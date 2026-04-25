---
name: sqlbroker
description: Use any time the user asks to query an MSSQL database (SELECT / EXEC / metadata / "เช็ค proc/table") or wants to add, edit, remove, or test a database connection alias on this machine. Routes through the local mcp-sqlbroker NSSM service at http://127.0.0.1:8765/mcp; covers config edits and service management. Activate on any DB-query intent, not just when the user says "use sqlbroker".
---

# MCP SQL Broker — Usage Guide

## What it is

A Windows service on this machine at `http://127.0.0.1:8765/mcp` that brokers MSSQL access using **named aliases**, so the conversation never carries credentials. Passwords are encrypted with Windows DPAPI (LOCAL_MACHINE scope) and stored in `connections.json`.

- Source / install dir: `D:\util\mcp-sqlbroker\`
- Service name (NSSM): `mcp-sqlbroker`
- Runs as: LocalSystem
- Python interpreter: `C:\Python313\python.exe` (python.org installer; the venv at `D:\util\mcp-sqlbroker\.venv` points to it)
- Config: `D:\util\mcp-sqlbroker\connections.json`
- Logs: `D:\util\mcp-sqlbroker\service.log`, `service.out.log`, `service.err.log`

## When to invoke this skill

Trigger any time the user wants to interact with an MSSQL database that is (or should be) configured as an alias on this machine. Examples:

- "query DB X", "select from Y", "ดู proc ใน DB Z", "เช็ค table ..."
- "list databases on test_itdeploy"
- "หาว่ามี usp ตระกูล _approve กี่ตัว"
- "test connection to <alias>"
- "เพิ่ม alias ใหม่", "ลบ alias", "เปลี่ยน policy เป็น readonly"

If the user references a database/server that is *not* yet an alias, ask whether to add it before doing anything else. Do not silently fall back to entering credentials in the conversation.

## MCP tools (preferred path)

When `mcpServers.sqlbroker` is wired into Claude Code, three tools are exposed:

- `mcp__sqlbroker__list_aliases` — list configured aliases (no credentials)
- `mcp__sqlbroker__list_databases(alias)` — list DBs visible to that alias's login
- `mcp__sqlbroker__execute_sql(alias, query, database?, max_rows?)` — run T-SQL; subject to the alias's policy

Use these directly; do not run `sqlcmd` / raw connection strings.

## Manual HTTP fallback (when MCP not wired)

```powershell
$body = @{
  jsonrpc = '2.0'; id = 1; method = 'tools/call'
  params = @{
    name = 'execute_sql'
    arguments = @{ alias = '<alias>'; query = 'SELECT TOP 5 name FROM sys.objects' }
  }
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/mcp `
  -ContentType 'application/json' -Body $body | ConvertTo-Json -Depth 8
```

Other JSON-RPC methods: `initialize`, `tools/list`, `tools/call` (with `name` = `list_aliases` | `list_databases` | `execute_sql`).

## Reading the config

```powershell
# Pretty list (recommended)
D:\util\mcp-sqlbroker\.venv\Scripts\python.exe D:\util\mcp-sqlbroker\manage_conn.py list

# Raw (password fields are encrypted blobs, not plaintext)
Get-Content D:\util\mcp-sqlbroker\connections.json
```

## Editing the config

The broker re-reads `connections.json` on every request — **no service restart needed** after edits.

### Add an alias (interactive, password hidden)
```powershell
D:\util\mcp-sqlbroker\.venv\Scripts\python.exe D:\util\mcp-sqlbroker\manage_conn.py add <alias>
# prompts for host, user, password, default_database, policy
```

### Add an alias programmatically without leaking the password to shell history
```powershell
$env:MCP_PWD = '<password>'
$src = @'
import os, sys
sys.path.insert(0, r"D:\util\mcp-sqlbroker")
from manage_conn import load, save
from server import encrypt_password
cfg = load()
cfg["connections"]["<alias>"] = {
    "host": r"<host>",
    "user": "<user>",
    "password_dpapi": encrypt_password(os.environ["MCP_PWD"]),
    "default_database": "<db_or_empty>",
    "policy": "readonly",
    "driver": "ODBC Driver 17 for SQL Server",
}
save(cfg)
'@
$src | & D:\util\mcp-sqlbroker\.venv\Scripts\python.exe -
$env:MCP_PWD = $null
```

### Remove an alias
```powershell
D:\util\mcp-sqlbroker\.venv\Scripts\python.exe D:\util\mcp-sqlbroker\manage_conn.py remove <alias>
```

### Test an alias
```powershell
D:\util\mcp-sqlbroker\.venv\Scripts\python.exe D:\util\mcp-sqlbroker\manage_conn.py test <alias>
```

### Edit fields directly
Edit `connections.json` and change any field EXCEPT `password_dpapi`:
- `policy` — `readonly` | `full` | `exec-only`
- `default_database`, `host`, `user`, `driver` — straightforward strings

To rotate the password, easiest is `manage_conn.py add <alias> --force` (re-prompts).

## Policies

| Policy      | Allowed                                  | Blocked                                            |
|-------------|------------------------------------------|----------------------------------------------------|
| `readonly`  | SELECT, sys queries                      | INSERT/UPDATE/DELETE/MERGE/TRUNCATE/DDL/EXEC       |
| `exec-only` | SELECT + EXEC stored procedures          | INSERT/UPDATE/DELETE/MERGE/TRUNCATE/DDL            |
| `full`      | Anything                                 | (none)                                             |

Default for new aliases: `readonly`. Use `full` only on sandbox / test boxes.

## Service management (NSSM)

Most NSSM commands need an Administrator PowerShell.

```powershell
D:\util\nssm.exe status   mcp-sqlbroker
D:\util\nssm.exe start    mcp-sqlbroker
D:\util\nssm.exe stop     mcp-sqlbroker
D:\util\nssm.exe restart  mcp-sqlbroker
D:\util\nssm.exe edit     mcp-sqlbroker        # GUI for env vars / log paths
```

Health check (no admin needed):
```powershell
Invoke-WebRequest http://127.0.0.1:8765/health -UseBasicParsing | Select-Object -Expand Content
# expect: {"ok":true,"server":"sqlbroker"}
```

## Wiring into Claude Code MCP config

Add to `~/.claude.json` or workspace MCP settings:
```json
{
  "mcpServers": {
    "sqlbroker": { "url": "http://127.0.0.1:8765/mcp" }
  }
}
```

After Claude Code restart, `mcp__sqlbroker__execute_sql` etc. become callable directly.

## Adding the broker to a new Windows host

The portable installer is `D:\util\mcp-sqlbroker\deploy.ps1`. Requires:
- Python 3.10+ from **python.org** (Microsoft Store Python causes service-as-LocalSystem failures because the interpreter lives behind a per-user reparse point)
- ODBC Driver 17 or 18 for SQL Server
- NSSM (https://nssm.cc/download)

## Troubleshooting

| Symptom | Fix |
|---|---|
| Service status `SERVICE_PAUSED` | `D:\util\nssm.exe reset mcp-sqlbroker Throttle` then `start` |
| Service won't start, no `service.err.log` written | venv probably points at Microsoft Store Python — rebuild venv from `C:\Python313\python.exe` (see `option-b-rebuild.ps1`) |
| `pyodbc.OperationalError: Invalid value specified for connection string attribute 'Encrypt' (0)` | ODBC Driver 17 doesn't accept `Encrypt=optional`; broker uses `Encrypt=no`. If TLS is required, install ODBC 18 and set the alias's `driver` field. |
| `pyodbc.OperationalError: Login failed` | Alias password is stale or wrong — re-add with `manage_conn.py add <alias> --force` |
| Smart App Control blocks `pydantic_core` on a fresh host | Don't add fastmcp / mcp-SDK / pydantic — broker is pure stdlib + pyodbc + pywin32 for exactly this reason |

## Files

| File | Purpose |
|---|---|
| `server.py` | HTTP MCP server (JSON-RPC over `POST /mcp`) |
| `manage_conn.py` | CLI: add / list / remove / test aliases |
| `connections.json` | Alias config — DPAPI-encrypted passwords |
| `requirements.txt` | `pyodbc`, `pywin32` |
| `deploy.ps1` | Portable installer for new Windows hosts |
| `install-service.ps1` | Just the NSSM service registration step (admin) |
| `option-b-rebuild.ps1` | One-shot fix when venv points at Microsoft Store Python |
| `fix-service-user.ps1` | Alternative: run service as a named user instead of LocalSystem |
