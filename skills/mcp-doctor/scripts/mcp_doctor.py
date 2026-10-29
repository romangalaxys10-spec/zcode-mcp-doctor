#!/usr/bin/env python3
"""mcp_doctor.py: diagnose and optionally fix MCP server configs in AI coding clients.

Discovers MCP config files for ZCode, Claude Code, Cline, OpenCode, and Goose,
validates their JSON, detects each server's transport (stdio / http / sse),
and probes each server with a minimal initialize handshake (subprocess for
stdio, urllib POST for http). Prints a per-server status table with concrete
fix suggestions. With --fix, rewrites broken config entries in place.

Stdlib only. Python 3.8+. Exit codes:
  0  all discovered servers OK
  1  at least one server broken (or config unparseable)
  2  no config files found at all
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CLIENTS = {
    "zcode": [
        Path.home() / ".zcode" / "cli" / "mcp.json",
        Path.home() / ".zcode" / "mcp.json",
    ],
    "claude-code": [
        Path.home() / ".claude" / "mcp.json",
        Path.home() / ".claude.json",
    ],
    "cline": [
        Path.home() / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / "saoudrizwan.cline-cline" / "settings" / "mcp_settings.json",  # macOS
        Path.home() / ".config" / "Code" / "User" / "globalStorage" / "saoudrizwan.cline-cline" / "settings" / "mcp_settings.json",  # Linux
        Path.home() / "AppData" / "Roaming" / "Code" / "User" / "globalStorage" / "saoudrizwan.cline-cline" / "settings" / "mcp_settings.json",  # Windows
    ],
    "opencode": [
        Path.home() / ".opencode" / "mcp.json",
        Path.home() / ".config" / "opencode" / "mcp.json",
    ],
    "goose": [
        Path.home() / ".config" / "goose" / "mcp.json",
        Path.home() / "Library" / "Application Support" / "goose" / "mcp.json",
        Path.home() / ".config" / "goose" / "config.yaml",
    ],
}

INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "mcp-doctor", "version": "0.1.0"},
    },
}

# Keys that mark a server entry as stdio (command to spawn).
STDIO_KEYS = ("command",)
# Keys that mark it as http.
HTTP_KEYS = ("url", "httpUrl", "sseUrl")


def find_configs(only_client, probe_only):
    """Return list of (client, path) for existing config files."""
    found = []
    clients = [only_client] if only_client else sorted(CLIENTS.keys())
    for client in clients:
        for path in CLIENTS[client]:
            if path.exists():
                found.append((client, path))
    return found


def load_json(path):
    """Parse a JSON config file. Returns (data, error)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"
    except OSError as e:
        return None, f"cannot read file: {e}"


def extract_servers(data):
    """Return dict of server_name -> server_config, tolerating common shapes.

    ZCode/Claude Code: {"mcpServers": {...}}
    Cline:  {"mcpServers": {...}}
    OpenCode: {"mcp": {"server-name": {...}}}
    """
    if not isinstance(data, dict):
        return {}
    for key in ("mcpServers", "mcp"):
        servers = data.get(key)
        if isinstance(servers, dict):
            return servers
    return {}


def detect_transport(cfg):
    """Return 'stdio' | 'http' | 'sse' | 'unknown' plus the value to probe."""
    if not isinstance(cfg, dict):
        return "unknown", None
    for k in STDIO_KEYS:
        if k in cfg and cfg.get(k):
            return "stdio", cfg
    for k in HTTP_KEYS:
        if k in cfg and isinstance(cfg.get(k), str):
            url = cfg.get("sseUrl") or cfg.get("httpUrl") or cfg.get("url")
            if "sseUrl" in cfg:
                return "sse", url
            if "type" in cfg and str(cfg.get("type")).lower() in ("sse",):
                return "sse", url
            return "http", url
    if isinstance(cfg.get("url"), str):
        return "http", cfg["url"]
    return "unknown", None


