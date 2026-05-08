---
name: sqlbroker-install
description: Install the mcp-sqlbroker local service (Windows / macOS / Linux). Triggers on "/sqlbroker-install", "/sqlbroker:install", "install sqlbroker", "set up sqlbroker service", "deploy mcp-sqlbroker".
---

# Install the mcp-sqlbroker service

Install the mcp-sqlbroker service on this machine. Picks the right deploy
script for the OS, runs it elevated (UAC on Windows / sudo on Unix), and
patches the host's MCP config so the broker is auto-wired.

## Step 1 — ALWAYS ask the user where to install (FIRST THING)

**Always pop this question first**, even before probing the broker. Reason: the user may have a previous install at the default location but want to move it, or may want to confirm the location explicitly. The `/health` probe in Step 2 then *responds* to their choice rather than silently bypassing it.

**On Claude Code**, use `AskUserQuestion` with header `Install location?`:

- Windows options:
  - `Auto-detect existing install` (recommended — uses whatever path the running broker reports via /health)
  - `D:\util\mcp-sqlbroker` (default for hosts with a D: drive)
  - `C:\opt\mcp-sqlbroker` (Linux-style, no D: required)
  - `C:\Program Files\mcp-sqlbroker` (system-wide)
  - `%USERPROFILE%\mcp-sqlbroker` (per-user, common on laptops without D:)
  - `Other (custom path)`
- Unix options:
  - `Auto-detect existing install` (recommended)
  - `/opt/mcp-sqlbroker` (default)
  - `/usr/local/mcp-sqlbroker`
  - `~/.local/mcp-sqlbroker` (per-user)
  - `Other (custom path)`

If they pick `Other`, ask in a follow-up free-text question for the absolute path. On Windows, prefer paths without spaces (work but require careful quoting in scheduled task / wrapper bat — flag this risk).

Capture the chosen value as `$installDir` (or the literal string `auto-detect`).

**On Codex CLI**, you can't pop a UI question — list the OS-appropriate options in your reply and ask the user to type their preferred path (or `auto-detect`). Pause for their answer before proceeding.

## Step 2 — probe `/health` and reconcile with the chosen path

```bash
curl -fsS http://127.0.0.1:8765/health
```

```powershell
Invoke-WebRequest 'http://127.0.0.1:8765/health' -UseBasicParsing | Select-Object -Expand Content
```

Then reconcile the user's choice from Step 1 with what `/health` reports:

