# Changelog

## 0.1.0 - 2026-10-29

- Initial release: MCP config discovery for ZCode, Claude Code, Cline, OpenCode, and Goose.
- JSON validation and stdio/http/sse transport detection, including the stdio-vs-http mismatch check.
- Live probes: stdio spawn + initialize JSON-RPC handshake with timeout, http POST via urllib.
- Per-server status table (OK / broken / why / exact fix), `--json` report, and `--fix` config rewrite with backup.