def probe_stdio(cfg, timeout):
    """Spawn the command and send an initialize JSON-RPC request over stdio.

    Returns (ok, detail).
    """
    cmd = [cfg.get("command")] + [str(c) for c in (cfg.get("args") or [])]
    exe = cmd[0]
    # Resolve through PATH before claiming the binary is missing.
    exe_path = shutil.which(exe) or (exe if (Path(exe).exists()) else None)
    if not exe_path:
        return False, f"command not found: {exe} (install it or fix the path)"
    cmd[0] = exe_path
    env = dict(os.environ)
    env.update({k: str(v) for k, v in (cfg.get("env") or {}).items()})
    line = json.dumps(INITIALIZE_REQUEST)
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except OSError as e:
        return False, f"spawn failed: {e}"
    deadline = time.time() + timeout
    try:
        proc.stdin.write(line.encode("utf-8") + b"\n")
        proc.stdin.flush()
        # Read stdout until deadline or EOF; we only need one JSON line.
        out = b""
        while time.time() < deadline:
            chunk = proc.stdout.read(1)
            if not chunk:
                break
            out += chunk
            if b"\n" in out:
                break
            if len(out) > 100000:
                break
        time.sleep(0.2)
        try:
            proc.kill()
        except OSError:
            pass
        proc.wait(timeout=5)
        text = out.decode("utf-8", "replace").strip()
        if not text:
            return False, f"no response on stdout within {timeout}s"
        try:
            resp = json.loads(text)
        except json.JSONDecodeError:
            return False, f"stdout is not JSON (first 120 chars): {text[:120]!r}"
        if "error" in resp:
            return False, f"initialize error: {resp['error']}"
        server_info = (resp.get("result") or {}).get("serverInfo") or {}
        name = server_info.get("name", "unnamed")
        return True, f"handshake OK, server reports itself as {name!r}"
    finally:
        if proc.poll() is None:
            proc.kill()


def probe_http(url, timeout):
    """POST an initialize request to an http(s) MCP endpoint.

    Handles both JSON and SSE-style responses (text/event-stream with
    jsonrpc payloads). Returns (ok, detail).
    """
    body = json.dumps(INITIALIZE_REQUEST).encode("utf-8")
    from urllib.parse import urlparse
    p = urlparse(url)
    host = p.hostname
    if not host:
        return False, f"malformed URL: {url}"
    port = p.port or (443 if p.scheme == "https" else 80)
    if port:
        try:
            socket.create_connection((host, port), timeout=min(timeout, 5)).close()
        except OSError as e:
            return False, f"cannot connect to {host}:{port} ({e})"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(65536).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        snippet = e.read(400).decode("utf-8", "replace") if e.fp else ""
        return False, f"HTTP {e.code} {e.reason} from {url} {snippet[:120]}"
    except (urllib.error.URLError, OSError, socket.timeout) as e:
        return False, f"connection failed: {e}"
    text = raw.strip()
    # SSE framing: lines look like "data: {json}".
    if text.startswith("event:") or text.startswith("data:"):
        for line in text.splitlines():
            if line.startswith("data:"):
                text = line[5:].strip()
                break
    try:
        resp_json = json.loads(text)
    except json.JSONDecodeError:
        return False, f"response is not JSON (first 120 chars): {text[:120]!r}"
    if "error" in resp_json and "result" not in resp_json:
        return False, f"initialize error: {resp_json['error']}"
    info = (resp_json.get("result") or {}).get("serverInfo") or {}
    name = info.get("name", "unnamed")
    return True, f"handshake OK, server reports itself as {name!r}"


def _split_url(url):
    from urllib.parse import urlparse
    p = urlparse(url)
    return p.hostname, p.port and p.port or (443 if p.scheme == "https" else 80), None


def fix_suggestion(name, transport, cfg, ok, detail):
    """Concrete, copy-pasteable fix advice for a broken server."""
    if not ok:
        if "command not found" in detail:
            missing = detail.split("command not found: ")[1].split(" (")[0]
            return (
                f"Install {missing!r} or fix its path. Check `which {missing}`; "
                f"if installed via npm/brew, use the absolute path in 'command'."
            )
        if "cannot connect" in detail:
            return (
                "The URL host is unreachable. Check the URL, network, firewall, "
                "and whether the remote MCP host is actually running. If this is "
                "a stdio server misconfigured as http, replace 'url' with "
                "'command'/'args'."
            )
        if "HTTP 4" in detail or "HTTP 5" in detail:
            return (
                "The endpoint responded with an error status. Verify the path "
                "and required auth headers (many hosted MCP servers need an "
                "'Authorization' header in the config 'headers' block)."
            )
        if "no response on stdout" in detail:
            return (
                "Process started but never answered initialize. Try running the "
                "command manually with an initialize JSON-RPC line on stdin; the "
                "server may expect newline-delimited JSON or may need more start-up "
                "time (raise the probe timeout)."
            )
        if "not JSON" in detail:
            return (
                "The process printed non-JSON output first. Some servers log to "
                "stdout; point their logging at stderr or set the transport "
                "correctly."
            )
        return f"Probe failed: {detail}"
    if transport == "sse":
        return "SSE transport is legacy in most clients; prefer 'http' if the host supports it."
    if ok:
        return None
    return None