| User picked | /health says | Action |
|---|---|---|
| `Auto-detect` | broker reachable | `$installDir` ← `install_dir` from response. Skip deploy. **Go to Step 4 (wire MCP only).** |
| `Auto-detect` | broker not reachable | Fall back to per-OS default (`D:\util\mcp-sqlbroker` / `/opt/mcp-sqlbroker`). **Go to Step 2.5 (pick install mode).** |
| Specific path X | broker reachable, install_dir = X | Same path → user wants a refresh. **Go to Step 3b with `-RefreshOnly` added.** (Refresh always inherits the original install's mode — admin needed only if it was a service install.) |
| Specific path X | broker reachable, install_dir = Y (≠ X) | ⚠️ **Conflict.** Tell the user: "Existing broker at Y. Installing a second one at X would conflict on port 8765. Either pick Y above, OR uninstall the existing one first (`Unregister-ScheduledTask mcp-sqlbroker -Confirm:$false` for service install, or remove the Startup `.lnk` for portable install; then `Remove-Item -Recurse Y`)." Ask them to re-run with a corrected choice. **Stop.** |
| Specific path X | broker not reachable | Fresh install at X. **Go to Step 2.5 (pick install mode).** |

For older brokers (< 2.8.2) that don't return `install_dir` on `/health`, fall back to scanning common paths until one contains `run_stdio_proxy.bat` / `run_stdio_proxy.sh`:
- Windows: `D:\util\mcp-sqlbroker`, `C:\util\mcp-sqlbroker`, `C:\opt\mcp-sqlbroker`, `C:\apps\mcp-sqlbroker`, `%USERPROFILE%\mcp-sqlbroker`
- Unix: `/opt/mcp-sqlbroker`, `/usr/local/mcp-sqlbroker`, `~/.local/mcp-sqlbroker`

## Step 2.5 — pick install mode (only when Step 2 says "deploy fresh")

If Step 2 routed to "fresh install" (no broker running), **always ask** which install mode to use. Use `AskUserQuestion` with header `Install mode?`:

- `Quick (portable, no admin)` — **recommended for laptops, single-user machines, Codex CLI users tired of UAC**. Bootstraps embedded Python in `$installDir`, drops a Startup folder shortcut so the broker auto-starts on logon, runs as the current user. ~30 seconds. No UAC, no scheduled task, no ODBC auto-install (you must already have `ODBC Driver 17/18 for SQL Server` — check with `Get-OdbcDriver`).
- `Service (always-on, needs admin)` — original heavy path. Registers Scheduled Task running as SYSTEM, auto-installs ODBC Driver 18, broker survives logout. ~5 minutes + UAC. Use this when the broker must serve multiple Windows users or boot before login.

If user picks `Quick`, **go to Step 3a**. If `Service`, **go to Step 3b**.

If Step 2 detected a same-path refresh, skip this question and go directly to **Step 3b with `-RefreshOnly`** (refresh always uses the same mode the install was created in — admin needed only if it was a service install).

## Step 3a — Quick portable deploy (no UAC, recommended)

```powershell
$deploy = Join-Path "${CLAUDE_PLUGIN_ROOT}" 'scripts\deploy.ps1'
$installDir = '<value from Step 2>'
& $deploy -InstallDir $installDir -Portable
```

Note: **no `Start-Process -Verb RunAs`** — runs in the current shell as the current user. The `-Portable` flag implies `-SkipService -SkipOdbc -AutoWire`. Add `-Codex` to also patch `~/.codex/config.toml` in the same call.

What this does:
1. Downloads embedded Python 3.13 (~10 MB) into `$installDir\python313\`
2. Pip-installs `pyodbc` + `pycryptodome` into that embedded Python
3. Copies `server.py`, `manage_conn.py`, `stdio_proxy.py`, `run_stdio_proxy.bat` to `$installDir`
4. Generates `master.key` (32 random bytes)
5. Writes `start-broker.bat` + drops a `.lnk` into the user's Startup folder (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\mcp-sqlbroker.lnk`) so the broker auto-starts on next logon
6. Launches the broker right now (hidden window) so the user can use it immediately
7. Wires `~/.claude.json` (and optionally `~/.codex/config.toml` with `-Codex`)

**ODBC Driver pre-flight (Quick mode skips auto-install):** before running the deploy, check that `ODBC Driver 17 for SQL Server` or `ODBC Driver 18 for SQL Server` is already on the system:

```powershell
Get-OdbcDriver -Name '*ODBC Driver* for SQL Server' | Select-Object -ExpandProperty Name
```

If neither is listed, tell the user to install it first via the [Microsoft download](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server) — this is the one piece Quick mode cannot do without admin. Then retry.

## Step 3b — Service deploy (always-on, needs admin)

Pick the right script for the OS — and pass through the `$installDir` you settled on in Step 2.

**Windows:**

```powershell
$deploy = Join-Path "${CLAUDE_PLUGIN_ROOT}" 'scripts\deploy.ps1'
$installDir = '<value from Step 2>'
Start-Process powershell.exe -Verb RunAs -ArgumentList @(
  '-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass',
  '-File', $deploy,
  '-InstallDir', $installDir
)
```

Add `-Codex` to also patch `~/.codex/config.toml`. Add `-AutoWire` to skip the `~/.claude.json` confirmation prompt. Add `-RefreshOnly` if Step 2 detected a same-path refresh (skips Python/ODBC re-install, just bounces the scheduled task).

The script registers a Scheduled Task named `mcp-sqlbroker` (no NSSM).

**macOS / Linux:**

```bash
sudo INSTALL_DIR='<value from Step 2>' "${CLAUDE_PLUGIN_ROOT}/scripts/deploy.sh"
```

Add `--codex` to also patch `~/.codex/config.toml`. Add `--auto-wire` to skip the `~/.claude.json` confirmation prompt. Add `--refresh-only` for same-path refresh.

The script writes either a systemd unit (`/etc/systemd/system/mcp-sqlbroker.service`) or a launchd plist (`/Library/LaunchDaemons/com.creamac.mcp-sqlbroker.plist`).

