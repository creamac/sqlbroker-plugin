# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A **dual-host marketplace + single-plugin repo** that ships `sqlbroker` — an alias-based MSSQL access layer for **Claude Code AND OpenAI Codex CLI**. The repo itself doesn't get "built" or "installed" directly; it's *served* by either CLI's plugin marketplace and the plugin's slash commands then *deploy* the broker source onto the host.

| Host | Marketplace install | MCP wiring file |
|---|---|---|
| Claude Code | `/plugin marketplace add creamac/sqlbroker-plugin` | `~/.claude.json` `mcpServers.sqlbroker` (JSON) |
| Codex CLI 0.124+ | `codex plugin marketplace add creamac/sqlbroker-plugin` | `~/.codex/config.toml` `[mcp_servers.sqlbroker]` (TOML) |

Both CLIs read **the same broker process and same MCP tool surface** — they differ only in (1) plugin manifest folder (`.claude-plugin/` vs `.codex-plugin/`), (2) marketplace location (`.claude-plugin/marketplace.json` vs `.agents/plugins/marketplace.json`), and (3) wiring file format (JSON vs TOML). Skills under `plugins/sqlbroker/skills/` (used by Codex) and commands under `plugins/sqlbroker/commands/` (used by Claude) carry **mirrored content** — a 1-line shim was attempted in v2.8 dev but reverted because Claude does NOT substitute `${CLAUDE_PLUGIN_ROOT}` in command bodies. Each file's frontmatter has a `Maintenance note:` cross-reference so a single edit catches both halves.

Two-tier mental model:

| Tier | Lives in | Role |
|---|---|---|
| **Plugin source** (this repo) | `D:\util\sqlbroker-plugin\plugins\sqlbroker\` | What you edit. Distributed via the marketplace. Includes skill, slash commands, and broker scripts. |
| **Deployed broker** (per host) | Win: `D:\util\mcp-sqlbroker\` · Unix: `/opt/mcp-sqlbroker/` | What actually runs as a service. Holds the **live** `connections.json` + `master.key`. |

**Core rule:** editing `plugins/sqlbroker/scripts/*.py` does NOT change anything until you redeploy. Run `/sqlbroker:update` (or `deploy.ps1 -RefreshOnly` / `deploy.sh --refresh-only`) to copy the new files into the install dir and bounce the service.

## Repo layout

```
.claude-plugin/marketplace.json      # Claude Code marketplace manifest
.agents/plugins/marketplace.json     # Codex CLI marketplace manifest (OpenAI convention — NOT .codex-plugin/)
.gitattributes                       # enforces *.sh/.py = LF, *.ps1/.bat = CRLF (cross-OS install integrity)
plugins/sqlbroker/
├── .claude-plugin/plugin.json       # Claude plugin manifest — version lives here
├── .codex-plugin/plugin.json        # Codex plugin manifest — must be bumped together with Claude's
├── skills/                          # Codex skill folder (auto-loaded by Codex)
│   ├── sqlbroker/SKILL.md           # auto-activating router skill (tool-pick cheatsheet, ops guide)
│   └── sqlbroker-{install,update,add,list,test,rotate,remove,status,diff}/SKILL.md
├── commands/                        # 9 Claude slash commands — MIRRORS skills/sqlbroker-*/SKILL.md content
│   ├── install.md update.md add.md  list.md test.md
│   ├── rotate.md  remove.md status.md diff.md
└── scripts/
    ├── server.py                    # HTTP MCP broker (~1400 lines, 14 tools, pool, Fernet AES)
    ├── manage_conn.py               # CLI: add/list/remove/test/rotate/migrate
    ├── stdio_proxy.py               # stdio→HTTP shim launched by Claude Code or Codex (pure stdlib)
    ├── run_stdio_proxy.{bat,sh}     # OS launchers for stdio_proxy.py
    ├── deploy.ps1                   # Windows installer — `-Codex` flag wires Codex CLI too
    ├── deploy.sh                    # Linux + macOS installer — `--codex` flag wires Codex CLI too
    ├── install-service.ps1          # LEGACY — old NSSM installer, superseded by deploy.ps1
    ├── option-b-rebuild.ps1         # LEGACY — NSSM rebuild path, superseded by deploy.ps1
    └── requirements.txt             # pyodbc, pycryptodome
