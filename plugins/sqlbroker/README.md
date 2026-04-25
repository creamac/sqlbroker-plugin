# sqlbroker — Claude Code plugin

**Alias-based MSSQL broker for Claude Code on Windows.** A local NSSM-managed service holds DPAPI-encrypted credentials by alias, so the chat never carries passwords.

## What you get

- 🛢️ **Skill** — `sqlbroker` auto-activates on any DB-query intent ("select from X", "เช็ค proc ใน Y")
- ⚡ **Slash commands** — `/sqlbroker:install`, `/sqlbroker:add`, `/sqlbroker:list`, `/sqlbroker:test`, `/sqlbroker:remove`, `/sqlbroker:status`
- 🔌 **MCP server registration** — once the local broker is running, Claude calls `execute_sql(alias, query)` directly without ever seeing the password
- 🛡️ **Three policies** — `readonly` (block all DML/DDL/EXEC), `exec-only` (SELECT + EXEC), `full` (anything)

## Requirements

- Windows 10 / 11 / Server 2016+
- **Python 3.10+ from python.org** (Microsoft Store Python causes service-as-LocalSystem failures because the interpreter sits behind a per-user reparse point)
- ODBC Driver 17 or 18 for SQL Server
- [NSSM](https://nssm.cc/download)
- Administrator PowerShell for the one-time service install

## Install

```
/plugin marketplace add creamac/sqlbroker-plugin
/plugin install sqlbroker@creamac/sqlbroker-plugin
/reload-plugins
```

Then register the local Windows service (one-time):

```
/sqlbroker:install
```

It will print the exact `deploy.ps1` command for you to run in **PowerShell as Administrator** — paths under `~\.claude\plugins\cache\sqlbroker-marketplace\sqlbroker\<version>\scripts\`.

Full quickstart with prerequisites: see the [marketplace README](../../README.md).

## Add your first connection

```
/sqlbroker:add prod_main
```

The command will prompt for host, user, password (hidden), database, and policy. Recommend `readonly` for production.

## Use it

Just ask normally:

> "list_databases ของ prod_main"
> "เช็คว่ามี proc ตระกูล `_audit_` กี่ตัวใน billing_db บน prod_main"
> "select count(*) from t_orders where created_at > '2026-01-01' on staging_main"

The skill picks up the intent and routes through the broker.

## Architecture

```
Claude Code ──HTTP/JSON-RPC──▶ mcp-sqlbroker (NSSM service, 127.0.0.1:8765)
                                  ├─ connections.json (DPAPI-encrypted passwords)
                                  ├─ policy enforcement (readonly|full|exec-only)
                                  └─ pyodbc → MSSQL
```

## Files

| File | Purpose |
|---|---|
| `skills/sqlbroker/SKILL.md` | Auto-activating skill with full usage guide |
| `commands/*.md` | Slash commands |
| `scripts/server.py` | HTTP MCP server (stdlib + pyodbc + pywin32 only — no fastmcp/pydantic to avoid Smart App Control DLL blocks) |
| `scripts/manage_conn.py` | CLI for add / list / remove / test aliases |
| `scripts/deploy.ps1` | Portable installer |
| `scripts/install-service.ps1` | NSSM-only registration step |
| `scripts/option-b-rebuild.ps1` | Fix when venv points at Microsoft Store Python |

## Security

- Broker binds **127.0.0.1 only** — no token, no network exposure. Trust boundary = the local Windows host.
- Passwords encrypted with DPAPI **LOCAL_MACHINE scope** (any code-execution on the host can decrypt; protect the host accordingly).
- Slash commands and the skill use an `MCP_PWD` env-var pattern when adding aliases, so passwords never enter shell history.
- For production aliases, prefer a SQL login with `db_datareader` only, AND set the broker policy to `readonly`. Defense in depth.

## License

MIT
