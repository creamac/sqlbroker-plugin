---
description: Install the mcp-sqlbroker service (Windows / macOS / Linux)
---

Install the mcp-sqlbroker service on this machine. Picks the right deploy
script for the OS, runs it elevated (UAC on Windows / sudo on Unix), and
patches the host's MCP config so the broker is auto-wired.

> **Maintenance note:** the canonical version of this content lives at `plugins/sqlbroker/skills/sqlbroker-install/SKILL.md` (used by Codex CLI). Keep this file in sync when editing — Claude Code does not substitute `${CLAUDE_PLUGIN_ROOT}` in command bodies, so we cannot reference the skill file as a thin shim.

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

5. The deploy output ends with a "Wire it into Claude Code / Codex" snippet. If `-AutoWire` / `--auto-wire` was used, the entry was already written. Otherwise tell the user to **paste that snippet under `mcpServers` in `~/.claude.json`** (Claude Code) or **as `[mcp_servers.sqlbroker]` in `~/.codex/config.toml`** (Codex), then restart their CLI (or `/reload-plugins` may be enough for Claude Code).

6. Once wired, suggest `/sqlbroker:add <alias>` to register the first DB connection.

## Optional flags (Windows)

`-InstallDir`, `-Port`, `-BindHost`, `-SkipOdbc`, `-SkipService`, `-AutoWire`, `-SkipMcpWire`, `-RefreshOnly`, `-Codex`. Pass them to `deploy.ps1` in the elevated window.

## Optional env vars (Unix)

`INSTALL_DIR`, `PORT`, `BIND_HOST`, `SERVICE_NAME`. Set them before invoking `sudo deploy.sh`. Flags: `--auto-wire`, `--skip-mcp-wire`, `--refresh-only`, `--codex`.

## Notes

- The deploy scripts do NOT touch existing `connections.json`, so re-running is safe.
- Passwords are AES-128-CBC + HMAC-SHA256 encrypted with `master.key` (32 random bytes generated at install). They are NOT in `connections.json` plaintext.