def rewrite_config(path, servers_data, broken, backup=True):
    """Drop broken server entries (after writing a .bak copy). Returns names removed."""
    if backup:
        b = path.with_suffix(path.suffix + ".bak")
        try:
            shutil.copy2(path, b)
        except OSError:
            pass
    removed = []
    if isinstance(servers_data, dict):
        for n in broken:
            if n in servers_data:
                del servers_data[n]
                removed.append(n)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(servers_data, f, indent=2)
        f.write("\n")
    return removed


def main():
    ap = argparse.ArgumentParser(
        description="Diagnose MCP server configs across AI coding clients."
    )
    ap.add_argument("--client", choices=sorted(CLIENTS.keys()),
                    help="only check one client")
    ap.add_argument("--probe", action="store_true", default=True,
                    help="probe each server (default)")
    ap.add_argument("--no-probe", dest="probe", action="store_false",
                    help="skip live probes, config validation only")
    ap.add_argument("--timeout", type=float, default=10.0,
                    help="per-server probe timeout seconds (default 10)")
    ap.add_argument("--fix", action="store_true",
                    help="rewrite configs, removing broken server entries "
                         "(a .bak copy is written first)")
    ap.add_argument("--json", action="store_true",
                    help="emit a machine-readable JSON report instead of the table")
    args = ap.parse_args()

    configs = find_configs(args.client, probe_only=False)
    if not configs:
        print("No MCP config files found.", file=sys.stderr)
        print("Checked:", file=sys.stderr)
        for c in sorted(CLIENTS.keys()):
            for p in CLIENTS[c]:
                mark = "yes" if p.exists() else " "
                print(f"  [{mark}] {p}", file=sys.stderr)
        sys.exit(2)

    report = []
    any_broken = False
    for client, path in configs:
        data, err = load_json(path)
        if err:
            any_broken = True
            report.append({
                "client": client, "config": str(path), "server": None,
                "transport": None, "status": "config-error", "detail": err,
                "fix": "Repair the JSON by hand (or run this tool with --fix after fixing it).",
            })
            continue
        servers = extract_servers(data)
        if not servers:
            report.append({
                "client": client, "config": str(path), "server": None,
                "transport": None, "status": "empty",
                "detail": "no server entries found under mcpServers/mcp",
                "fix": None,
            })
            continue
        broken = []
        for name, cfg in servers.items():
            transport, target = detect_transport(cfg)
            if args.probe and target is not None:
                if transport == "stdio":
                    ok, detail = probe_stdio(cfg, args.timeout)
                elif transport in ("http", "sse"):
                    ok, detail = probe_http(target, args.timeout)
                else:
                    ok, detail = None, "unknown transport"
                fix = fix_suggestion(name, transport, cfg, ok, detail) if not ok else None
            else:
                ok, detail, fix = None, "probe skipped", None
            status = "ok" if ok else ("skipped" if ok is None and not args.probe else "broken")
            if ok is False:
                any_broken = True
                broken.append(name)
            report.append({
                "client": client, "config": str(path), "server": name,
                "transport": transport, "status": status,
                "detail": detail, "fix": fix,
            })
        if args.fix and broken:
            # `servers` is a reference into `data`, so del mutates the document.
            removed = rewrite_config(path, data, broken)
            print(f"[--fix] {path}: removed {removed}, backup at {path}.bak", file=sys.stderr)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{'CLIENT':<12} {'SERVER':<24} {'TRANSPORT':<8} {'STATUS':<14} DETAIL")
        print("-" * 100)
        for r in report:
            server = r["server"] or "-"
            print(f"{r['client']:<12} {server:<24} {(r['transport'] or '-'):<8} "
                  f"{r['status']:<14} {r['detail']}")
            if r.get("fix"):
                print(f"{'':<12} -> fix: {r['fix']}")
    sys.exit(1 if any_broken else 0)


if __name__ == "__main__":
    main()
