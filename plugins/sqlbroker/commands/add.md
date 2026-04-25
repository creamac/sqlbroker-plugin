---
description: Add a new MSSQL connection alias (interactive)
argument-hint: [alias_name]
---

Add a new MSSQL connection alias to mcp-sqlbroker. Args: $ARGUMENTS.

## Flow (collect non-secrets in Claude, password in user's terminal)

1. **Alias name** — if `$ARGUMENTS` is empty, ask the user (short, snake_case: `prod_main`, `staging_db`).

2. **Host, user, default_database** — ask the user one at a time in chat (free-text):
   - host (e.g. `192.168.1.10\INSTANCE` or `host,1433`)
   - user (SQL login)
   - default_database (optional — blank to skip)

3. **Policy** — use the `AskUserQuestion` tool with these options:
   - `readonly (Recommended)` — block DML/DDL/EXEC; SELECT only
   - `exec-only` — SELECT + EXEC stored procedures; block DML/DDL
   - `full` — anything (use only for test sandboxes)

4. **Password** — DO NOT collect via chat (lands in transcript). Instead, print the exact command for the user to run in their own terminal — `manage_conn.py add` will prompt for the password securely with `getpass`:

   ```powershell
   D:\util\mcp-sqlbroker\python313\python.exe D:\util\mcp-sqlbroker\manage_conn.py add <alias> ^
       --host '<host>' --user '<user>' --database '<db_or_empty>' --policy <policy> --force
   ```

   ```bash
   /opt/mcp-sqlbroker/.venv/bin/python3 /opt/mcp-sqlbroker/manage_conn.py add <alias> \
       --host '<host>' --user '<user>' --database '<db_or_empty>' --policy <policy> --force
   ```

   The `--force` flag overwrites an existing alias; the script omits `--password`, so it prompts via `getpass.getpass()` (hidden input on the user's terminal).

5. After the user reports it ran successfully, verify with `/sqlbroker:test <alias>`.

## Safety

- Never accept the password as a `--password` CLI arg from the user — it would enter shell history.
- Never echo the password back in chat.
- Broker re-reads `connections.json` on every request — no service restart.
- For production DBs, prefer `readonly` AND a SQL login with `db_datareader` only.
