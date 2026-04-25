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

Trigger any time the user wants to interact with an MSSQL database that is (or should be) configured as an alias on this machine. Examples by intent:

- **Browse/discover** — "query DB X", "select from Y", "list databases on prod_main", "หาว่ามี usp ตระกูล _approve กี่ตัว", "เช็ค table"
- **Inspect a proc/view** — "ดู definition ของ usp_foo", "what does proc bar do?"
- **Inspect a table** — "schema ของ t_orders", "what columns does X have?", "indexes on table Y"
- **Trace dependencies** — "what tables does proc X read?", "ใครเรียก usp_foo บ้าง"
- **Connections** — "test alias", "เพิ่ม alias ใหม่", "ลบ alias", "rotate password", "เปลี่ยน policy"

If the user references a database/server that is *not* yet an alias, ask whether to add it before doing anything else. Do not silently fall back to entering credentials in the conversation.

## Tool selection (prefer the most specific tool)

When the broker is wired into Claude Code (via `mcpServers.sqlbroker`), 14 MCP tools are exposed. **Pick the most specific one — don't fall back to `execute_sql` if a dedicated tool fits.**

**Connection / metadata:**
- `list_aliases()` — configured aliases (no credentials)
- `list_databases(alias)` — DBs visible to the alias's login
- `get_server_info(alias, database?)` — version (`2008/2012/2014/2016/2017/2019/2022`), edition, instance, host, collation, uptime. **Run this first** when you need to pick version-compatible queries (e.g. STRING_AGG only on 2017+).

**Schema introspection (preferred over hand-written `sys.*` queries):**
- `list_objects(alias, name_pattern, type, database?)` — find procs/tables/views/functions/triggers by `LIKE` pattern. **Use this** when the user says "find procs matching ...", "ลิสต์ทุก table ที่ ...", "หา view ที่ ..."
- `get_definition(alias, object_name, database?)` — source CREATE statement. **Use this** when user asks "show me proc X", "ดู definition", "what does X do?"
- `get_table_schema(alias, table_name, database?)` — columns + types + nullable + identity + PK + non-PK indexes in one call. **Use this** when user asks "what columns does X have?", "schema ของ ...", "indexes on ..."
- `get_dependencies(alias, object_name, database?)` — both directions: what an object uses + what uses it. **Use this** when user asks "what does proc X read/write?", "ใครเรียก usp_foo", "trace dependencies"
- `find_in_definitions(alias, search_text, type?, database?)` — full-text grep across all proc/view/function/trigger bodies. **Use this** when user asks "find all procs that touch table X", "which views reference column Y", "หา proc ที่มีคำว่า ..."
- `find_in_columns(alias, search_text, database?)` — column-name search across all user tables/views. **Use this** for "which tables have a column called email_to?", "หาทุก table ที่มี column ชื่อ status"
- `get_proc_params(alias, object_name, database?)` — parameter list (name, type, output flag, default) of a proc or function. **Use this** before calling a proc via execute_sql so you know how to bind args.
- `compare_definitions(alias_a, alias_b, object_name, database_a?, database_b?)` — diff the source code of an object across two aliases (or two databases on the same alias). **Use this** for "is proc X the same on prod and staging?", "what changed in usp_foo between dev and uat?"

**Data / runtime:**
- `preview_table(alias, table_name, top_n=10, database?)` — safe `SELECT TOP n *` from a table/view. **Use this** for quick peeks; do NOT hand-craft `SELECT TOP n *` via execute_sql — preview_table validates the object exists first and bracket-escapes the name.
- `get_active_queries(alias, top_n=50, database?)` — currently-running queries (sys.dm_exec_requests). **Use this** when debugging "what's slow right now?", "ใครยึด lock", blocking analysis.

**Catch-all:**
- `execute_sql(alias, query, database?, max_rows?)` — run T-SQL; subject to the alias's `readonly | exec-only | full` policy. Only use when no specific tool fits (custom joins across catalog views, multi-result-set procs, etc.)

Tools are auto-prefixed `mcp__plugin_sqlbroker_sqlbroker__` when called.

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
