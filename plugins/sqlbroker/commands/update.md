---
description: Update the deployed broker code to match the current plugin version
---

Refresh the broker code in `<InstallDir>` (default `D:\util\mcp-sqlbroker` on Windows, `/opt/mcp-sqlbroker` on Unix) so it matches the slash commands and skill that came with the plugin you just upgraded via `/plugin install sqlbroker@creamac/sqlbroker-plugin`.

This is a **fast** update — it does NOT re-download Python / ODBC / NSSM, it does NOT touch `~/.claude.json`, and it does NOT alter your `connections.json` or `master.key`. It just copies the latest `server.py`, `manage_conn.py`, `stdio_proxy.py`, `run_stdio_proxy.bat`, then bounces the service.

## Steps

1. Detect OS (Windows vs Linux/macOS).

2. Show the user the deployed broker version vs the plugin version (so they can confirm an actual upgrade is needed):

   ```bash
   curl -fsS http://127.0.0.1:8765/mcp -X POST \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
     | python -c "import json,sys; d=json.load(sys.stdin); print('broker:', d['result']['serverInfo']['version'])"
   ```

3. **Windows path:** Tell the user a UAC dialog will pop up (needs admin to bounce the Scheduled Task). Then:

   ```powershell
   $deploy = Join-Path "${CLAUDE_PLUGIN_ROOT}" 'scripts\deploy.ps1'
   Start-Process powershell.exe -Verb RunAs -ArgumentList @(
     '-NoProfile', '-ExecutionPolicy', 'Bypass',
     '-File', $deploy,
     '-RefreshOnly', '-AutoWire'
   ) -Wait
   ```

   `-RefreshOnly` makes deploy.ps1 skip Python / ODBC / NSSM steps entirely. `-AutoWire` is harmless on a refresh (the entry already exists).

4. **Linux / macOS path:** prompt for sudo, then:

   ```bash
   sudo "${CLAUDE_PLUGIN_ROOT}/scripts/deploy.sh" --refresh-only
   ```

   (deploy.sh `--refresh-only` skips venv/keyring deps and just copies files + restarts the systemd unit / launchd plist.)

5. Verify the broker is now serving the new version:

   ```bash
   curl -fsS http://127.0.0.1:8765/mcp -X POST -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
   ```

6. Optional: run `/sqlbroker:list` to confirm aliases are intact.

## When to use

- After running `/plugin install sqlbroker@creamac/sqlbroker-plugin` to pull a new plugin version
- When you've manually edited the broker source (or pulled a git update) and want the running service to pick it up

## When NOT to use

- First-time install — use `/sqlbroker:install` instead (full setup)
- After moving `connections.json` or `master.key` — backup and restore those manually first
