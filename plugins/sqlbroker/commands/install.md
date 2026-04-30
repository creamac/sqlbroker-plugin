---
description: Install the mcp-sqlbroker service (Windows / macOS / Linux)
---

Install the mcp-sqlbroker service on this machine. Picks the right deploy
script for the OS, runs it elevated (UAC on Windows / sudo on Unix), and
patches the host's MCP config so the broker is auto-wired.

> **Maintenance note:** mirrored at `plugins/sqlbroker/skills/sqlbroker-install/SKILL.md` (read by Codex CLI). Keep both files in sync.

## Step 1 — ALWAYS ask the user where to install (FIRST THING)

**Always pop this question first**, even before probing the broker. Reason: the user may have a previous install at the default location but want to move it, or may want to confirm the location explicitly. The `/health` probe in Step 2 then *responds* to their choice rather than silently bypassing it.

Use **`AskUserQuestion`** with header `Install location?`:

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

If they pick `Other`, ask in a follow-up free-text question for the absolute path. Prefer paths without spaces on Windows. Capture the chosen value as `$installDir` (or the literal `auto-detect`).

## Step 2 — probe `/health` and reconcile with the chosen path

```powershell
Invoke-WebRequest 'http://127.0.0.1:8765/health' -UseBasicParsing | Select-Object -Expand Content
```

Then reconcile the user's choice from Step 1 with what `/health` reports:

| User picked | /health says | Action |
|---|---|---|
| `Auto-detect` | broker reachable | `$installDir` ← `install_dir` from response. **Go to Step 4 (wire MCP only).** |
| `Auto-detect` | broker not reachable | Fall back to `D:\util\mcp-sqlbroker`. **Go to Step 3 (elevated deploy).** |
| Specific path X | broker reachable, install_dir = X | Same path → user wants a refresh. **Go to Step 3 with `-RefreshOnly` added.** |
| Specific path X | broker reachable, install_dir = Y (≠ X) | ⚠️ **Conflict.** Tell the user: "Existing broker at Y. Installing a second one at X would conflict on port 8765. Either pick Y above, OR uninstall the existing one first (`Unregister-ScheduledTask mcp-sqlbroker -Confirm:$false; Remove-Item -Recurse Y`)." Ask them to re-run with a corrected choice. **Stop.** |
| Specific path X | broker not reachable | Fresh install at X. **Go to Step 3 (elevated deploy).** |

For older brokers (< 2.8.2) that don't return `install_dir`, scan common paths until one contains `run_stdio_proxy.bat`: `D:\util\mcp-sqlbroker`, `C:\util\mcp-sqlbroker`, `C:\opt\mcp-sqlbroker`, `C:\apps\mcp-sqlbroker`, `%USERPROFILE%\mcp-sqlbroker`.

## Step 3 — elevated deploy (only when Step 2 says "deploy")

Tell the user a UAC dialog will pop up. Then launch the elevated PowerShell window — pass `-InstallDir` with the value from Step 2:

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

For Linux/macOS:

```bash
sudo INSTALL_DIR='<value from Step 2>' "${CLAUDE_PLUGIN_ROOT}/scripts/deploy.sh"
```

Add `--codex` / `--auto-wire` / `--refresh-only` as needed.

After the user reports the deploy window/output finished, run a health check:

```powershell
Invoke-WebRequest 'http://127.0.0.1:8765/health' -UseBasicParsing | Select-Object -Expand Content
```

The deploy output ends with a "Wire it into Claude Code / Codex" snippet. If `-AutoWire` / `--auto-wire` was used, the entry was already written. Otherwise tell the user to **paste that snippet under `mcpServers` in `~/.claude.json`** (Claude Code), then `/reload-plugins`.

## Step 4 — wire `~/.claude.json` (entry point when Step 2 says "skip deploy")

If `-AutoWire` was used during a prior deploy, this is already done. Otherwise add to `~/.claude.json` (replace `<install_dir>` with the path from Step 2):

```json
"mcpServers": {
  "sqlbroker": { "command": "<install_dir>\\run_stdio_proxy.bat", "args": [] }
}
```

Then `/reload-plugins` (or restart Claude Code).

## Step 5 — first connection

Once wired, suggest `/sqlbroker:add <alias>` to register the first DB connection.

## Optional flags (Windows)

`-InstallDir`, `-Port`, `-BindHost`, `-SkipOdbc`, `-SkipService`, `-AutoWire`, `-SkipMcpWire`, `-RefreshOnly`, `-Codex`. Pass them to `deploy.ps1` in the elevated window.

## Optional env vars (Unix)

`INSTALL_DIR`, `PORT`, `BIND_HOST`, `SERVICE_NAME`. Set them before invoking `sudo deploy.sh`. Flags: `--auto-wire`, `--skip-mcp-wire`, `--refresh-only`, `--codex`.

## Notes

- The deploy scripts do NOT touch existing `connections.json`, so re-running is safe.
- Passwords are AES-128-CBC + HMAC-SHA256 encrypted with `master.key` (32 random bytes generated at install). They are NOT in `connections.json` plaintext.
