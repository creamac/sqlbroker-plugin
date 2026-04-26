# sqlbroker — Claude Code & Codex CLI plugin

**Alias-based MSSQL broker for Claude Code and OpenAI Codex CLI (Windows / macOS / Linux).** A local service holds passwords encrypted with `master.key` (AES-128-CBC + HMAC) so the chat never carries credentials.

## What you get

- 🛢️ **Auto-router skill** — `sqlbroker` auto-activates on any DB-query intent ("select from X", "เช็ค proc ใน Y") on both Claude Code and Codex CLI
- ⚡ **9 commands/skills** — install, update, add, list, test, rotate, remove, status, diff. Invoked as `/sqlbroker:<name>` on Claude or `/sqlbroker-<name>` on Codex
- 🔌 **14 MCP tools** — schema introspection (list_objects, get_definition, get_table_schema, get_dependencies, find_in_definitions, find_in_columns, get_proc_params, compare_definitions), data (preview_table, execute_sql), runtime (get_server_info, get_active_queries, list_databases, list_aliases)
- 🛡️ **3 policies** — `readonly` (block all DML/DDL/EXEC), `exec-only` (SELECT + EXEC), `full` (anything)
- 🔐 **3 auth modes** — SQL login, Windows Authentication (Trusted_Connection), Azure AD service principal
- 📝 **One source of truth** — skill markdown drives both CLIs; Claude commands are 1-line shims that read the skill file

## Requirements

- **Windows** 10 / 11 / Server 2016+ — admin shell for service registration
- **macOS** 12+ — `python3` (`brew install python@3.13`), `sudo`
- **Linux** — `python3` + `python3-venv`, `sudo`, ODBC Driver 18 (Microsoft repo)

`deploy.ps1` (Windows) auto-downloads embedded Python, ODBC Driver 18, and registers a Scheduled Task. **No NSSM needed.**

## Install

**Claude Code:**

```
/plugin marketplace add creamac/sqlbroker-plugin
/plugin install sqlbroker@creamac/sqlbroker-plugin
/reload-plugins
```

**Codex CLI:**

```
codex plugin marketplace add creamac/sqlbroker-plugin
codex plugin install sqlbroker
```

Then register the local service (one-time):

```
/sqlbroker:install        # Claude
/sqlbroker-install        # Codex
```

UAC dialog (Win) or sudo prompt (Unix) → script runs unattended → patches `~/.claude.json` (and `~/.codex/config.toml` if `-Codex` / `--codex` flag set) with the MCP wiring entry.

Full quickstart with prerequisites: see the [marketplace README](../../README.md).

## Add your first connection

```
/sqlbroker:add prod_main
```

Claude collects host / user / db / policy in chat (policy via `AskUserQuestion` form). Then it prints **one command for you to run in your own terminal** — `getpass` prompts for the password there. Password never enters the chat.

## Update later

After pulling a new plugin version, refresh the deployed broker code:

```
/sqlbroker:update
```

Skips Python/ODBC reinstall — just copies `server.py` + `manage_conn.py` and bounces the service.

## Use it

Just ask normally:

> "list_databases ของ prod_main"
> "เช็คว่ามี proc ตระกูล `_audit_` กี่ตัวใน billing_db บน prod_main"
> "ดู definition ของ usp_X บน prod_main"
> "compare definition ของ usp_X ระหว่าง staging_main กับ prod_main"

The skill picks up the intent and routes to the right MCP tool.

## Architecture

```
Claude Code ──stdio JSON-RPC──▶ run_stdio_proxy.[bat|sh] → stdio_proxy.py
                                          │
                                          │  HTTP POST /mcp
                                          ▼
                              mcp-sqlbroker service (127.0.0.1:8765)
                                ├─ connections.json (host/user/db/policy/auth_mode + password_enc)
                                ├─ master.key (32 random bytes, Fernet AES)
                                ├─ connection pool (per alias+db, max 4, TTL 300s, ping + state reset)
                                ├─ policy enforcement (string-literal-aware regex)
                                └─ pyodbc → MSSQL
```

Service backend per OS: Task Scheduler (Win) / launchd (Mac) / systemd (Linux). Auto-restart on failure.

## Files

| File | Purpose |
|---|---|
| `skills/sqlbroker/SKILL.md` | Auto-activating skill — when to use which of the 14 tools |
| `commands/*.md` | 9 slash commands |
| `scripts/server.py` | HTTP MCP broker (stdlib + pyodbc + pycryptodome — no fastmcp/pydantic) |
| `scripts/manage_conn.py` | CLI: add / list / remove / test / rotate / migrate |
| `scripts/stdio_proxy.py` | stdio→HTTP shim launched by Claude Code (pure stdlib) |
| `scripts/run_stdio_proxy.bat` / `.sh` | Windows / Unix launcher for stdio_proxy.py |
| `scripts/deploy.ps1` | Windows installer (embedded Python + ODBC + Task Scheduler) |
| `scripts/deploy.sh` | Linux + macOS installer (venv + systemd / launchd) |

## Security

- Broker binds **127.0.0.1 only** — no token, no network exposure. Trust boundary = the local host.
- Passwords are AES-128-CBC + HMAC-SHA256 encrypted with `master.key`. Anyone with read access to **both** `master.key` and `connections.json` can decrypt — protect the host accordingly.
- Slash commands collect passwords via `getpass` in the user's own terminal — never via chat or `--password` CLI args.
- For production aliases, prefer a SQL login with `db_datareader` only AND broker policy `readonly`. Defense in depth.

## License

MIT
