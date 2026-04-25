# sqlbroker-marketplace

Claude Code plugin marketplace for managing local MSSQL access **without ever putting credentials in the conversation**.

## What's in it

### `sqlbroker` plugin (v2.2.0 — cross-platform)

Alias-based MSSQL broker for **Windows / macOS / Linux**. The local service holds passwords in the **OS keyring** (Windows Credential Manager / macOS Keychain / Linux Secret Service); Claude calls databases by alias only — passwords never enter the chat or any prompt.

- 🛢️ **Auto-activating skill** — any DB-query intent routes through the broker
- ⚡ **6 slash commands** — `install`, `add`, `list`, `test`, `remove`, `status`
- 🔌 **stdio MCP shim** that proxies to the local HTTP broker
- 🛡️ **3 policies** — `readonly` (block DML/DDL/EXEC), `exec-only` (SELECT + EXEC), `full`
- 🚫 **No NSSM** — uses the OS-native init system (Task Scheduler / launchd / systemd)

→ Plugin user guide: [`plugins/sqlbroker/README.md`](plugins/sqlbroker/README.md)

---

## Quickstart

### 0. Prerequisites per OS

| OS | What you need | What gets auto-installed |
|---|---|---|
| **Windows 10/11/Server 2016+** | Claude Code, admin shell access | embedded Python, ODBC Driver 18, Task Scheduler entry |
| **macOS 12+** | Claude Code, `python3` (`brew install python@3.13`), `sudo` | venv + `pyodbc` + `keyring`, launchd plist. ODBC driver: `brew install msodbcsql18` (manual) |
| **Linux (Debian/Ubuntu/RHEL/Fedora)** | Claude Code, `python3` + `python3-venv`, `sudo` | venv + `pyodbc` + `keyring`, systemd unit. ODBC driver: install `msodbcsql18` from Microsoft repo (manual) |

### 1. Install the plugin (every OS)

```
/plugin marketplace add creamac/sqlbroker-plugin
/plugin install sqlbroker@creamac/sqlbroker-plugin
/reload-plugins
```

### 2. Install the local service

```
/sqlbroker:install
```

The slash command picks the right deploy script for your OS and runs it elevated.

- **Windows** — UAC dialog pops up, click "Yes". Embedded Python + ODBC driver + Scheduled Task all set up automatically.
- **macOS / Linux** — script prompts for `sudo`. Uses your system `python3`, creates a venv, registers a launchd plist (Mac) or systemd unit (Linux).

### 3. Wire it into Claude Code (one-time, manual)

The deploy script prints an MCP wiring snippet at the end. Paste it under the `mcpServers` key in `~/.claude.json`:

```json
{
  "mcpServers": {
    "sqlbroker": {
      "command": "D:\\util\\mcp-sqlbroker\\run_stdio_proxy.bat",
      "args": []
    }
  }
}
```

(macOS / Linux: `command` will be `/opt/mcp-sqlbroker/run_stdio_proxy.sh`)

Then restart Claude Code (or `/reload-plugins`).

> ℹ️ The plugin manifest doesn't auto-register the MCP server because Claude Code's plugin schema doesn't support per-OS `command`. We chose explicit user-side wiring over a brittle Windows-only default.

### 4. Add your first connection

```
/sqlbroker:add prod_main
```

The slash command prompts for **host, user, password (hidden), default_database, policy**. **Recommend `readonly` for production.** Password is stored in the OS keyring; `connections.json` carries no secret.

### 5. Use it

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
run_stdio_proxy.[bat|sh] → stdio_proxy.py  (pure stdlib shim)
    │
    │  HTTP POST /mcp
    ▼
mcp-sqlbroker service (127.0.0.1:8765)
    ├─ connections.json (no passwords — just metadata + alias names)
    ├─ OS keyring       (Credential Manager / Keychain / Secret Service)
    ├─ policy enforcement (readonly | exec-only | full)
    └─ pyodbc → MSSQL
```

Service backend per OS:

| OS | Init system | Auto-restart |
|---|---|---|
| Windows | Task Scheduler (`mcp-sqlbroker`, runs as SYSTEM at boot) | Yes (RestartCount 99 / 1m interval) |
| macOS | launchd (`com.creamac.mcp-sqlbroker.plist`) | Yes (`KeepAlive`) |
| Linux | systemd (`mcp-sqlbroker.service`) | Yes (`Restart=on-failure`) |

The chat sees **alias names only** — never hosts, users, or passwords.

---

## Verifying it works

```
/sqlbroker:status
```

Or query the broker directly:

```powershell
Invoke-WebRequest http://127.0.0.1:8765/health -UseBasicParsing | Select-Object -Expand Content
```

```bash
curl -fsS http://127.0.0.1:8765/health
```

---

## Migrating from v1.x

v1 stored passwords as `password_dpapi` blobs in `connections.json`. v2 stores them in the OS keyring.

- **Auto-migration:** v2 server migrates legacy entries on first request (Windows only; `deploy.ps1` installs `pywin32` automatically when it detects legacy aliases).
- **Manual migration:** `python manage_conn.py migrate`.

After migration, `connections.json` no longer carries any password field.

---

## Uninstall

```
/plugin uninstall sqlbroker
/plugin marketplace remove sqlbroker-marketplace
/reload-plugins
```

Then stop and remove the service:

**Windows (admin):**
```powershell
Stop-ScheduledTask     -TaskName mcp-sqlbroker
Unregister-ScheduledTask -TaskName mcp-sqlbroker -Confirm:$false
Remove-Item -Recurse -Force D:\util\mcp-sqlbroker     # if you also want files gone
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

Don't forget to remove the `mcpServers.sqlbroker` entry from `~/.claude.json`. Passwords in the OS keyring will remain until you delete them by alias (use the keyring app of your OS).

---

## Security notes

- Broker binds **127.0.0.1 only** — no token, no network exposure. Trust boundary = the local host.
- Passwords stored in the OS keyring (DPAPI / Keychain / libsecret). Anyone with code-execution as the same user/system can read them — protect the host.
- Slash commands and the skill use an `MCP_PWD` env-var pattern when adding aliases, so passwords never enter shell history.
- For production aliases, use a SQL login with `db_datareader` only AND set the broker policy to `readonly`. Defense in depth.

---

## License

MIT — see [`LICENSE`](LICENSE).

## Author

[@creamac](https://github.com/creamac)
