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

If you get `{"ok":true,"server":"sqlbroker"}`, **the broker is already installed and running**. Skip to Step 6 — only wire `~/.claude.json` (no UAC needed). This is the common case when the user previously installed via Codex CLI or a manual deploy.

## Step 1 — detect OS (only if Step 0 found no broker)

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

   Add `-Codex` to also patch `~/.codex/config.toml`. Add `-AutoWire` to skip the `~/.claude.json` confirmation prompt.

   The script registers a Scheduled Task named `mcp-sqlbroker` (no NSSM).

3. **macOS / Linux path:**

   Tell the user `sudo` will be required. Suggest they run:

   ```bash
   sudo "${CLAUDE_PLUGIN_ROOT}/scripts/deploy.sh"
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

If `-AutoWire` was used during a prior deploy, this is already done. Otherwise add manually:

```json
"mcpServers": {
  "sqlbroker": { "command": "D:\\util\\mcp-sqlbroker\\run_stdio_proxy.bat", "args": [] }
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
