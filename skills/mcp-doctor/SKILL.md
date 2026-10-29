---
name: mcp-doctor
description: Diagnose and repair MCP server configs across ZCode, Claude Code, Cline, OpenCode, and Goose. Use when a user says an MCP server will not start, shows "transport" errors, gets no tools from an MCP server, asks why their MCP config is broken, or asks to validate/fix MCP settings. Also use before shipping a new MCP config, to catch a stdio entry written as http (the most common community failure) before it breaks the client.
---

# mcp-doctor

Find every MCP config on this machine, prove each server actually answers an
`initialize` handshake, and point at the exact broken entry with a copy-paste
fix. The #1 community failure is a transport mismatch: a stdio server
(described with `command` + `args`) pointed at, or written as, an `http`/`sse`
URL, or vice versa. This tool detects that, probes live, and can rewrite the
config.

## Standard config paths (what the script checks per OS)

| Client      | Path                                                                                                  |
|-------------|-------------------------------------------------------------------------------------------------------|
| ZCode       | `~/.zcode/cli/mcp.json`, `~/.zcode/mcp.json`                                                          |
| Claude Code | `~/.claude/mcp.json`, `~/.claude.json`                                                                |
| Cline       | VS Code user globalStorage `saoudrizwan.cline-cline/settings/mcp_settings.json` (per-OS base dir)      |
| OpenCode    | `~/.opencode/mcp.json`, `~/.config/opencode/mcp.json`                                                 |
| Goose       | `~/.config/goose/mcp.json` (also `Library/Application Support/goose/mcp.json` on macOS)               |

The script discovers the standard paths for macOS, Linux, and Windows and
only reports the files that exist.

## 1. Run the probe

```bash
python3 scripts/mcp_doctor.py
```

This:

1. Discovers every existing client config file.
2. Parses each as JSON. A parse error is reported per file and stops the probe
   for that file (you cannot trust a config the client itself will refuse).
3. For each `mcpServers` / `mcp` entry, detects the transport:
   - `stdio` when a `command` key is present.
   - `http` when a `url` / `httpUrl` key is present.
   - `sse` when a `sseUrl` key or `type: "sse"` is present.
4. Probes each reachable server:
   - stdio: spawn the command, send an `initialize` JSON-RPC line on stdin,
     read stdout until a JSON response or the `--timeout` deadline, then kill
     the process. Missing binary, silent process, and non-JSON chatter are all
     distinguished in the `detail` column.
   - http/sse: POST the `initialize` request with urllib, read JSON or an SSE
     `data:` frame, and report non-2xx bodies.
5. Prints a status table: client, server name, transport, status
   (`ok`/`broken`/`skipped`/`config-error`), the failure detail, and a concrete
   fix line.

Flags:
- `--client <zcode|claude-code|cline|opencode|goose>`: check one client only.
- `--no-probe`: static validation only (JSON + transport detection), no spawns
  or network.
- `--timeout N`: per-server handshake deadline in seconds (default 10).
- `--json`: machine-readable report for downstream tooling.
- `--fix`: rewrite each config, removing only the server entries that probed
  broken, after writing a `<file>.bak` copy. It never invents server entries,
  never touches a config that failed to parse, and leaves working entries
  untouched.

## 2. Read the table

Statuses:
- `ok` - handshake answered with a JSON `initialize` result.
- `broken` - the probe failed. The `detail` names the class:
  - `command not found: X` - the binary is missing or the path is wrong.
  - `cannot connect to host:port` - URL host unreachable (or the host is down).
  - `HTTP 4xx/5xx` - endpoint refused or errored the request.
  - `no response on stdout within Ns` - process started but never answered.
  - `stdout is not JSON` - process chatters non-JSON on stdout.
- `config-error` - the whole file is not valid JSON.
- `empty` / `skipped` - no entries, or probe disabled.

When a row is `broken`, fix exactly what the `fix:` line says. Do not bulk
edit the config; a config the client cannot parse makes every server in it
disappear, not just the broken one.

## 3. Apply the fix

Edit the entry by hand (or use `--fix` to drop broken entries and restore
from `.bak` if needed). Then re-run the probe:

```bash
python3 scripts/mcp_doctor.py --client zcode
```

Expect exit code `0` when every probed server is OK, `1` when at least one is
broken, `2` when no config files were found.

## Guardrails

- The stdio probe spawns the configured command with a hard timeout and then
  kills it. Only point this tool at servers you trust to start safely, or
  use `--no-probe` for a read-only check.
- `--fix` is the only write path, and it removes broken entries; it does not
  add or repair entries. A stdio/server mismatch is fixed by hand, guided by
  the `fix:` line.
- No credentials are printed. The probe sends only an `initialize` request
  with an empty capabilities object.
- Servers that require authentication (headers, tokens) will fail the probe
  with a 401/403; that is expected. The tool reports the status, it does not
  fill in credentials for you.
- The script is Python 3 stdlib only and runs on macOS, Linux, and Windows.
