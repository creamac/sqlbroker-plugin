# sqlbroker-marketplace

Claude Code plugin marketplace for managing local MSSQL access **without ever putting credentials in the conversation**.

## What's in it

### `sqlbroker` plugin

Alias-based MSSQL broker for Windows. A local NSSM-managed service holds DPAPI-encrypted passwords; Claude calls databases by alias only — passwords never enter the chat or any prompt.

- 🛢️ **Auto-activating skill** — any DB-query intent (`"select from X"`, `"เช็ค proc ใน Y"`) routes through the broker
- ⚡ **6 slash commands** — `install`, `add`, `list`, `test`, `remove`, `status`
- 🔌 **MCP server** registered automatically (stdio→HTTP shim talking to the local broker)
- 🛡️ **3 policies** — `readonly` (block DML/DDL/EXEC), `exec-only` (SELECT + EXEC), `full`

→ Plugin user guide: [`plugins/sqlbroker/README.md`](plugins/sqlbroker/README.md)

---

## Quickstart (Windows)

### 0. Prerequisites

| | Why |
|---|---|
| Windows 10 / 11 / Server 2016+ | DPAPI lives here |
| Claude Code | host for the plugin — https://claude.com/claude-code |

That's it. **You don't need to install Python, ODBC Driver, or NSSM yourself** — `deploy.ps1` downloads the embedded Python, the ODBC driver, and NSSM during install.

### 1. Install the plugin

In a Claude Code session:

```
/plugin marketplace add creamac/sqlbroker-plugin
/plugin install sqlbroker@creamac/sqlbroker-plugin
/reload-plugins
```

### 2. Install the local Windows service

```
/sqlbroker:install
```

That's the whole step. The slash command launches `deploy.ps1` elevated via UAC — click "Yes" on the dialog and a PowerShell window will run the installer. It will:

- Download Python 3.13 embeddable into `D:\util\mcp-sqlbroker\python313\` (no system Python install needed)
- Bootstrap pip, install `pyodbc` + `pywin32`
- Auto-install **ODBC Driver 18 for SQL Server** if missing
- Auto-download **NSSM**
- Register and start the `mcp-sqlbroker` Windows service (LocalSystem, auto-start at boot)
- Health-check `http://127.0.0.1:8765/health`

To pass options (e.g. different install dir or port), run the script manually instead:

```powershell
# in PowerShell as Administrator
cd "$env:USERPROFILE\.claude\plugins\cache\sqlbroker-marketplace\sqlbroker\1.0.0\scripts"
.\deploy.ps1 -InstallDir 'C:\apps\mcp-sqlbroker' -Port 9000
```

### 3. Add your first connection

```
/sqlbroker:add prod_main
```

The slash command will prompt for **host, user, password (hidden), default_database, policy**. **Recommend `readonly` for production.** Password is encrypted via Windows DPAPI (LOCAL_MACHINE scope) before being written to `connections.json`.

### 4. Use it

Just ask Claude things like:

> "list_databases ของ prod_main"
> "เช็คว่ามี proc ตระกูล `_audit_` กี่ตัวใน billing_db บน prod_main"
> "select count(*) from t_orders where created_at > '2026-01-01' on staging_main"

The skill picks up the intent and routes through `mcp__plugin_sqlbroker_sqlbroker__execute_sql`.

---

## Architecture

```
Claude Code
    │
    │  stdio JSON-RPC
    ▼
run_stdio_proxy.bat → stdio_proxy.py  (pure stdlib shim)
    │
    │  HTTP POST /mcp
    ▼
mcp-sqlbroker (NSSM service, 127.0.0.1:8765)
    ├─ connections.json       (DPAPI-encrypted passwords)
    ├─ policy enforcement     (readonly | exec-only | full)
    └─ pyodbc → MSSQL
```

The chat sees **alias names only** — never hosts, users, or passwords.

---

## Verifying it works

```
/sqlbroker:status
```

Healthy output (3 lines):
```
[1] NSSM status: SERVICE_RUNNING
[2] HTTP health: {"ok":true,"server":"sqlbroker"}
[3] aliases: ...
```

Or query the broker directly:
```powershell
Invoke-WebRequest http://127.0.0.1:8765/health -UseBasicParsing | Select-Object -Expand Content
```

---

## Uninstall

```
/plugin uninstall sqlbroker
/plugin marketplace remove sqlbroker-marketplace
/reload-plugins
```

Stop and remove the Windows service (admin shell):
```powershell
D:\util\nssm.exe stop   mcp-sqlbroker
D:\util\nssm.exe remove mcp-sqlbroker confirm
Remove-Item -Recurse -Force D:\util\mcp-sqlbroker     # only if you want to wipe everything
```

The encrypted `connections.json` becomes useless once Windows DPAPI keys for that machine are gone, but if you want belt-and-suspenders, delete the file.

---

## Security notes

- The broker binds **127.0.0.1 only** — no token, no network exposure. Trust boundary = the local Windows host.
- Passwords are encrypted with DPAPI **LOCAL_MACHINE scope** — anyone with code-execution on the host can decrypt. Protect the host accordingly.
- Slash commands and the skill use an `MCP_PWD` env-var pattern when adding aliases, so passwords never enter shell history.
- For production aliases, use a SQL login with `db_datareader` only AND set the broker policy to `readonly`. Defense in depth.

---

## License

MIT — see [`LICENSE`](LICENSE).

## Author

[@creamac](https://github.com/creamac)
