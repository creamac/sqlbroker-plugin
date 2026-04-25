# sqlbroker — Claude Code marketplace + plugin

> Talk to MSSQL from Claude Code by **alias name**, never by credentials.

A local broker holds your SQL Server passwords in an encrypted file
(`master.key` + AES-128-CBC + HMAC-SHA256). Claude calls databases by
alias only — host, user, and password never enter the conversation.
Cross-platform: Windows / macOS / Linux.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Version](https://img.shields.io/badge/version-2.3.1-blue)

```
You:   "list databases on prod_main"
You:   "ดู proc ที่ชื่อมี _approve ใน billing_db บน prod_main"
You:   "select count(*) from t_orders where created_at > '2026-01-01' on staging_main"
```

The skill auto-activates on any DB-query intent and routes through the broker.

---

## Why?

Without a broker, every MSSQL connection from an AI agent looks like one of these:

```jsonc
// ~/.claude.json — 😱 plaintext password in config
"mssql_prod": {
  "command": "uvx",
  "args": ["--from", "microsoft-sql-server-mcp", "mssql_mcp_server"],
  "env": { "MSSQL_PASSWORD": "Hunter2!", ... }
}
```

```python
# Or in a chat:
> "connect to 10.0.0.5 as appuser with password Hunter2! then run..."
```

Both leak credentials into config files, transcripts, and shell history.
sqlbroker stores the passwords once, encrypted, and exposes only **alias
names** through the MCP tools — `mcp__plugin_sqlbroker_sqlbroker__execute_sql(alias="prod_main", query="...")`.

---

## Compatibility

### MSSQL servers

Anything **ODBC Driver 17 or 18** can talk to. Tested:

| Server | Status |
|---|---|
| **SQL Server 2016 SP1+** | ✅ Verified (smoke + execute_sql + sys.databases) |
| SQL Server 2017 / 2019 / 2022 | ✅ Same wire protocol — should be drop-in |
| SQL Server 2014 | ✅ Works via ODBC 17 |
| SQL Server 2012 | ⚠️ Works via ODBC 17 but TLS 1.2+ may need patching |
| SQL Server 2008 / 2008 R2 | ⚠️ ODBC 17 lists support; cipher negotiation can fail — use ODBC 17 explicitly, not 18 |
| Azure SQL Database / Managed Instance | ✅ Use ODBC 18 with `Encrypt=yes` (override the default) |
| SQL Server on Linux (2017+) | ✅ Same as Windows server-side |

Auth: **SQL login** (verified). Windows Auth via ODBC `Trusted_Connection=yes` works in principle but the broker keeps a password column — for AAD/Windows-Auth setups, set the alias's `user` to a placeholder and patch `connections.json` `driver`/auth fields directly.

### Hosts running the broker

| OS | Service backend | Auto-restart |
|---|---|---|
| **Windows 10 / 11 / Server 2016+** | Windows Task Scheduler (runs as SYSTEM at boot) | RestartCount 99, 1m interval |
| **macOS 12+** | launchd (`com.creamac.mcp-sqlbroker.plist`) | `KeepAlive=true` |
| **Linux (Debian/Ubuntu/RHEL/Fedora, systemd)** | systemd unit | `Restart=on-failure`, `RestartSec=5` |

### Claude Code

Tested with the marketplace + plugin slash command flow on Claude Code Desktop. Plugin manifest version is 1.0+; works with the `/plugin install <plugin>@<owner>/<repo>` syntax.

---

## Quickstart

### 0) Prerequisites per OS

| OS | Need yourself | Auto-installed |
|---|---|---|
| **Windows** | Claude Code, admin shell access | embedded Python 3.13, ODBC Driver 18, Scheduled Task |
| **macOS** | Claude Code, `python3` (`brew install python@3.13`), `sudo` | venv + `pyodbc` + `pycryptodome`, launchd plist. ODBC: `brew install msodbcsql18` (manual) |
| **Linux** | Claude Code, `python3` + `python3-venv`, `sudo` | venv + `pyodbc` + `pycryptodome`, systemd unit. ODBC: install `msodbcsql18` from Microsoft repo (manual) |

### 1) Install the plugin

```
/plugin marketplace add creamac/sqlbroker-plugin
/plugin install sqlbroker@creamac/sqlbroker-plugin
/reload-plugins
```

### 2) Install the local service

```
/sqlbroker:install
```

Picks the right deploy script for your OS and runs it elevated. The script:

- **Windows** — downloads embedded Python + ODBC Driver 18, registers a Scheduled Task, starts it, optionally patches `~/.claude.json` with the MCP wiring entry. UAC dialog → click Yes.
- **macOS / Linux** — uses your system `python3`, builds a venv, registers a launchd plist or systemd unit. `sudo` password required.

### 3) Add your first connection

```
/sqlbroker:add prod_main
```

Claude collects host / user / db / policy in chat (policy via the `AskUserQuestion` form). Then it prints a **single command for you to run in your own terminal** — that's where `getpass` prompts for the password. Password never enters the chat or shell history.

### 4) Use it

```
"list_databases ของ prod_main"
"select count(*) from t_orders where created_at > '2026-01-01' on staging_main"
"เช็ค proc ที่มี audit ใน billing_db บน prod_main"
```

The skill picks up the intent and routes through `mcp__plugin_sqlbroker_sqlbroker__execute_sql`.

---

## Architecture

```
Claude Code
    │
    │  stdio JSON-RPC
    ▼
run_stdio_proxy.[bat|sh] → stdio_proxy.py  (pure stdlib shim)
    │
    │  HTTP POST /mcp
    ▼
mcp-sqlbroker service (127.0.0.1:8765)
    ├─ connections.json  — host/user/db/policy + password_enc (Fernet AES blob)
    ├─ master.key        — 32 random bytes generated at install
    ├─ policy enforcement — regex strips strings + comments before checking
    └─ pyodbc → MSSQL
```

The chat sees alias names only — never hosts, users, or passwords.

### Threat model

- Broker binds **127.0.0.1 only** — no token, no network exposure.
- `master.key` + `connections.json` together = the secret. Anyone with read access to **both** files (or code execution as the broker user) can decrypt.
- This is equivalent to the v1 DPAPI LOCAL_MACHINE model: **the host is the trust boundary**. Protect it accordingly.
- For hardening: file ACL `master.key` so only SYSTEM (Win) / root (Unix) + the SQL admin can read.

---

## Slash commands

| Command | Purpose |
|---|---|
| `/sqlbroker:install` | Install the local service (deploy.ps1 / deploy.sh elevated) |
| `/sqlbroker:update` | Refresh broker code after a plugin upgrade (skips Python/ODBC/NSSM) |
| `/sqlbroker:add <alias>` | Add a new alias — chat for non-secrets, terminal for password |
| `/sqlbroker:list` | List all aliases (no credentials) |
| `/sqlbroker:test <alias>` | Run a 4-column identity query against the alias |
| `/sqlbroker:rotate <alias>` | Rotate password only — host/user/policy untouched |
| `/sqlbroker:remove <alias>` | Delete alias from config |
| `/sqlbroker:status` | Service health + alias list (3-step check) |

## MCP tools (auto-routed via the skill — 14 total)

**Core:**
- `list_aliases()` — configured aliases, no credentials
- `list_databases(alias)` — DBs visible to the alias's login
- `execute_sql(alias, query, database?, max_rows?)` — run T-SQL, subject to policy

**Server / runtime (v2.6):**
- `get_server_info(alias, database?)` — version (`2008/.../2022`), edition, instance, host, collation, uptime
- `get_active_queries(alias, top_n?, database?)` — currently-running queries (sys.dm_exec_requests)

**Schema introspection (v2.5 + v2.7):**
- `list_objects(alias, name_pattern, type, database?)` — find procs/tables/views by `LIKE` pattern
- `get_definition(alias, object_name, database?)` — source CREATE statement
- `get_table_schema(alias, table_name, database?)` — columns + types + nullable + identity + PK + indexes
- `get_dependencies(alias, object_name, database?)` — both directions: uses + used_by
- `find_in_definitions(alias, search_text, type?, database?)` — full-text grep across proc/view/function bodies
- `find_in_columns(alias, search_text, database?)` — column-name search across all user tables/views *(v2.7)*
- `get_proc_params(alias, object_name, database?)` — parameter list (name, type, output, default) of a proc/function *(v2.7)*
- `compare_definitions(alias_a, alias_b, object_name, database_a?, database_b?)` — diff source code across two environments *(v2.7)*

**Data (v2.6):**
- `preview_table(alias, table_name, top_n?, database?)` — safe `SELECT TOP n *`

All tools auto-prefix `mcp__plugin_sqlbroker_sqlbroker__` when called by Claude.

## Policies

| Policy | Allowed | Blocked |
|---|---|---|
| `readonly` (default for new aliases) | SELECT, sys queries | INSERT/UPDATE/DELETE/MERGE/TRUNCATE/DDL/EXEC |
| `exec-only` | SELECT + EXEC stored procedures | INSERT/UPDATE/DELETE/MERGE/TRUNCATE/DDL |
| `full` | Anything | (none) |

The regex strips SQL string literals (`'...'`) and comments (`-- ...`, `/* ... */`) before scanning, so queries like `SELECT '/*' WHERE '*/' = 'UPDATE'` aren't false-positive blocked.

## Auth modes (v2.4+)

Each alias has an `auth_mode` field:

| `auth_mode` | What it does | When to use | Notes |
|---|---|---|---|
| `sql` (default) | Username + master.key-encrypted password | Most environments | Works on all OS |
| `windows` | `Trusted_Connection=yes` — uses the **broker process's** Windows identity | On-prem MSSQL with Windows Auth | Service must run as a Windows account that has DB access. SYSTEM (default) only works for **local** SQL Server; for cross-machine, run as a domain user via `deploy.ps1 -ServiceUser/-ServicePassword`. |
| `aad-spn` | Azure AD service principal | Azure SQL Database / Managed Instance | Requires ODBC Driver 18+. `user` = `client_id` (UUID), password = `client_secret` |

Set with `--auth-mode` flag on `manage_conn.py add`, or pick from the `AskUserQuestion` form on `/sqlbroker:add`.

---

## Migrating from v1.x or v2.0–2.2

v1 stored passwords as DPAPI blobs in `connections.json`.
v2.0–2.2 stored them in the OS keyring (which broke when the broker ran as a system service — see [PRE-MORTEM.md](#pre-mortem)).
v2.3+ uses an `master.key` file that any process can read regardless of run-context.

**Auto-migration runs on first server start after upgrade:**
- v1 (`password_dpapi`) → re-encrypted with `master.key` (Windows: needs pywin32, deploy.ps1 installs it automatically when legacy detected)
- v2.0–2.2 (no password field) → reads from OS keyring, re-encrypts with `master.key`, deletes the keyring entry

After migration, `connections.json` carries only `password_enc`. Per-alias migration is logged at INFO level.

**Manual migration:**
```
python manage_conn.py migrate
```

---

## Verifying it works

```
/sqlbroker:status
```

Or directly:

```powershell
Invoke-WebRequest http://127.0.0.1:8765/health -UseBasicParsing | Select-Object -Expand Content
```

```bash
curl -fsS http://127.0.0.1:8765/health
```

Expected: `{"ok":true,"server":"sqlbroker"}`

---

## Uninstall

```
/plugin uninstall sqlbroker
/plugin marketplace remove sqlbroker-marketplace
/reload-plugins
```

Then stop & remove the service:

**Windows (admin):**
```powershell
Stop-ScheduledTask     -TaskName mcp-sqlbroker
Unregister-ScheduledTask -TaskName mcp-sqlbroker -Confirm:$false
Remove-Item -Recurse -Force D:\util\mcp-sqlbroker        # if you also want files gone
```

**Linux:**
```bash
sudo systemctl stop mcp-sqlbroker
sudo systemctl disable mcp-sqlbroker
sudo rm /etc/systemd/system/mcp-sqlbroker.service
sudo systemctl daemon-reload
sudo rm -rf /opt/mcp-sqlbroker
```

**macOS:**
```bash
sudo launchctl unload /Library/LaunchDaemons/com.creamac.mcp-sqlbroker.plist
sudo rm /Library/LaunchDaemons/com.creamac.mcp-sqlbroker.plist
sudo rm -rf /opt/mcp-sqlbroker
```

Don't forget to remove the `mcpServers.sqlbroker` entry from `~/.claude.json` if `deploy` patched it for you.

---

## Configuration

`deploy.ps1` (Windows):

| Flag | Default | Notes |
|---|---|---|
| `-InstallDir` | `D:\util\mcp-sqlbroker` | |
| `-Port` | `8765` | |
| `-BindHost` | `127.0.0.1` | Don't expose without adding auth |
| `-ServiceName` | `mcp-sqlbroker` | Scheduled Task name |
| `-ServiceUser` / `-ServicePassword` | (empty → SYSTEM) | Run as a named user instead |
| `-SkipOdbc` | off | Skip ODBC Driver 18 auto-install |
| `-SkipService` | off | Files only, no service |
| `-AutoWire` | off | Skip the y/n prompt and write the MCP entry |
| `-SkipMcpWire` | off | Don't touch `~/.claude.json` at all |

`deploy.sh` (Linux/macOS) — env vars:

| Var | Default | Notes |
|---|---|---|
| `INSTALL_DIR` | `/opt/mcp-sqlbroker` | |
| `PORT` | `8765` | |
| `BIND_HOST` | `127.0.0.1` | |
| `SERVICE_NAME` | `mcp-sqlbroker` | |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Service won't start | Tail `<InstallDir>/service.err.log` and `service.log` |
| `master.key did not match (HMAC mismatch)` | Someone deleted/replaced master.key. If you have backup, restore. If not, re-add aliases (passwords are unrecoverable). |
| `ImportError: DLL load failed ... cryptography` | Smart App Control is blocking the cryptography Rust DLL. v2.3+ uses pycryptodome (C extension) instead — confirm you're on v2.3+. |
| Service stuck PAUSED (Windows v2.1 NSSM legacy) | One-time: `D:\util\nssm.exe reset mcp-sqlbroker Throttle && D:\util\nssm.exe start mcp-sqlbroker`. Better: re-run `/sqlbroker:install` to migrate to Scheduled Task. |
| Aliases listed but `execute_sql` says "No encrypted password" | v2.0–2.2 → v2.3 migration didn't complete (e.g. systemd daemon couldn't reach Secret Service). Run `python manage_conn.py migrate` manually, or re-add the alias. |
| ODBC connection: `SSL Provider: certificate verify failed` | Add `TrustServerCertificate=yes` in the alias's `driver` field, or install proper SQL Server certs |

---

## Files in this repo

```
sqlbroker-marketplace/
├── .claude-plugin/
│   └── marketplace.json          # marketplace manifest
├── README.md                     # ← you are here
├── LICENSE
└── plugins/sqlbroker/
    ├── .claude-plugin/
    │   └── plugin.json           # plugin manifest (v2.3.1)
    ├── README.md                 # plugin user guide
    ├── skills/sqlbroker/SKILL.md # auto-activating skill
    ├── commands/                 # 7 slash commands
    │   ├── install.md  add.md  list.md  test.md
    │   ├── rotate.md   remove.md  status.md
    └── scripts/
        ├── server.py             # HTTP MCP broker
        ├── manage_conn.py        # CLI: add/list/remove/test/rotate/migrate
        ├── stdio_proxy.py        # stdio→HTTP shim (pure stdlib)
        ├── run_stdio_proxy.bat   # Windows launcher
        ├── run_stdio_proxy.sh    # Unix launcher
        ├── deploy.ps1            # Windows installer (Task Scheduler)
        └── deploy.sh             # Linux + macOS installer
```

---

## License

MIT — see [`LICENSE`](LICENSE).

## Author

Built by **Cream — Pumipat** ([@creamac](https://github.com/creamac))

## Roadmap

| Version | Status | Theme |
|---|---|---|
| v2.3.1 | ✅ shipped | master.key encryption, Task Scheduler / launchd / systemd, rotate command |
| v2.4.0 | ✅ shipped | Windows Authentication + Azure AD service principal (`auth_mode` field) |
| v2.5.0 | ✅ shipped | Schema introspection (4 tools) + connection pool + `/sqlbroker:update` |
| **v2.6.0** | ✅ shipped | **+4 tools**: `get_server_info` (version detection), `find_in_definitions` (full-text grep), `preview_table` (safe SELECT TOP n), `get_active_queries` (running queries DMV) |
| v2.7 | idea | Azure AD interactive auth (device code flow) |
| v2.8 | idea | Per-alias query timeout + concurrency limit |
| v2.9 | idea | `compare_definitions(alias_a, alias_b, object_name)` — schema diff |
| v3.0 | idea | Optional auth token between Claude and the broker (for multi-user / shared hosts) |

Open issues / PRs welcome at https://github.com/creamac/sqlbroker-plugin/issues

## Pre-mortem

The architecture went through one major rewrite (v2.0 keyring → v2.3 file-encrypted) after a pre-mortem identified that running a service as SYSTEM/root meant the daemon couldn't read passwords stored in the **user's** OS keyring. v2.3's `master.key` file approach removes the run-context dependency. See commit `732c6e9` for the full rationale.
