---
name: mcp-doctor
description: Diagnose and fix MCP server configs across ZCode, Claude Code, Cline, OpenCode, and Goose
allowed-tools: Read, Bash, Write
argument-hint: [optional client name]
---

Invoke the `mcp-doctor` skill with this input: **$ARGUMENTS**

Run `python3 scripts/mcp_doctor.py` (add `--client <name>` when the user names
a client, add `--fix` only when the user explicitly asks to rewrite configs).
Show the status table, explain each broken row in plain language, and end by
re-running the probe to confirm the fixes.

If no arguments are given, probe every client whose config file exists and
report all of them. If no config files are found at all (exit 2), list the
standard paths you checked so the user knows where to look.
