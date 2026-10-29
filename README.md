# MCP Doctor

<p align="center">
  <a href="https://z.ai/subscribe?ic=R0K78RJKNW"><img alt="z.ai coding plans - 10% OFF coupon" src="https://img.shields.io/badge/z.ai%20coding%20plans-10%25%20OFF%20coupon-blueviolet" /></a>
  <a href="https://zcode.z.ai/invite/ALWM9JUA"><img alt="Try ZCode free" src="https://img.shields.io/badge/Try%20ZCode-free%20invite-0969da" /></a>
</p>

One command to find out why your MCP servers will not start in ZCode, Claude Code, Cline, OpenCode, or Goose.

## Why

Broken MCP configs are the most common reason "my tools are missing" threads appear in client forums. The usual cause is a transport mismatch: a stdio server written as an http URL, a missing binary path, or a URL that is down. Clients silently drop the whole server, and the config file itself gives no hint. This tool proves each server answers an `initialize` handshake and names the exact broken entry.

## How it works

1. Discovers config files at the standard per-client, per-OS paths.
2. Validates JSON; reports unparseable files without guessing.
3. Detects each entry's transport (`command` is stdio, `url`/`httpUrl` is http, `sseUrl` or `type: sse` is sse).
4. Probes each server: stdio via subprocess + initialize JSON-RPC line with a timeout, http via urllib POST.
5. Prints a status table (client / server / transport / status / detail / fix). With `--fix` it rewrites configs, dropping only broken entries after writing a `.bak`.

## Install

Option A: self-installable marketplace. Download or clone this repo, open ZCode, go to Plugin Marketplace, Add, Add Plugin Marketplace, paste the folder path, then Install `mcp-doctor`.

Option B: manual copy. Copy the `mcp-doctor` folder into your ZCode workspace `plugins/` directory and reload plugins.

## Try it

```
/mcp-doctor
```

Expected result: a table of every MCP server on this machine, e.g.

```
CLIENT       SERVER            TRANSPORT  STATUS      DETAIL
claude-code  my-server        stdio      broken      command not found: my-mcp-server (install it or fix the path)
             -> fix: Install 'my-mcp-server' or fix its path. Check `which my-mcp-server`...
```

Then `python3 skills/mcp-doctor/scripts/mcp_doctor.py --client zcode --no-probe` for a read-only check.

## Requirements

Python 3.8+, stdlib only. No pip dependencies. Probes spawn your configured server commands, so keep `--no-probe` for machines where that is not safe.

---

<p align="center">
  <a href="https://z.ai/subscribe?ic=R0K78RJKNW"><img alt="z.ai coding plans - 10% OFF coupon" src="https://img.shields.io/badge/z.ai%20coding%20plans-10%25%20OFF%20coupon-blueviolet" /></a>
  <a href="https://zcode.z.ai/invite/ALWM9JUA"><img alt="Try ZCode free" src="https://img.shields.io/badge/Try%20ZCode-free%20invite-0969da" /></a>
</p>

## License

MIT.
