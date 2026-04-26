---
description: Remove an SQL connection alias
argument-hint: <alias_name>
---

Remove the alias `$ARGUMENTS` from mcp-sqlbroker.

> **Maintenance note:** canonical content also at `plugins/sqlbroker/skills/sqlbroker-remove/SKILL.md`. Keep in sync.

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
