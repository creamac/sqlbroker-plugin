---
description: Add a new MSSQL connection alias (interactive)
argument-hint: [alias_name]
---

Add a new MSSQL connection alias to mcp-sqlbroker. Args: $ARGUMENTS.

## Flow (collect non-secrets in Claude, password in user's terminal)

1. **Alias name** — if `$ARGUMENTS` is empty, ask the user (short, snake_case: `prod_main`, `staging_db`).

2. **Auth mode** — use `AskUserQuestion` with these options:
   - `SQL login (Recommended)` — username + password (most common)
   - `Windows Authentication` — Trusted_Connection; broker process identity is used. **Warn:** the broker runs as SYSTEM by default — only works for local SQL Server unless deploy.ps1 was given `-ServiceUser/-ServicePassword` to run as a domain account.
   - `Azure AD service principal` — for Azure SQL DB / Managed Instance; needs ODBC 18+, client_id + client_secret.

3. **Host** — chat free-text. Examples:
   - `192.168.1.10\INSTANCE`, `host,1433`, `tcp:host.database.windows.net,1433` (Azure)

4. **User / password (depends on auth mode):**
   - **SQL login** → ask user via chat; password collected by user in their terminal (step 6)
   - **Windows** → skip — no user/password fields needed
   - **AAD service principal** → user = `client_id` (UUID); password = `client_secret` (collected in terminal)

5. **default_database** — chat (optional, blank to skip). **Policy** — `AskUserQuestion`: `readonly (Recommended)` / `exec-only` / `full`.

6. **Password** — DO NOT collect via chat. Print the command for the user to run in their own terminal — `manage_conn.py` prompts for password via `getpass` (hidden input):

   **SQL login:**
   ```powershell
   D:\util\mcp-sqlbroker\python313\python.exe D:\util\mcp-sqlbroker\manage_conn.py add <alias> ^
       --host '<host>' --user '<user>' --database '<db>' --policy <policy> --auth-mode sql --force
   ```

   **Windows auth (no password):**
   ```powershell
   D:\util\mcp-sqlbroker\python313\python.exe D:\util\mcp-sqlbroker\manage_conn.py add <alias> ^
       --host '<host>' --database '<db>' --policy <policy> --auth-mode windows --force
   ```

   **Azure AD service principal:**
   ```powershell
   D:\util\mcp-sqlbroker\python313\python.exe D:\util\mcp-sqlbroker\manage_conn.py add <alias> ^
       --host '<host>' --user '<client_id>' --database '<db>' --policy <policy> --auth-mode aad-spn --force
   ```

   Linux/Mac: replace `D:\util\mcp-sqlbroker\python313\python.exe` with `/opt/mcp-sqlbroker/.venv/bin/python3` and use `\` line-continuations.

7. After the user reports it ran successfully, verify with `/sqlbroker:test <alias>`.

## Safety

- Never accept the password as a `--password` CLI arg from the user — it would enter shell history.
- Never echo the password back in chat.
- Broker re-reads `connections.json` on every request — no service restart.
- For production DBs, prefer `readonly` AND a SQL login with `db_datareader` only.