```

The `install-service.ps1` and `option-b-rebuild.ps1` scripts are **NSSM-era leftovers**. They're not referenced by any current command or doc. Do not extend or recommend them — `deploy.ps1` is the only supported Windows installer. They're kept on disk only to avoid breaking anyone still pointing at them; safe to delete in a future cleanup.

## Architecture

```
Claude Code  ──stdio JSON-RPC──▶  run_stdio_proxy.{bat,sh}  →  stdio_proxy.py
                                                                    │
                                                                    │  HTTP POST /mcp
                                                                    ▼
                                                  mcp-sqlbroker (127.0.0.1:8765)
                                                  ├─ connections.json  (alias→host/user/policy/auth + password_enc)
                                                  ├─ master.key        (32 random bytes, generated at install)
                                                  ├─ Fernet AES-128-CBC + HMAC-SHA256 (pycryptodome)
                                                  ├─ policy regex (string-literal aware)
                                                  ├─ connection pool — per (alias,db), max 4, TTL 300s
                                                  └─ pyodbc → MSSQL (auth: SQL | Windows | AAD-SPN)
```

Key invariants:

- **`master.key` + `connections.json` together = the secret.** Threat model is "host is the trust boundary" — anyone who can read both files (or run code as the broker user) can decrypt every password. No network token, broker binds 127.0.0.1 only.
- **`connections.json` is re-read every request** — no service restart needed after `manage_conn.py` edits. (The pool's connections are pinged + state-reset on checkout, so removed/rotated aliases get refreshed.)
- **`stdio_proxy.py` is pure stdlib.** It must work without the broker's venv (Claude Code launches it directly). Don't add `pyodbc`/`pycryptodome` imports there.
- **Three auth modes** (`auth_mode` field per alias): `sql` (default, encrypted password), `windows` (Trusted_Connection — uses broker process identity), `aad-spn` (Azure AD service principal — requires ODBC 18+).
- **Three policies**: `readonly` (SELECT + sys only), `exec-only` (SELECT + EXEC), `full` (anything). Regex strips string literals + comments before matching so `SELECT '/* UPDATE */'` isn't false-blocked.

## Development workflow

There is no traditional build/test/lint pipeline — this is a Python service plus declarative manifests. Iteration loop:

1. **Edit** `plugins/sqlbroker/scripts/*.py` (or `skills/`, `commands/`).
2. **Redeploy** so the running broker picks up the change:
   ```powershell
   # Windows — auto-elevates
   /sqlbroker:update
   # or directly (admin shell):
   D:\util\sqlbroker-plugin\plugins\sqlbroker\scripts\deploy.ps1 -RefreshOnly -AutoWire
   ```
   ```bash
   # Linux / macOS
   sudo D:/util/sqlbroker-plugin/plugins/sqlbroker/scripts/deploy.sh --refresh-only
   ```
   `-RefreshOnly` skips Python/ODBC reinstall, just copies files + bounces the service. It pre-flight checks that the embedded Python still exists.
3. **Verify** the deployed broker reports the new version:
   ```bash
   curl -fsS http://127.0.0.1:8765/health
   curl -fsS -X POST http://127.0.0.1:8765/mcp -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
   ```
4. **Smoke-test** an alias:
   ```
   /sqlbroker:test <alias>
   ```
   or directly: `python manage_conn.py test <alias>` from the install dir.

There is **no test suite** (`pytest`, `unittest`, etc.) in the repo. Verification is empirical — run the broker, hit it, look at `service.log` / `service.err.log` in `<InstallDir>`.

For purely local manual runs without the service:

```powershell
# From the deployed install dir
D:\util\mcp-sqlbroker\python313\python.exe D:\util\mcp-sqlbroker\server.py
```

## Adding a new MCP tool

The tool registry is `TOOLS = { ... }` near line 1004 in `server.py`. To add a tool:

1. Write `def tool_<name>(args): ...` returning a JSON-serializable dict. Use the `pooled_connection(alias, database)` context manager, never `get_connection` directly.
2. Add an entry to `TOOLS` with `spec` (MCP `inputSchema`) and `fn` (the function).
3. Bump version: `SERVER_VERSION` in `server.py`, `version` in `plugins/sqlbroker/.claude-plugin/plugin.json`, `version` in `.claude-plugin/marketplace.json`. The `compatibility` between marketplace/plugin/broker version is checked nowhere — they just need to drift together so users can reason about what's deployed.
4. Document the tool in `skills/sqlbroker/SKILL.md` (the tool-pick cheatsheet table is what the skill uses to pick the right tool).
5. Redeploy via `/sqlbroker:update` and verify with a `tools/list` MCP call.

When the tool returns rows (`_coerce` helper handles type conversion for JSON output), prefer the column shape `{"columns": [...], "rows": [[...], ...]}` for consistency with `execute_sql`.

## Versioning

Five files carry the version string and **must be bumped together**:

- `.claude-plugin/marketplace.json` → `plugins[0].version`
- `.codex-plugin/marketplace.json` → `plugins[0].version`
- `plugins/sqlbroker/.claude-plugin/plugin.json` → `version`
- `plugins/sqlbroker/.codex-plugin/plugin.json` → `version`
- `plugins/sqlbroker/scripts/server.py` → `SERVER_VERSION`

Commit message convention from `git log`: `vX.Y.Z: <theme>` for feature releases, `vX.Y.Z hotfix-N: ...` for hotfixes, `docs: ...` for docs-only.

## Migration paths still in code

`server.py:_migrate_legacy()` runs on every config load and handles two stale formats. Keep these working unless you're certain no one is on those versions:

- **v1 → v2.3+**: `password_dpapi` field (Windows DPAPI blob) → re-encrypt with `master.key`. Needs `pywin32` (deploy.ps1 auto-installs it when it detects legacy aliases).
- **v2.0–2.2 → v2.3+**: aliases with no password field → pull from OS keyring, re-encrypt, delete keyring entry. Needs `keyring`. Service running as SYSTEM cannot read user keyring entries; this is the bug that drove the v2.3 rewrite.

If you remove either path, also remove the corresponding install-time installer in `deploy.ps1` (search `needPywin32` / `needKeyring`).

## Things to know before editing

- **Both Claude Code and Codex plugin manifests only accept stdio MCP servers.** That's why `stdio_proxy.py` exists as a shim in front of the HTTP broker. Don't try to wire the broker's HTTP endpoint directly into `~/.claude.json` or `~/.codex/config.toml`.
- **Slash commands use `${CLAUDE_PLUGIN_ROOT}`** to find the deploy scripts at runtime. When adding new commands that shell out, use that env var, not a hardcoded path. Codex skills do not get this variable substituted automatically — they assume the deployed paths (`D:\util\mcp-sqlbroker\` / `/opt/mcp-sqlbroker/`) which are stable post-`/sqlbroker-install`.
- **Install dir paths are duplicated** in `run_stdio_proxy.bat` (hardcoded fallbacks for `D:\util\mcp-sqlbroker`, `C:\util\mcp-sqlbroker`, `C:\apps\mcp-sqlbroker`) and `run_stdio_proxy.sh` (`/opt/mcp-sqlbroker/.venv/bin/python3`). If you change the default `InstallDir`, update both wrappers and `deploy.{ps1,sh}`.
- **Never accept passwords through chat or `--password` CLI args** — the user-facing flow always routes through `getpass` in the user's own terminal. The `sqlbroker-add` / `sqlbroker-rotate` skills enforce this; preserve that pattern.
- **Skills are the source of truth, commands are shims.** When updating an op (e.g. install flow changes), edit `skills/sqlbroker-<name>/SKILL.md`. The Claude command at `commands/<name>.md` is a 1-line `Read ${CLAUDE_PLUGIN_ROOT}/skills/...` instruction — it never carries content.
- **`-Codex` / `--codex` flag** on the deploy scripts wires `~/.codex/config.toml`. Tries `codex mcp add sqlbroker -- <wrapper>` first; falls back to direct TOML patch via Python + `tomli_w` if the Codex CLI isn't on PATH (common when running elevated and Codex was installed per-user via npm).
