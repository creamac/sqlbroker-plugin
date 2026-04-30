# sqlbroker — Claude Code & Codex CLI marketplace + plugin

> Talk to MSSQL from Claude Code or OpenAI Codex CLI by **alias name**, never by credentials.

A local broker holds your SQL Server passwords in an encrypted file
(`master.key` + AES-128-CBC + HMAC-SHA256). Your AI agent calls databases
by alias only — host, user, and password never enter the conversation.
Cross-platform: Windows / macOS / Linux. **One repo, two manifests** —
the same plugin works for Claude Code (`/plugin marketplace add ...`) and
Codex CLI (`codex plugin marketplace add ...`).

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Version](https://img.shields.io/badge/version-2.7.1-blue)
![Tools](https://img.shields.io/badge/MCP_tools-14-green)
![Auth](https://img.shields.io/badge/auth-SQL_%7C_Windows_%7C_AAD--SPN-orange)
![Hosts](https://img.shields.io/badge/hosts-Claude_Code_%7C_Codex_CLI-purple)

```
You:   "list databases on prod_main"
You:   "ดู proc ที่ชื่อมี _approve ใน billing_db บน prod_main"
You:   "select count(*) from t_orders where created_at > '2026-01-01' on staging_main"
```

The skill auto-activates on any DB-query intent and routes through the broker.

---

## Quickstart

> 5 minutes from zero to your first SQL query.

### 0) Prerequisites per OS

| OS | Need yourself | Auto-installed by `deploy` |
|---|---|---|
| **Windows** | Claude Code or Codex CLI 0.124+, admin shell access | embedded Python 3.13, ODBC Driver 18, Scheduled Task |
| **macOS** | Claude Code or Codex CLI 0.124+, `python3` (`brew install python@3.13`), `sudo` | venv + `pyodbc` + `pycryptodome`, launchd plist. ODBC: `brew install msodbcsql18` (manual) |
| **Linux** | Claude Code or Codex CLI 0.124+, `python3` + `python3-venv`, `sudo` | venv + `pyodbc` + `pycryptodome`, systemd unit. ODBC: install `msodbcsql18` from Microsoft repo (manual) |

You can install on either CLI alone, or **both** — pass `-Codex` (Windows) / `--codex` (Unix) to the deploy script and it will wire `~/.claude.json` AND `~/.codex/config.toml` in one run.

### 1) Install the plugin (every OS)

**Claude Code:**

```
/plugin marketplace add creamac/sqlbroker-plugin
/plugin install sqlbroker@creamac/sqlbroker-plugin
/reload-plugins
```

**Codex CLI (0.124+):**

```
codex plugin marketplace add creamac/sqlbroker-plugin
```

The marketplace declares `installation: INSTALLED_BY_DEFAULT`, so the plugin is auto-enabled on the next Codex session start. To verify, launch `codex` and type `/plugins` — `sqlbroker` should appear with a green dot. (If you cloned the repo locally, pass the absolute path instead of the GitHub shorthand.)

Both CLIs read the same broker source under `plugins/sqlbroker/`. The manifests live in two different places per platform convention:

| Host | Marketplace manifest | Plugin manifest |
|---|---|---|
| Claude Code | `.claude-plugin/marketplace.json` | `plugins/sqlbroker/.claude-plugin/plugin.json` |
| Codex CLI | `.agents/plugins/marketplace.json` (per OpenAI convention) | `plugins/sqlbroker/.codex-plugin/plugin.json` |

### 2) Install the local service

> **Required step on first install.** Don't skip this — Quickstart Step 3 below assumes the broker process is up and `manage_conn.py` is deployed under `D:\util\mcp-sqlbroker\` (Windows) / `/opt/mcp-sqlbroker/` (Unix). If you try to run `manage_conn.py` before this step, you'll get `ModuleNotFoundError: No module named 'server'`.

**Claude Code (recommended):** type
```
/sqlbroker:install
```
(UAC prompts on Windows / sudo prompts on Unix when the broker isn't running yet). The skill auto-checks `curl http://127.0.0.1:8765/health` first — **if the broker is already running** (e.g. you installed via the other CLI on this same host), it skips the elevated deploy and just wires the missing MCP config. **If not running**, it pops an `AskUserQuestion` for the install location (laptops with no D: drive can pick `%USERPROFILE%\mcp-sqlbroker` or `C:\opt\mcp-sqlbroker`), then elevates and runs the OS-appropriate deploy script.

**Codex CLI:** Codex does **not** expose plugin skills as slash commands — `/sqlbroker-install` returns "Unrecognized command". Instead, ask the agent in plain language: `"install sqlbroker"` or `"set up sqlbroker on this machine"`. The Codex agent will pick up the `sqlbroker-install` skill and follow it. Since Codex sandboxes typically can't elevate themselves, the agent will print the manual elevation command for you to run in your own terminal, then call `codex mcp add` from inside the sandbox once the broker is up.

| OS | What deploy installs | Default install dir |
|---|---|---|
| Windows | embedded Python 3.13, ODBC Driver 18, Scheduled Task `mcp-sqlbroker`, Claude/Codex MCP wiring | `D:\util\mcp-sqlbroker` |
| macOS / Linux | venv + `pyodbc` + `pycryptodome`, launchd plist / systemd unit, MCP wiring | `/opt/mcp-sqlbroker` |

**Custom install location:** the install dir is fully configurable. The skill will ask you on first install. To override manually, pass `-InstallDir 'C:\path\to\anywhere'` to `deploy.ps1` or `INSTALL_DIR=/path/to/anywhere sudo ./deploy.sh`. Once installed, the broker exposes the chosen path on `/health` so future skill invocations (update, status, fast-path Codex wiring) auto-detect it without hardcoding.

The deploy script supports flags `-AutoWire` / `--auto-wire` to skip the y/n prompt and `-Codex` / `--codex` to also patch `~/.codex/config.toml` in the same run.

**If the broker is already up and you only need Codex wired**, the simplest one-liner (run in your own terminal — no admin needed):

```bash
codex mcp add sqlbroker -- D:\util\mcp-sqlbroker\run_stdio_proxy.bat   # Windows
codex mcp add sqlbroker -- /opt/mcp-sqlbroker/run_stdio_proxy.sh       # Linux/macOS
```

Codex's own CLI rewrites `~/.codex/config.toml`. Verify with `codex mcp list`.

### 3) Add your first connection

**Claude Code:** type `/sqlbroker:add prod_main`
**Codex CLI:** ask the agent `"add a sqlbroker alias called prod_main"` (no slash command — Codex skills are AI-invoked from natural language)

Either way, the agent collects host / user / db / policy in chat (policy via an `AskUserQuestion`-style form on Claude, or interactive prompt on Codex). Then it prints **one command for you to run in your own terminal** — `getpass` prompts for the password there. Password never enters the chat or shell history.

### 4) Use it

Just ask the agent things like:

```
"list_databases ของ prod_main"
"select count(*) from t_orders where created_at > '2026-01-01' on staging_main"
"เช็ค proc ที่มี audit ใน billing_db บน prod_main"
"ดู definition ของ usp_FsData_Approve_Workflow บน prod_main"
"compare definition ของ usp_X ระหว่าง staging_main กับ prod_main"
```

The auto-router skill (`sqlbroker`) picks up the intent on either CLI and dispatches to the right one of the 14 MCP tools — no need to remember tool names.

---

## Why?

### Problem 1 — credentials leak everywhere

Without a broker, every MSSQL connection from an AI agent looks like one of these:

```jsonc
// ~/.claude.json — 😱 plaintext password in config
"mssql_prod": {
  "command": "uvx",
  "args": ["--from", "microsoft-sql-server-mcp", "mssql_mcp_server"],
  "env": { "MSSQL_PASSWORD": "Hunter2!", ... }
}
```

```toml
# ~/.codex/config.toml — same problem, different syntax
[mcp_servers.mssql]
command = "cmd"
args = ["/c", "npx.cmd", "-y", "mssql-mcp@2.3.2"]

[mcp_servers.mssql.env]
DB_PASSWORD = "Hunter2!"   # 😱 plaintext, world-readable on most setups
DB_SERVER = "10.0.0.5,1433"
DB_USER = "appuser"
```

```python
# Or in a chat:
> "connect to 10.0.0.5 as appuser with password Hunter2! then run..."
```

All three leak credentials into config files, transcripts, and shell history.
sqlbroker stores the passwords once, encrypted (master.key + Fernet), and exposes only **alias names** through MCP — `execute_sql(alias="prod_main", query="...")`.

### Problem 2 — one MCP server per database eats tokens & config

Without a broker, every database needs its own MCP server entry:

```jsonc
// ~/.claude.json — 5 DBs = 5 MCP servers
"mssql_prod":      { "command": "uvx", "args": [...], "env": { ... } },
"mssql_staging":   { "command": "uvx", "args": [...], "env": { ... } },
"mssql_uat":       { "command": "uvx", "args": [...], "env": { ... } },
"mssql_dev":       { "command": "uvx", "args": [...], "env": { ... } },
"mssql_reporting": { "command": "uvx", "args": [...], "env": { ... } },
```

Cost:
- Each MCP server's tool list is loaded into Claude context **every session**
- 5 servers × ~5 tools = ~25 tool descriptions in your context every turn
- 5 separate processes spawned by Claude Code on session start
- 5 places to rotate passwords when one changes
- Every new DB = edit `.claude.json`, restart Claude Code

With sqlbroker — **one MCP server, unlimited aliases**:

```jsonc
// ~/.claude.json — one entry, forever
"sqlbroker": { "command": "...\\run_stdio_proxy.bat" }
```

```bash
# Add as many DBs as you want — no MCP changes, no restart
/sqlbroker:add prod_main
/sqlbroker:add staging_main
/sqlbroker:add uat_main
/sqlbroker:add dev_main
/sqlbroker:add reporting
# ...
```

What you save:
- 🪙 **~225 tokens/session** (broker's 14 tool descriptions vs. N×5 from spawning N MCP servers)
- 🚀 **One process** (broker is shared by all aliases) instead of N
- 🔁 **No Claude Code restart** when adding a DB (broker re-reads `connections.json` per request)
- 🛡️ **One password rotation flow** (`/sqlbroker:rotate <alias>`) for any DB
- 🧠 **Shared connection pool** — repeat queries on the same alias reuse warm connections (~50ms saved per call after warm-up)

Add a 6th, 60th, or 600th DB and the token cost stays the same.

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

Auth (v2.4+): **SQL login** (verified, default), **Windows Authentication** (`Trusted_Connection=yes`), **Azure AD service principal** (ODBC 18 + `Authentication=ActiveDirectoryServicePrincipal`). Pick via the `auth_mode` field per-alias — see [Auth modes](#auth-modes-v24).

### Hosts running the broker

| OS | Service backend | Auto-restart |
|---|---|---|
| **Windows 10 / 11 / Server 2016+** | Windows Task Scheduler (runs as SYSTEM at boot) | RestartCount 99, 1m interval |
| **macOS 12+** | launchd (`com.creamac.mcp-sqlbroker.plist`) | `KeepAlive=true` |
| **Linux (Debian/Ubuntu/RHEL/Fedora, systemd)** | systemd unit | `Restart=on-failure`, `RestartSec=5` |

### Claude Code & Codex CLI

| Host | Plugin manifest | MCP wiring |
|---|---|---|
| **Claude Code Desktop / CLI** | `.claude-plugin/marketplace.json` + `plugins/sqlbroker/.claude-plugin/plugin.json` | `~/.claude.json` `mcpServers.sqlbroker` (JSON) |
| **Codex CLI 0.124+** | `.agents/plugins/marketplace.json` + `plugins/sqlbroker/.codex-plugin/plugin.json` | `~/.codex/config.toml` `[mcp_servers.sqlbroker]` (TOML) |

Same broker process, same MCP tool surface — only the wiring format differs. The `-Codex` / `--codex` flag on the deploy script handles both formats in one run. Claude exposes 9 slash commands as `/sqlbroker:<name>`; Codex exposes 9 skills as `/sqlbroker-<name>`. Skill files at `skills/sqlbroker-*/SKILL.md` (used by Codex) and command files at `commands/*.md` (used by Claude) carry the same content; both files include a maintenance note pointing at each other so a single edit keeps them in sync.

---

## Architecture

```
Claude Code  ┐
             │ stdio JSON-RPC
Codex CLI    ┘
             ▼
run_stdio_proxy.[bat|sh] → stdio_proxy.py  (pure stdlib shim, no deps)
             │
             │ HTTP POST /mcp
             ▼
mcp-sqlbroker service (127.0.0.1:8765)
    ├─ connections.json  — host/user/db/policy/auth_mode + password_enc (Fernet AES blob)
    ├─ master.key        — 32 random bytes generated at install
    ├─ policy enforcement — regex strips strings + comments before checking
    ├─ connection pool   — per (alias, db) Queue, max 4, TTL 300s, ping + reset state on checkout
    └─ pyodbc → MSSQL (auth: SQL login | Windows | AAD-SPN)
```

The chat sees alias names only — never hosts, users, or passwords. Both CLIs spawn the **same** `stdio_proxy.py` process, which talks to the **one** broker service. No per-CLI processes; no duplicated connections.

### How dual-platform works (one repo, two manifests)

```
sqlbroker-plugin/                           # the repo
├── .claude-plugin/marketplace.json         # Claude reads this
├── .agents/plugins/marketplace.json        # Codex reads this (OpenAI convention)
└── plugins/sqlbroker/
    ├── .claude-plugin/plugin.json          # Claude plugin manifest
    ├── .codex-plugin/plugin.json           # Codex plugin manifest (different schema — interface{}, etc.)
    ├── skills/                             # 1 router + 9 ops skills (read by Codex; mirror of commands/)
    │   ├── sqlbroker/SKILL.md              # auto-activator on both CLIs
    │   └── sqlbroker-{install,add,...}/SKILL.md
    ├── commands/                           # Claude slash commands (mirror of skills/sqlbroker-*/)
    └── scripts/                            # broker source (shared, deployed by either CLI)
```

- **Claude Code**: `commands/install.md` carries the full instructions. Slash invocation: `/sqlbroker:install`. Claude does NOT substitute `${CLAUDE_PLUGIN_ROOT}` in command bodies, so the content has to live inline.
- **Codex CLI**: `skills/sqlbroker-install/SKILL.md` carries the same content. Slash invocation: `/sqlbroker-install`. Codex auto-loads skills declared by the plugin manifest's `skills: "./skills/"` field.
- **Maintenance contract:** each command file references its skill twin in a `Maintenance note:` line, and vice versa. When you edit one, edit the other in the same commit.

### Threat model

- Broker binds **127.0.0.1 only** — no token, no network exposure.
- `master.key` + `connections.json` together = the secret. Anyone with read access to **both** files (or code execution as the broker user) can decrypt.
- This is equivalent to the v1 DPAPI LOCAL_MACHINE model: **the host is the trust boundary**. Protect it accordingly.
- For hardening: file ACL `master.key` so only SYSTEM (Win) / root (Unix) + the SQL admin can read.

---

## How to invoke ops on each CLI

The plugin ships 9 ops + 1 auto-router skill. Invocation differs per CLI:

| Op | Claude Code (slash) | Codex CLI (natural language to the agent) |
|---|---|---|
| Install service | `/sqlbroker:install` | `"install sqlbroker"` |
| Refresh broker code | `/sqlbroker:update` | `"update sqlbroker to latest"` |
| Add alias | `/sqlbroker:add <alias>` | `"add a sqlbroker alias called <alias>"` |
| List aliases | `/sqlbroker:list` | `"list sqlbroker aliases"` |
| Test alias | `/sqlbroker:test <alias>` | `"test sqlbroker alias <alias>"` |
| Rotate password | `/sqlbroker:rotate <alias>` | `"rotate password for sqlbroker alias <alias>"` |
| Remove alias | `/sqlbroker:remove <alias>` | `"remove sqlbroker alias <alias>"` |
| Service health | `/sqlbroker:status` | `"check sqlbroker status"` |
| Diff object | `/sqlbroker:diff <a> <b> <obj>` | `"diff <obj> between sqlbroker aliases <a> and <b>"` |

**Why the difference?** Claude Code's plugin system maps `commands/*.md` directly to slash commands. **Codex CLI does NOT** — its slash commands are reserved for built-ins (`/plugins`, `/model`, `/help`, …) and skills are auto-loaded into the agent's context, invoked by the model when the user expresses intent in natural language. Both routes ultimately load the same skill file (`plugins/sqlbroker/skills/sqlbroker-<name>/SKILL.md`) and run the same MCP tools.

Once the broker MCP server is wired (`mcp_servers.sqlbroker` in `~/.codex/config.toml`), you can also ask in MCP-tool style: `"list databases on prod_main"` → the agent calls `mcp__sqlbroker__list_databases(alias="prod_main")` directly, bypassing the skill layer.

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

All tools auto-prefix `mcp__plugin_sqlbroker_sqlbroker__` when called by Claude Code (and an equivalent prefix on Codex). The auto-router skill picks the most specific tool — only fall back to `execute_sql` for custom joins across catalog views, multi-result-set procs, etc.

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

## Updating to a new plugin version

**Claude Code** (one shot):

```
/sqlbroker:update
```

**Codex CLI** (two steps because Codex's plugin manager and the broker service are separate concerns):

```bash
# 1. Pull the latest plugin source from GitHub into Codex's cache
codex plugin marketplace upgrade sqlbroker-marketplace

# If the upgrade fails with "Access is denied" (a known Codex 0.125 quirk on
# Windows when the cache has open file handles), use the clean re-add path:
codex plugin marketplace remove sqlbroker-marketplace
rm -rf ~/.codex/.tmp/marketplaces/sqlbroker-marketplace          # Unix
Remove-Item -Recurse -Force "$env:USERPROFILE\.codex\.tmp\marketplaces\sqlbroker-marketplace"  # Windows
codex plugin marketplace add creamac/sqlbroker-plugin
```

```bash
# 2. Refresh the deployed broker code. Two options:

# (a) Ask the Codex agent — it'll invoke the sqlbroker-update skill
#     and print the elevation command for you:
#       > "update sqlbroker broker to latest"

# (b) Run deploy.ps1 -RefreshOnly directly (faster, no AI roundtrip):
$deploy = "$env:USERPROFILE\.codex\plugins\cache\sqlbroker-marketplace\sqlbroker\<version>\scripts\deploy.ps1"
Start-Process powershell -Verb RunAs -ArgumentList @('-NoProfile','-File',$deploy,'-RefreshOnly','-AutoWire')
```

Step 2 needs admin (UAC on Windows / sudo on Unix) because the broker service has to be bounced. `connections.json` and `master.key` are NEVER touched by `-RefreshOnly`.

## Verifying it works

**Claude Code:** `/sqlbroker:status`
**Codex CLI:** ask `"check sqlbroker status"`

Or directly (works regardless of which CLI is wired):

```powershell
Invoke-WebRequest http://127.0.0.1:8765/health -UseBasicParsing | Select-Object -Expand Content
```

```bash
curl -fsS http://127.0.0.1:8765/health
```

Expected: `{"ok":true,"server":"sqlbroker"}`

To confirm the MCP wiring on each CLI:

```bash
# Claude Code — check ~/.claude.json
python -c "import json; print(json.load(open(r'C:\Users\you\.claude.json')).get('mcpServers',{}).get('sqlbroker'))"

# Codex CLI — built-in inspector
codex mcp list
codex mcp get sqlbroker
```

---

## Uninstall

**Claude Code:**

```
/plugin uninstall sqlbroker
/plugin marketplace remove sqlbroker-marketplace
/reload-plugins
```

**Codex CLI:**

```
codex plugin marketplace remove sqlbroker-marketplace
codex mcp remove sqlbroker
```

(Both `codex plugin marketplace remove` and `codex mcp remove` exist as CLI subcommands. There is no `codex plugin install/uninstall` — install is automatic via `installation: INSTALLED_BY_DEFAULT` in the marketplace manifest, or interactive via `/plugins` inside a Codex session.)

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

Don't forget to remove the `mcpServers.sqlbroker` entry from `~/.claude.json` (Claude Code) and/or `[mcp_servers.sqlbroker]` from `~/.codex/config.toml` (Codex) if `deploy` patched them for you. The deploy script saves a `.bak.YYYYMMDDHHMMSS` next to each before patching, so you can also restore that backup.

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
| `-AutoWire` | off | Skip the y/n prompt and write the MCP entry to `~/.claude.json` |
| `-SkipMcpWire` | off | Don't touch `~/.claude.json` (or `~/.codex/config.toml`) at all |
| `-RefreshOnly` | off | Just copy files + bounce Scheduled Task (skip Python/ODBC) — used by `/sqlbroker:update`. **Skips MCP wiring** — combine with re-running without `-RefreshOnly` if you want wiring updated. |
| `-Codex` | off | Also wire `~/.codex/config.toml` `[mcp_servers.sqlbroker]`. Tries `codex mcp add sqlbroker -- <wrapper>` first; falls back to direct TOML patch via embedded Python + `tomli_w` if the Codex CLI isn't on PATH (common when running elevated and Codex was installed per-user via npm). |

`deploy.sh` (Linux/macOS) — env vars + flags:

| Var | Default | Notes |
|---|---|---|
| `INSTALL_DIR` | `/opt/mcp-sqlbroker` | |
| `PORT` | `8765` | |
| `BIND_HOST` | `127.0.0.1` | |
| `SERVICE_NAME` | `mcp-sqlbroker` | |

| Flag | Notes |
|---|---|
| `--auto-wire` | Skip the y/n prompt and write the MCP entry to `$SUDO_USER`'s `~/.claude.json` |
| `--skip-mcp-wire` | Don't touch `~/.claude.json` (or `~/.codex/config.toml`) |
| `--refresh-only` | Bounce systemd unit / launchd plist after copying files (skip venv/deps). **Skips MCP wiring**. |
| `--codex` | Also wire `~/.codex/config.toml` — same fallback chain as Windows (`codex mcp add` first, direct TOML patch second). |

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
| **Codex** — `codex mcp list` doesn't show `sqlbroker` after `-Codex` deploy | Either: (a) the deploy ran elevated and your codex CLI is per-user (npm) → fallback TOML patch should have run, check for backup file `~/.codex/config.toml.bak.*`; (b) `tomli_w` install failed inside the broker venv. Re-run deploy without elevation, or manually `codex mcp add sqlbroker -- D:\util\mcp-sqlbroker\run_stdio_proxy.bat`. |
| **Codex** — `codex plugin marketplace add` succeeds but skills don't load | Restart Codex; local marketplaces are picked up at session start. If still missing, check `codex features list \| grep plugins` returns `stable true`. |
| **Codex** — `[mcp_servers.sqlbroker]` exists but Codex says "tool not found" | The wrapper path may be wrong. Run `codex mcp get sqlbroker` to see what's stored, then verify the path resolves and `python` exists at the embedded location (`D:\util\mcp-sqlbroker\python313\python.exe` on Windows). |

---

## Files in this repo

```
sqlbroker-plugin/
├── .claude-plugin/
│   └── marketplace.json          # Claude Code marketplace manifest
├── .agents/
│   └── plugins/
│       └── marketplace.json      # Codex CLI marketplace manifest (OpenAI convention)
├── .gitattributes                # enforces LF for .sh/.py, CRLF for .ps1/.bat — required for cross-OS install
├── README.md                     # ← you are here
├── CLAUDE.md                     # AI agent guidance for working in this repo
├── LICENSE
└── plugins/sqlbroker/
    ├── .claude-plugin/
    │   └── plugin.json           # Claude plugin manifest (v2.7.1)
    ├── .codex-plugin/
    │   └── plugin.json           # Codex plugin manifest (v2.7.1, with interface{})
    ├── README.md                 # plugin user guide
    ├── skills/                   # Codex skill folder (auto-loaded by Codex)
    │   ├── sqlbroker/SKILL.md            # auto-activating router skill (tool-pick cheatsheet)
    │   ├── sqlbroker-install/SKILL.md    # install service
    │   ├── sqlbroker-update/SKILL.md     # refresh broker code
    │   ├── sqlbroker-add/SKILL.md        # add alias (interactive)
    │   ├── sqlbroker-list/SKILL.md       # list aliases
    │   ├── sqlbroker-test/SKILL.md       # test alias
    │   ├── sqlbroker-rotate/SKILL.md     # rotate password
    │   ├── sqlbroker-remove/SKILL.md     # remove alias
    │   ├── sqlbroker-status/SKILL.md     # service health
    │   └── sqlbroker-diff/SKILL.md       # compare proc across envs
    ├── commands/                 # Claude slash commands — mirror skills/sqlbroker-*/SKILL.md content (with cross-ref note)
    │   ├── install.md  update.md  add.md  list.md  test.md
    │   ├── rotate.md   remove.md  status.md  diff.md
    └── scripts/
        ├── server.py             # HTTP MCP broker (14 tools, pool, master.key)
        ├── manage_conn.py        # CLI: add/list/remove/test/rotate/migrate
        ├── stdio_proxy.py        # stdio→HTTP shim (pure stdlib)
        ├── run_stdio_proxy.bat   # Windows launcher
        ├── run_stdio_proxy.sh    # Unix launcher
        ├── deploy.ps1            # Windows installer (Task Scheduler) — `-Codex` flag wires Codex too
        └── deploy.sh             # Linux + macOS installer       — `--codex` flag wires Codex too
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
| v2.6.0 | ✅ shipped | +4 tools: `get_server_info`, `find_in_definitions`, `preview_table`, `get_active_queries` |
| v2.7.0 | ✅ shipped | +3 tools: `compare_definitions`, `find_in_columns`, `get_proc_params` + `/sqlbroker:diff` slash command |
| v2.7.1 | ✅ shipped | **Pre-mortem hotfix**: pool resets session state on checkout, friendly DMV permission errors, `deploy.sh --auto-wire`, `-RefreshOnly` preflight check, tool descriptions trimmed ~50% (verbose guidance moved to skill) |
| **v2.8.0** | ✅ shipped | **Codex CLI support**: dual-marketplace (`.codex-plugin/`), 9 first-class Codex skills + auto-router, deploy `-Codex`/`--codex` flag (codex CLI primary, TOML patch fallback via `tomli_w`), commands restructured as 1-line shims pointing at single-source skill files |
| v2.9 | idea | Azure AD interactive auth (device code flow) |
| v3.0 | idea | Per-alias query timeout + concurrency limit |
| v3.1 | idea | Optional auth token between AI client and the broker (for multi-user / shared hosts) |

Open issues / PRs welcome at https://github.com/creamac/sqlbroker-plugin/issues

## Pre-mortem

### v2.3 — keyring → master.key file

The architecture went through one major rewrite (v2.0 keyring → v2.3 file-encrypted) after a pre-mortem identified that running a service as SYSTEM/root meant the daemon couldn't read passwords stored in the **user's** OS keyring. v2.3's `master.key` file approach removes the run-context dependency. See commit `732c6e9` for the full rationale.

### v2.8 — bugs caught before merge by pre-mortem + smoke test

A formal pre-mortem identified five candidate failure modes; smoke-testing on Codex CLI 0.124 confirmed three were real bugs and surfaced two more. All five are now fixed; what follows is the audit trail so future contributors know what NOT to redo.

| # | Predicted failure | Confirmed? | Fix |
|---|---|---|---|
| 1 | `${CLAUDE_PLUGIN_ROOT}` doesn't substitute in command bodies; 1-line shim model breaks all 9 Claude slash commands | ✅ confirmed (claude-code-guide research + empirical `env` check) | Reverted commands to inline content with a `Maintenance note:` cross-reference to the skill twin |
| 2 | Codex marketplace at `.codex-plugin/marketplace.json` (Claude convention) — Codex actually expects `.agents/plugins/marketplace.json` | ✅ confirmed (silent ignore — `codex plugin marketplace add` succeeded without loading any plugins) | Moved manifest to `.agents/plugins/marketplace.json`; Codex now reads + validates it |
| 3 | `authentication: NONE` invalid value | ✅ confirmed (Codex rejected: `expected ON_INSTALL or ON_USE`) | Changed to `ON_INSTALL` |
| 4 | `installation: AVAILABLE` requires interactive `/plugins` install — README's `codex plugin install <name>` command doesn't exist | ✅ confirmed (CLI returned `unrecognized subcommand`) | Changed to `INSTALLED_BY_DEFAULT` (auto-installs); README rewritten to remove fake CLI command |
| 5 | CRLF line endings corrupt `deploy.sh` on Linux/macOS first install | ✅ confirmed (git status warning) | Added `.gitattributes` enforcing `*.sh text eol=lf`, `*.py text eol=lf`, `*.ps1 text eol=crlf` |

### v2.8 — bugs found post-merge by real-world Codex install

Three bugs that the pre-merge pre-mortem missed because they only surface with a real Codex 0.125 session, fixed in v2.8.1:

| Bug | Symptom | Fix |
|---|---|---|
| `for line in sys.stdin:` buffers on Windows | Codex 0.125 reports `MCP startup failed: Transport closed` for sqlbroker even though manual stdin piping works | `stdio_proxy.py` switched to explicit `readline()` loop + emits `sqlbroker stdio_proxy ready` on stderr (mirrors mssql-mcp's readiness signal) |
| Codex spawns `.bat` files unreliably | Same "Transport closed" when MCP `command` points at `run_stdio_proxy.bat` | Recommend `codex mcp add sqlbroker -- python.exe -u stdio_proxy.py` instead — bypass cmd shell + bat |
| README claimed `/sqlbroker-install` etc. as Codex slash commands | "Unrecognized command" in interactive Codex | Codex skills aren't slash commands; they're AI-invoked from natural language. Slash commands table in README rewritten as a "how to invoke" comparison. |
| `defaultPrompt` array of 4 hits Codex's max-3 limit | Manifest validation warning logged repeatedly | Trimmed to 3 entries |
| Plugin cache stale after marketplace upgrade hits "Access denied" | Skills don't load even after `codex plugin marketplace upgrade` | Documented clean-rebuild workaround: `marketplace remove` + `rm -rf ~/.codex/.tmp/marketplaces/<name>` + `marketplace add` |

### v2.8 — known sharp edges still in production

1. **`-RefreshOnly` skips MCP wiring on both platforms.** If you ran the first install without `-Codex` and now want Codex wired, re-run *without* `-RefreshOnly`. Documented in the Configuration table.
2. **TOML patch overwrites the entire `[mcp_servers.sqlbroker]` block.** Hand-edited `env_vars`, custom `cwd`, or `startup_timeout_sec` get nuked on re-deploy. The script writes a `.bak.YYYYMMDDHHMMSS` first.
3. **`codex mcp add` may not be on PATH for an elevated Windows shell** when Codex was installed per-user via `npm`. Fallback TOML patch handles this, but it requires `tomli_w` install — offline machines may silently fail.
4. **Codex skill activation on first install is sometimes delayed by one session.** If you ran `codex plugin marketplace add ...` mid-session, the skill may not appear until you exit and relaunch `codex`. Use `/plugins` to confirm `sqlbroker` shows green before asking the agent to use it.
