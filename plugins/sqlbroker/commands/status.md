---
description: Check mcp-sqlbroker service health and configured aliases
---

Run a 3-step health check for mcp-sqlbroker. Detect OS first; the service backend differs.

## Steps

1. **Service status** — depends on OS:
   - Windows: `(Get-ScheduledTask -TaskName mcp-sqlbroker).State` (expect `Running`)
   - Linux:   `systemctl is-active mcp-sqlbroker` (expect `active`)
   - macOS:   `launchctl list | grep com.creamac.mcp-sqlbroker` (PID > 0 expected)

2. **HTTP health + version** — works the same on every OS:
   ```bash
   curl -fsS http://127.0.0.1:8765/health           # expect {"ok":true,"server":"sqlbroker"}
   ```
   ```powershell
   Invoke-WebRequest 'http://127.0.0.1:8765/health' -UseBasicParsing | Select-Object -Expand Content
   ```
   Optionally probe broker version via `initialize`:
   ```bash
   curl -fsS -X POST http://127.0.0.1:8765/mcp -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
   ```
   Expected `result.serverInfo.version` = current plugin version (e.g. `2.7.1`).

3. **Configured aliases** — prefer the MCP tool when wired:
   - `mcp__sqlbroker__list_aliases()` (no args)
   - Fallback CLI:
     - Windows: `D:\util\mcp-sqlbroker\python313\python.exe D:\util\mcp-sqlbroker\manage_conn.py list`
     - Linux/macOS: `/opt/mcp-sqlbroker/.venv/bin/python3 /opt/mcp-sqlbroker/manage_conn.py list`

Report all 3 steps to the user. If anything fails, propose a fix:

| Symptom | Fix |
|---|---|
| Task `Disabled` / `Ready` (Windows) | Admin shell → `Start-ScheduledTask -TaskName mcp-sqlbroker` |
| systemd `inactive` / `failed` | `sudo systemctl restart mcp-sqlbroker`; check `journalctl -u mcp-sqlbroker -n 50` |
| launchd plist not loaded | `sudo launchctl load /Library/LaunchDaemons/com.creamac.mcp-sqlbroker.plist` |
| Health unreachable | Tail `<InstallDir>/service.log` (and `service.err.log` if it exists) |
| Broker version mismatches plugin version | Run `/sqlbroker:update` to refresh server.py + manage_conn.py and bounce the service |
| `master.key did not match (HMAC mismatch)` | Someone replaced master.key. Restore from backup or re-add aliases. |
| `No encrypted password for alias '<name>'` | v2.0–2.2 keyring migration didn't complete. Run `manage_conn.py migrate` (admin/sudo) or `/sqlbroker:add <alias> --force` to re-add. |
| Aliases call returns `permission_denied: VIEW SERVER STATE` (only `get_active_queries`) | Grant `VIEW SERVER STATE` to the alias's SQL login, or use a privileged alias for that one tool. |
