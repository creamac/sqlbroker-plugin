---
name: sqlbroker-remove
description: Delete an SQL connection alias from mcp-sqlbroker config. Destructive — confirm with the user first. Triggers on "/sqlbroker-remove", "/sqlbroker:remove", "delete alias", "remove sqlbroker connection".
---

# Remove an alias

Remove the alias `$ARGUMENTS` (or `$1` on Codex) from mcp-sqlbroker.

**Confirm with the user before proceeding** — this is destructive. They will need to re-enter the password to add it back.

```powershell
# Windows
D:\util\mcp-sqlbroker\python313\python.exe D:\util\mcp-sqlbroker\manage_conn.py remove $ARGUMENTS
```

```bash
# Linux / macOS
/opt/mcp-sqlbroker/.venv/bin/python3 /opt/mcp-sqlbroker/manage_conn.py remove $ARGUMENTS
```

The broker re-reads `connections.json` on the next request — no service restart needed. Pooled connections for the removed alias get dropped at next checkout (ping fails → conn closed → not re-pooled).
