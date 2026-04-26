---
name: sqlbroker-test
description: Test an SQL connection alias by running a quick identity query. Triggers on "/sqlbroker-test", "/sqlbroker:test", "test alias", "verify sqlbroker connection".
---

# Test an alias

Test the alias `$ARGUMENTS` (or `$1` on Codex) by running a quick identity query (`@@SERVERNAME`, `DB_NAME()`, `SUSER_SNAME()`, `@@VERSION`).

```powershell
# Windows
D:\util\mcp-sqlbroker\python313\python.exe D:\util\mcp-sqlbroker\manage_conn.py test $ARGUMENTS
```

```bash
# Linux / macOS
/opt/mcp-sqlbroker/.venv/bin/python3 /opt/mcp-sqlbroker/manage_conn.py test $ARGUMENTS
```

If it fails, check:
- Network reachability (host/port)
- SQL login still valid (password rotated? — `/sqlbroker:rotate <alias>`)
- Driver match — broker default is `ODBC Driver 17 for SQL Server`; switch to `18` in `connections.json` if the server requires TLS
