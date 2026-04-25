---
name: sqlbroker
description: Use any time the user asks to query an MSSQL database (SELECT / EXEC / metadata / "เช็ค proc/table") or wants to add, edit, remove, or test a database connection alias on this machine. Routes through the local mcp-sqlbroker service at http://127.0.0.1:8765/mcp; covers config edits and service management. Activate on any DB-query intent, not just when the user says "use sqlbroker".
---

# MCP SQL Broker — Usage Guide

## What it is

A local service at `http://127.0.0.1:8765/mcp` that brokers MSSQL access using **named aliases** so the conversation never carries credentials. Passwords are encrypted with a per-install random AES-128-CBC + HMAC key (`master.key`) and stored as `password_enc` in `connections.json`.

| | Default |
|---|---|
| Source / install dir | Windows: `D:\util\mcp-sqlbroker\` · Linux: `/opt/mcp-sqlbroker/` · macOS: `/opt/mcp-sqlbroker/` |
| Service backend | Windows: Task Scheduler (`mcp-sqlbroker`) · Linux: systemd · macOS: launchd plist |
| Runs as | LocalSystem (Win) / root (Unix) by default |
| Python interpreter | Windows: `<InstallDir>\python313\python.exe` (embedded, downloaded by deploy.ps1) · Unix: `<InstallDir>/.venv/bin/python3` |
| Config | `<InstallDir>/connections.json` (no plaintext passwords) |
| Encryption key | `<InstallDir>/master.key` (32 random bytes) |
| Logs | `<InstallDir>/service.log` (and `service.out.log` / `service.err.log` if redirected) |

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

### Tool-pick cheatsheet (resolve ambiguity)

| User says... | Pick this tool — NOT this |
|---|---|
| "show me proc X" / "ดู definition" | ✅ `get_definition` — NOT `find_in_definitions` |
| "find procs that use table X" / "หา proc ที่ใช้ ..." | ✅ `find_in_definitions` — NOT `get_definition` |
| "what columns does table X have?" | ✅ `get_table_schema` — NOT `find_in_columns` |
| "which tables have column called X?" | ✅ `find_in_columns` — NOT `get_table_schema` |
| "what does proc X read/write?" | ✅ `get_dependencies` — NOT `find_in_definitions` |
| "list procs matching ..." | ✅ `list_objects` — NOT `find_in_definitions` |
| "show me top 10 rows of X" | ✅ `preview_table` — NOT `execute_sql` |
| "what params does proc X take?" | ✅ `get_proc_params` — NOT `get_definition` |
| "is proc X same on prod and staging?" | ✅ `compare_definitions` — NOT 2× `get_definition` |
| "what version of SQL Server?" | ✅ `get_server_info` — NOT `execute_sql` |
| "what's running right now?" | ✅ `get_active_queries` — NOT `execute_sql` |

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

## Service management

Most management commands need elevation (admin PowerShell on Windows / `sudo` on Unix).

**Windows (Task Scheduler):**
```powershell
Get-ScheduledTask -TaskName mcp-sqlbroker | Format-List State,LastRunTime,LastTaskResult
Stop-ScheduledTask  -TaskName mcp-sqlbroker
Start-ScheduledTask -TaskName mcp-sqlbroker
```

**Linux (systemd):**
```bash
sudo systemctl status   mcp-sqlbroker
sudo systemctl restart  mcp-sqlbroker
sudo journalctl -u mcp-sqlbroker -n 50
```

**macOS (launchd):**
```bash
sudo launchctl unload /Library/LaunchDaemons/com.creamac.mcp-sqlbroker.plist
sudo launchctl load   /Library/LaunchDaemons/com.creamac.mcp-sqlbroker.plist
```

Health check (no admin needed, every OS):
```bash
curl -fsS http://127.0.0.1:8765/health
# expect: {"ok":true,"server":"sqlbroker"}
```

Refresh code without re-installing dependencies (use after pulling a new plugin version):
- Windows: `/sqlbroker:update` (auto-elevates) or `deploy.ps1 -RefreshOnly`
- Unix: `sudo deploy.sh --refresh-only`

## Wiring into Claude Code MCP config

`deploy.ps1` / `deploy.sh` patches `~/.claude.json` automatically (with `-AutoWire` / `--auto-wire`). The entry it writes:

```json
"mcpServers": {
  "sqlbroker": { "command": "<InstallDir>/run_stdio_proxy.[bat|sh]", "args": [] }
}
```

After a Claude Code reload, all 14 `mcp__sqlbroker__*` tools become callable.

## Adding the broker to a new host

The installer scripts auto-download / install everything needed:

**Windows** — `deploy.ps1` downloads embedded Python 3.13 + ODBC Driver 18, registers a Scheduled Task running as SYSTEM, optionally patches `~/.claude.json`. Requires admin shell. **No NSSM** — uses Task Scheduler.

**Linux / macOS** — `deploy.sh` uses your system `python3`, builds a venv, installs `pyodbc` + `pycryptodome`, registers a systemd unit (Linux) or launchd plist (macOS). Requires `sudo`. ODBC Driver 18 install hint printed if missing.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Task `Disabled` / `Ready` (Windows) | Admin: `Start-ScheduledTask -TaskName mcp-sqlbroker` |
| systemd `inactive` / `failed` | `sudo systemctl restart mcp-sqlbroker`; `journalctl -u mcp-sqlbroker -n 50` |
| Service won't start, no `service.err.log` written | Run `/sqlbroker:install` again — likely a bad embedded Python install |
| `master.key did not match (HMAC mismatch)` | Someone replaced master.key. Restore from backup or re-add aliases. |
| `No encrypted password for alias '<name>'` | Migration didn't complete or alias missing. Run `manage_conn.py migrate` (admin/sudo) or `/sqlbroker:add <alias> --force`. |
| `permission_denied: VIEW SERVER STATE` (only `get_active_queries`) | Grant `VIEW SERVER STATE` to alias's SQL login or use a privileged alias for that one tool. |
| `pyodbc.OperationalError: Login failed` | Password rotated. `/sqlbroker:rotate <alias>`. |
| Smart App Control blocks `pydantic_core` on a fresh host | v2.3+ uses `pycryptodome` (C extension) instead of `cryptography` (Rust). Confirm you're on v2.3+. |

## Files

| File | Purpose |
|---|---|
| `server.py` | HTTP MCP broker — 14 tools, connection pool, master.key encryption, Fernet AES |
| `manage_conn.py` | CLI: `add` / `list` / `remove` / `test` / `rotate` / `migrate` |
| `connections.json` | Alias config — `password_enc` (no plaintext) |
| `master.key` | 32 random bytes for Fernet encryption (one per install) |
| `requirements.txt` | `pyodbc`, `pycryptodome` |
| `stdio_proxy.py` + `run_stdio_proxy.{bat,sh}` | stdio→HTTP shim launched by Claude Code |
| `deploy.ps1` | Windows installer (Task Scheduler, no NSSM) |
| `deploy.sh` | Linux + macOS installer (systemd / launchd) |
