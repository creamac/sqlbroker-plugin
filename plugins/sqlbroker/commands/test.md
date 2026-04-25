---
description: Test an SQL connection alias
argument-hint: <alias_name>
---

Test the alias `$ARGUMENTS` by running a quick identity query (`@@SERVERNAME`, `DB_NAME()`, `SUSER_SNAME()`, `@@VERSION`).

```powershell
D:\util\mcp-sqlbroker\.venv\Scripts\python.exe D:\util\mcp-sqlbroker\manage_conn.py test $ARGUMENTS
```

If it fails, check:
- Network reachability (host/port)
- SQL login still valid (password rotated?)
- Driver match — broker default is `ODBC Driver 17 for SQL Server`; switch to `18` in `connections.json` if the server requires TLS
