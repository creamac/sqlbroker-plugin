---
description: Add a new MSSQL connection alias
argument-hint: [alias_name]
---

Add a new MSSQL connection alias to mcp-sqlbroker. The arguments after the slash command are: $ARGUMENTS.

## Steps

1. Determine the broker install directory. Default: `D:\util\mcp-sqlbroker`. If the user has installed elsewhere, ask before proceeding.
2. If the user did not provide an alias name in `$ARGUMENTS`, ask for one (short, snake_case, e.g. `prod_main`, `dev_70_31`).
3. Ask the user for:
   - **host** — e.g. `192.168.1.10\INSTANCE` or `host,1433`
   - **user** — SQL login name
   - **password** — DO NOT echo it. Tell the user to type it; we will pass it via `MCP_PWD` env var, not the command line.
   - **default_database** — optional, can be blank
   - **policy** — `readonly` | `full` | `exec-only`. Default to `readonly` and recommend it unless the user is operating on a sandbox they explicitly designated as test.
4. Add the alias using the env-var pattern (avoids password leaking into shell history):

   ```powershell
   $env:MCP_PWD = '<password from user>'
   $src = @'
   import os, sys
   sys.path.insert(0, r"D:\util\mcp-sqlbroker")
   from manage_conn import load, save
   from server import encrypt_password
   cfg = load()
   cfg["connections"]["<alias>"] = {
       "host": "<host>",
       "user": "<user>",
       "password_dpapi": encrypt_password(os.environ["MCP_PWD"]),
       "default_database": "<db_or_empty>",
       "policy": "<policy>",
       "driver": "ODBC Driver 17 for SQL Server",
   }
   save(cfg)
   '@
   $src | & "D:\util\mcp-sqlbroker\.venv\Scripts\python.exe" -
   $env:MCP_PWD = $null
   ```

5. Test with `/sqlbroker:test <alias>` (or run `manage_conn.py test <alias>` directly).
6. Confirm policy with the user, especially if they picked `full` for a non-test box.

## Safety

- Never put the password as a command-line arg.
- The broker re-reads `connections.json` on every request — no service restart required.
- For production DBs, prefer `readonly` AND a SQL login that has `db_datareader` only.
