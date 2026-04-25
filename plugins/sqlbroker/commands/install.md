---
description: Install the mcp-sqlbroker service (Windows / macOS / Linux)
---

Install the mcp-sqlbroker service on this machine. Picks the right deploy
script for the OS, runs it elevated (UAC on Windows / sudo on Unix), and
prints the MCP wiring snippet for the user to paste into `~/.claude.json`.

## Steps

1. Detect OS:
   - Windows → use `${CLAUDE_PLUGIN_ROOT}/scripts/deploy.ps1`
   - macOS / Linux → use `${CLAUDE_PLUGIN_ROOT}/scripts/deploy.sh`

2. **Windows path:**

   Tell the user a UAC dialog will pop up. Then launch the elevated PowerShell window:

   ```powershell
   $deploy = Join-Path "${CLAUDE_PLUGIN_ROOT}" 'scripts\deploy.ps1'
   Start-Process powershell.exe -Verb RunAs -ArgumentList @(
     '-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $deploy
   )
   ```

   The script registers a Scheduled Task named `mcp-sqlbroker` (no NSSM).

3. **macOS / Linux path:**

   Tell the user `sudo` will be required. Suggest they run:

   ```bash
   sudo "${CLAUDE_PLUGIN_ROOT}/scripts/deploy.sh"
   ```

   The script writes either a systemd unit (`/etc/systemd/system/mcp-sqlbroker.service`) or a launchd plist (`/Library/LaunchDaemons/com.creamac.mcp-sqlbroker.plist`).

4. After the user reports the deploy window/output finished, run a health check:

   ```bash
   curl -fsS http://127.0.0.1:8765/health    # Unix
   ```

   ```powershell
   Invoke-WebRequest 'http://127.0.0.1:8765/health' -UseBasicParsing | Select-Object -Expand Content
   ```

5. The deploy output ends with an "Wire it into Claude Code" snippet. Tell the user to **paste that snippet under `mcpServers` in `~/.claude.json`**, then restart Claude Code (or `/reload-plugins` may be enough).

6. Once wired, suggest `/sqlbroker:add <alias>` to register the first DB connection.

## What the deploy script does (zero prerequisites on Windows)

**Windows (`deploy.ps1`):**
- Downloads Python 3.13 embeddable into `<InstallDir>\python313\` — no system Python install required.
- Auto-installs ODBC Driver 18 for SQL Server if missing.
- Registers a Scheduled Task running as SYSTEM at boot, auto-restart on failure.

**Linux (`deploy.sh`):**
- Uses system `python3` (apt/yum/dnf must have it).
- Creates a venv, installs `pyodbc` + `keyring`.
- Hints at ODBC Driver 18 install (Microsoft repo apt/yum) if missing.
- Writes systemd unit, enables, starts.

**macOS (`deploy.sh`):**
- Uses system `python3` (Homebrew or python.org).
- Creates a venv, installs `pyodbc` + `keyring`.
- Hints at `brew install msodbcsql18` if missing.
- Writes a LaunchDaemon plist, loads via `launchctl`.

## Optional flags (Windows)

`-InstallDir`, `-Port`, `-BindHost`, `-SkipOdbc`, `-SkipService`. Pass them to `deploy.ps1` in the elevated window.

## Optional env vars (Unix)

`INSTALL_DIR`, `PORT`, `BIND_HOST`, `SERVICE_NAME`. Set them before invoking `sudo deploy.sh`.

## Notes

- The deploy scripts do NOT touch existing `connections.json`, so re-running is safe.
- Passwords are stored in the OS keyring (Windows Credential Manager / macOS Keychain / Linux Secret Service) — they are NOT in `connections.json`.
