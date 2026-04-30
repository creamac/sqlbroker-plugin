---
description: Install the mcp-sqlbroker service (Windows / macOS / Linux)
---

Install the mcp-sqlbroker service on this machine. Picks the right deploy
script for the OS, runs it elevated (UAC on Windows / sudo on Unix), and
patches the host's MCP config so the broker is auto-wired.

> **Maintenance note:** mirrored at `plugins/sqlbroker/skills/sqlbroker-install/SKILL.md` (read by Codex CLI). Keep both files in sync.

## Step 0 — fast-path check (ALWAYS DO THIS FIRST)

Before launching any elevated installer, probe the broker's HTTP health endpoint:

```powershell
Invoke-WebRequest 'http://127.0.0.1:8765/health' -UseBasicParsing | Select-Object -Expand Content
```

If you get a JSON response with `"ok":true`, **the broker is already installed and running**. On v2.8.2+ the response also includes `install_dir` and `version` — capture those. Skip directly to Step 6 (only wire `~/.claude.json`, no UAC needed). This is the common case when the user previously installed via Codex CLI or a manual deploy.

## Step 0.5 — ask the user where to install (ONLY if Step 0 found nothing)

Use **`AskUserQuestion`** with header `Install location?` and these option labels:

- Windows: `D:\util\mcp-sqlbroker` (recommended — D: drive), `C:\opt\mcp-sqlbroker` (Linux-style), `C:\Program Files\mcp-sqlbroker` (system-wide), `%USERPROFILE%\mcp-sqlbroker` (per-user, laptops with no D:), `Other (custom path)`
- Unix: `/opt/mcp-sqlbroker` (recommended), `/usr/local/mcp-sqlbroker`, `~/.local/mcp-sqlbroker` (per-user), `Other (custom path)`

If they pick `Other`, ask a follow-up free-text question for the absolute path. Prefer paths without spaces on Windows. Capture the chosen path as `$installDir` and pass it through to deploy via `-InstallDir`. **Don't proceed without explicit user confirmation — install path is sticky once the scheduled task is registered.**

## Step 1 — detect OS

   - Windows → use `${CLAUDE_PLUGIN_ROOT}/scripts/deploy.ps1`
   - macOS / Linux → use `${CLAUDE_PLUGIN_ROOT}/scripts/deploy.sh`

2. **Windows path:**

   Tell the user a UAC dialog will pop up. Then launch the elevated PowerShell window — pass `-InstallDir` with the path captured in Step 0.5:

   ```powershell
   $deploy = Join-Path "${CLAUDE_PLUGIN_ROOT}" 'scripts\deploy.ps1'
   $installDir = '<chosen path from Step 0.5, or D:\util\mcp-sqlbroker>'
   Start-Process powershell.exe -Verb RunAs -ArgumentList @(
     '-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass',
     '-File', $deploy,
     '-InstallDir', $installDir
   )
   ```

   Add `-Codex` to also patch `~/.codex/config.toml`. Add `-AutoWire` to skip the `~/.claude.json` confirmation prompt.

   The script registers a Scheduled Task named `mcp-sqlbroker` (no NSSM).

3. **macOS / Linux path:**

   Tell the user `sudo` will be required. Pass `INSTALL_DIR=` if Step 0.5 chose a non-default path:

   ```bash
   sudo INSTALL_DIR='<chosen path or /opt/mcp-sqlbroker>' "${CLAUDE_PLUGIN_ROOT}/scripts/deploy.sh"
   ```

   Add `--codex` to also patch `~/.codex/config.toml`. Add `--auto-wire` to skip the `~/.claude.json` confirmation prompt.

4. After the user reports the deploy window/output finished, run a health check:

   ```bash
   curl -fsS http://127.0.0.1:8765/health
   ```

   ```powershell
   Invoke-WebRequest 'http://127.0.0.1:8765/health' -UseBasicParsing | Select-Object -Expand Content
   ```

5. The deploy output ends with a "Wire it into Claude Code / Codex" snippet. If `-AutoWire` / `--auto-wire` was used, the entry was already written. Otherwise tell the user to **paste that snippet under `mcpServers` in `~/.claude.json`** (Claude Code) or **as `[mcp_servers.sqlbroker]` in `~/.codex/config.toml`** (Codex), then `/reload-plugins` (Claude) or relaunch Codex.

## Step 6 — wire `~/.claude.json` (entry point if Step 0 succeeded)

If `-AutoWire` was used during a prior deploy, this is already done. Otherwise:

**First, detect the actual install dir from `/health`** (don't assume the default):

```powershell
(Invoke-WebRequest 'http://127.0.0.1:8765/health' -UseBasicParsing).Content | ConvertFrom-Json | Select-Object -Expand install_dir
```

Older brokers (< 2.8.2) don't return `install_dir`; in that case, scan common paths until one contains `run_stdio_proxy.bat`: `D:\util\mcp-sqlbroker`, `C:\util\mcp-sqlbroker`, `C:\opt\mcp-sqlbroker`, `C:\apps\mcp-sqlbroker`, `%USERPROFILE%\mcp-sqlbroker`.

Then add to `~/.claude.json` (replace `<install_dir>` with the path you got):

```json
"mcpServers": {
  "sqlbroker": { "command": "<install_dir>\\run_stdio_proxy.bat", "args": [] }
}
```

Then `/reload-plugins` (or restart Claude Code).

## Step 7 — first connection

Once wired, suggest `/sqlbroker:add <alias>` to register the first DB connection.

## Optional flags (Windows)

`-InstallDir`, `-Port`, `-BindHost`, `-SkipOdbc`, `-SkipService`, `-AutoWire`, `-SkipMcpWire`, `-RefreshOnly`, `-Codex`. Pass them to `deploy.ps1` in the elevated window.

## Optional env vars (Unix)

`INSTALL_DIR`, `PORT`, `BIND_HOST`, `SERVICE_NAME`. Set them before invoking `sudo deploy.sh`. Flags: `--auto-wire`, `--skip-mcp-wire`, `--refresh-only`, `--codex`.

## Notes

- The deploy scripts do NOT touch existing `connections.json`, so re-running is safe.
- Passwords are AES-128-CBC + HMAC-SHA256 encrypted with `master.key` (32 random bytes generated at install). They are NOT in `connections.json` plaintext.
