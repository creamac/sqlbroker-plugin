---
description: Remove an SQL connection alias
argument-hint: <alias_name>
---

Remove the alias `$ARGUMENTS` from mcp-sqlbroker.

Confirm with the user before proceeding (this is destructive — they will need to re-enter the password to add it back).

```powershell
D:\util\mcp-sqlbroker\.venv\Scripts\python.exe D:\util\mcp-sqlbroker\manage_conn.py remove $ARGUMENTS
```

The broker re-reads `connections.json` on the next request — no service restart needed.
