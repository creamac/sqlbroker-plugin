---
name: sqlbroker-install
description: Install the mcp-sqlbroker local service (Windows / macOS / Linux). Triggers on "/sqlbroker-install", "/sqlbroker:install", "install sqlbroker", "set up sqlbroker service", "deploy mcp-sqlbroker".
---

# Install the mcp-sqlbroker service

Install the mcp-sqlbroker service on this machine. Picks the right deploy
script for the OS, runs it elevated (UAC on Windows / sudo on Unix), and
patches the host's MCP config so the broker is auto-wired.

## Steps

1. Detect OS:
   - Windows → use `${CLAUDE_PLUGIN_ROOT}/scripts/deploy.ps1` (or `${CODEX_PLUGIN_ROOT}/scripts/deploy.ps1` on Codex; if neither variable resolves, use the absolute path to the deploy script in the cloned repo)
   - macOS / Linux → use `${CLAUDE_PLUGIN_ROOT}/scripts/deploy.sh`

2. **Windows path:**

   Tell the user a UAC dialog will pop up. Then launch the elevated PowerShell window:

   ```powershell
   $deploy = Join-Path "${CLAUDE_PLUGIN_ROOT}" 'scripts\deploy.ps1'
   Start-Process powershell.exe -Verb RunAs -ArgumentList @(
     '-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $deploy
   )
   ```

   Add `-Codex` to also patch `~/.codex/config.toml`. Add `-AutoWire` to skip the `~/.claude.json` confirmation prompt.

   The script registers a Scheduled Task named `mcp-sqlbroker` (no NSSM).

3. **macOS / Linux path:**

   Tell the user `sudo` will be required. Suggest they run:

   ```bash
   sudo "${CLAUDE_PLUGIN_ROOT}/scripts/deploy.sh"
   ```

   Add `--codex` to also patch `~/.codex/config.toml`. Add `--auto-wire` to skip the `~/.claude.json` confirmation prompt.

   The script writes either a systemd unit (`/etc/systemd/system/mcp-sqlbroker.service`) or a launchd plist (`/Library/LaunchDaemons/com.creamac.mcp-sqlbroker.plist`).

4. After the user reports the deploy window/output finished, run a health check:

   ```bash
   curl -fsS http://127.0.0.1:8765/health    # Unix
   ```

   ```powershell
   Invoke-WebRequest 'http://127.0.0.1:8765/health' -UseBasicParsing | Select-Object -Expand Content
   ```

5. The deploy output ends with a "Wire it into Claude Code / Codex" snippet. If `-AutoWire` / `--auto-wire` was used, the entry was already written. Otherwise tell the user to **paste that snippet under `mcpServers` in `~/.claude.json`** (Claude Code) or **as `[mcp_servers.sqlbroker]` in `~/.codex/config.toml`** (Codex), then restart their CLI (or `/reload-plugins` may be enough for Claude Code).

6. Once wired, suggest `/sqlbroker:add <alias>` (Claude) or `/sqlbroker-add <alias>` (Codex) to register the first DB connection.

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
