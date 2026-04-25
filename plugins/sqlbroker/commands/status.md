---
description: Check mcp-sqlbroker service health and configured aliases
---

Run a 3-step health check for mcp-sqlbroker:

1. **Service status** — `D:\util\nssm.exe status mcp-sqlbroker` (expect `SERVICE_RUNNING`)
2. **HTTP health** — `Invoke-WebRequest http://127.0.0.1:8765/health -UseBasicParsing | Select-Object -Expand Content` (expect `{"ok":true,"server":"sqlbroker"}`)
3. **Configured aliases** — `D:\util\mcp-sqlbroker\.venv\Scripts\python.exe D:\util\mcp-sqlbroker\manage_conn.py list`

Report each step. If anything fails, propose a fix:

| Symptom | Fix |
|---|---|
| Service `STOPPED` | Start: `D:\util\nssm.exe start mcp-sqlbroker` (admin) |
| Service `PAUSED` | `D:\util\nssm.exe reset mcp-sqlbroker Throttle` then `start` (admin) |
| Health unreachable | Tail `D:\util\mcp-sqlbroker\service.err.log` and `service.log` |
| `service.err.log` empty + service won't start | venv probably points at Microsoft Store Python — run `${CLAUDE_PLUGIN_ROOT}\scripts\option-b-rebuild.ps1` (admin) |
