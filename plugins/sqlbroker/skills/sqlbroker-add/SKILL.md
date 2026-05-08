---
name: sqlbroker-add
description: Add a new MSSQL connection alias to mcp-sqlbroker. Collects host/user/db/policy in chat. Password collected via the user's terminal by default (getpass hidden input); chat-paste flow available on explicit opt-in. Triggers on "/sqlbroker-add", "/sqlbroker:add", "add new alias", "add database connection", "register new mssql alias".
---

# Add a new MSSQL connection alias

Add a new MSSQL connection alias to mcp-sqlbroker. The alias name comes from `$ARGUMENTS` (or `$1` on Codex).

## Flow (collect non-secrets in chat, password in user's terminal)

1. **Alias name** — if `$ARGUMENTS` is empty, ask the user (short, snake_case: `prod_main`, `staging_db`).

2. **Auth mode** — use `AskUserQuestion` (or equivalent picker) with these options:
   - `SQL login (Recommended)` — username + password (most common)
   - `Windows Authentication` — Trusted_Connection; broker process identity is used. **Warn:** the broker runs as SYSTEM by default — only works for local SQL Server unless `deploy.ps1` was given `-ServiceUser/-ServicePassword` to run as a domain account.
   - `Azure AD service principal` — for Azure SQL DB / Managed Instance; needs ODBC 18+, client_id + client_secret.

3. **Host** — chat free-text. Examples:
   - `192.168.1.10\INSTANCE`, `host,1433`, `tcp:host.database.windows.net,1433` (Azure)

4. **User / password (depends on auth mode):**
   - **SQL login** → ask user via chat; password collected by user in their terminal (step 6)
   - **Windows** → skip — no user/password fields needed
   - **AAD service principal** → user = `client_id` (UUID); password = `client_secret` (collected in terminal)

5. **default_database** — chat (optional, blank to skip). **Policy** — `AskUserQuestion`: `readonly (Recommended)` / `exec-only` / `full`.

5b. **Charset (optional, default `cp874`)** — codepage for legacy ANSI VARCHAR/CHAR columns. The default `cp874` covers Thai_CI_AS (TIS-620) which is the common case in TH environments. Only ask if the target server's default collation is non-Thai (e.g. `Latin1_General_CI_AS` → use `cp1252`, Japanese → `cp932`). NVARCHAR is unaffected by this setting (always UTF-16). If unsure, accept the default — wrong charset shows up as `?` or mojibake on Thai data and is a one-flag fix.

6. **Password — pick the flow** (default = terminal-only; chat-paste only on explicit user opt-in):

   **6a. Terminal flow (default, recommended)** — DO NOT collect via chat. Print the command for the user to run in their own terminal — `manage_conn.py` prompts for password via `getpass` (hidden input):

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

   **6b. Chat-paste flow (only when user explicitly opts in)** — trigger on "paste in chat ok", "skip terminal step", "ขอ paste มาใน chat", "ขี้เกียจเปิด terminal" or similar.

   Before accepting the password, **show this one-line warning** and ask the user to confirm with `yes`:

   > ⚠️ Password จะอยู่ใน conversation transcript + Claude API prompt cache (TTL 5 min) + Bash tool args ตลอดไป. Trade-off: ไม่ต้องเปิด terminal. ยืนยันด้วยการพิมพ์ `yes`?

   On confirmation, ask the user to paste the password in the next message. Then run the equivalent command **non-interactively** with `--password` so no terminal step is needed:

   ```powershell
   D:\util\mcp-sqlbroker\python313\python.exe D:\util\mcp-sqlbroker\manage_conn.py add <alias> ^
       --host '<host>' --user '<user>' --database '<db>' --policy <policy> --auth-mode sql ^
       --password '<paste-here>' --force
   ```

   After running, **do not echo the password back** in any subsequent message. Treat it as opaque from that point onward.

7. After the user reports it ran successfully (or you ran it inline in flow 6b), verify with `/sqlbroker:test <alias>` (Claude) or `/sqlbroker-test <alias>` (Codex).

## Safety

- Default to the terminal flow (6a). Use chat-paste flow (6b) only on explicit user opt-in — never silently route through `--password`.
- Show the trade-off warning in 6b every time. Do not skip it on repeated invocations.
- Never echo the password back in chat or in any tool result summary.
- Never store the password in a file the user did not ask for. Pass it through to `manage_conn.py` and forget it.
- Broker re-reads `connections.json` on every request — no service restart.
- For production DBs, prefer `readonly` AND a SQL login with `db_datareader` only.