After the user reports the deploy window/output finished, run a health check:

```bash
curl -fsS http://127.0.0.1:8765/health
```

```powershell
Invoke-WebRequest 'http://127.0.0.1:8765/health' -UseBasicParsing | Select-Object -Expand Content
```

The deploy output ends with a "Wire it into Claude Code / Codex" snippet. If `-AutoWire` / `--auto-wire` was used, the entry was already written. Otherwise tell the user to **paste that snippet under `mcpServers` in `~/.claude.json`** (Claude Code) or **as `[mcp_servers.sqlbroker]` in `~/.codex/config.toml`** (Codex), then restart their CLI (or `/reload-plugins` may be enough for Claude Code).

## Step 4 — wire your CLI's MCP config (entry point when Step 2 says "skip deploy")

If Step 2's reconciliation routed you here, the broker is already running and `$installDir` already came from `/health`. You just need to wire the CLI.

**Codex CLI — direct CLI wiring (preferred when running inside Codex):**

```bash
codex mcp add sqlbroker -- <install_dir>\run_stdio_proxy.bat       # Windows
codex mcp add sqlbroker -- <install_dir>/run_stdio_proxy.sh        # Linux/macOS
```

Substitute the actual path you got from `/health` for `<install_dir>`. This needs no admin and no UAC. Codex's own CLI rewrites `~/.codex/config.toml` for you. Verify with:

```bash
codex mcp list
codex mcp get sqlbroker
```

If the user is running you (the AI) inside Codex with a sandbox that blocks `codex mcp add`, ask them to run that command themselves in their own terminal.

**Claude Code — JSON edit:**

If `/sqlbroker:install` was run with `-AutoWire`, this is already done. Otherwise add to `~/.claude.json` (replace the path with what `/health` reported):

```json
"mcpServers": {
  "sqlbroker": { "command": "<install_dir>\\run_stdio_proxy.bat", "args": [] }
}
```

Then `/reload-plugins` (or restart Claude Code).

## Step 5 — first connection

Once wired, suggest `/sqlbroker:add <alias>` (Claude) or `/sqlbroker-add <alias>` (Codex) to register the first DB connection.

## What the deploy script does (zero prerequisites on Windows)

**Windows (`deploy.ps1`):**
- Downloads Python 3.13 embeddable into `<InstallDir>\python313\` — no system Python install required.
- Auto-installs ODBC Driver 18 for SQL Server if missing.
- Registers a Scheduled Task running as SYSTEM at boot, auto-restart on failure.
- With `-Codex`: detects `codex` CLI and runs `codex mcp add sqlbroker -- <run_stdio_proxy.bat>`. Falls back to manual TOML patch if the CLI isn't on PATH.

**Linux (`deploy.sh`):**
- Uses system `python3` (apt/yum/dnf must have it).
- Creates a venv, installs `pyodbc` + `pycryptodome`.
- Hints at ODBC Driver 18 install (Microsoft repo apt/yum) if missing.
- Writes systemd unit, enables, starts.
- With `--codex`: same as Windows.

**macOS (`deploy.sh`):**
- Uses system `python3` (Homebrew or python.org).
- Creates a venv, installs `pyodbc` + `pycryptodome`.
- Hints at `brew install msodbcsql18` if missing.
- Writes a LaunchDaemon plist, loads via `launchctl`.

## Optional flags (Windows)

`-InstallDir`, `-Port`, `-BindHost`, `-SkipOdbc`, `-SkipService`, `-AutoWire`, `-SkipMcpWire`, `-RefreshOnly`, `-Codex`. Pass them to `deploy.ps1` in the elevated window.

## Optional env vars (Unix)

`INSTALL_DIR`, `PORT`, `BIND_HOST`, `SERVICE_NAME`. Set them before invoking `sudo deploy.sh`. Flags: `--auto-wire`, `--skip-mcp-wire`, `--refresh-only`, `--codex`.

## Notes

- The deploy scripts do NOT touch existing `connections.json`, so re-running is safe.
- Passwords are AES-128-CBC + HMAC-SHA256 encrypted with `master.key` (32 random bytes generated at install). They are NOT in `connections.json` plaintext.
