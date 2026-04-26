---
description: Update the deployed broker code to match the current plugin version
---

Refresh the broker code in `<InstallDir>` (default `D:\util\mcp-sqlbroker` on Windows, `/opt/mcp-sqlbroker` on Unix) so it matches the plugin you just upgraded.

> **Maintenance note:** canonical content also at `plugins/sqlbroker/skills/sqlbroker-update/SKILL.md`. Keep in sync.

This is a **fast** update — it does NOT re-download Python / ODBC, it does NOT touch `~/.claude.json` or `~/.codex/config.toml`, and it does NOT alter your `connections.json` or `master.key`. It just copies the latest `server.py`, `manage_conn.py`, `stdio_proxy.py`, `run_stdio_proxy.{bat,sh}`, then bounces the service.

## Steps

1. Detect OS (Windows vs Linux/macOS).

2. **Windows path:** Tell the user a UAC dialog will pop up (needs admin to bounce the Scheduled Task). Then:

   ```powershell
   $deploy = Join-Path "${CLAUDE_PLUGIN_ROOT}" 'scripts\deploy.ps1'
   Start-Process powershell.exe -Verb RunAs -ArgumentList @(
     '-NoProfile', '-ExecutionPolicy', 'Bypass',
     '-File', $deploy,
     '-RefreshOnly', '-AutoWire'
   ) -Wait
   ```

3. **Linux / macOS path:** prompt for sudo, then:

   ```bash
   sudo "${CLAUDE_PLUGIN_ROOT}/scripts/deploy.sh" --refresh-only
   ```

4. Verify the broker is now serving the new version:

   ```bash
   curl -fsS http://127.0.0.1:8765/mcp -X POST -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
   ```

## When NOT to use

- First-time install — use `/sqlbroker:install` (full setup)
- After moving `connections.json` or `master.key` — backup and restore those manually first
- When you also want to re-wire MCP — `--refresh-only` skips wiring, re-run without it
