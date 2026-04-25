---
description: Install the mcp-sqlbroker Windows service (auto-elevated)
---

Install or update the mcp-sqlbroker Windows service on this machine. The
deploy script downloads embedded Python, ODBC Driver 18 (if missing), and
NSSM, then registers an auto-starting service. It needs Administrator
rights — this command launches it elevated via UAC, so the user only has
to click "Yes" on the UAC dialog.

## Steps

1. Confirm OS is Windows. If not, stop and tell the user this plugin is Windows-only.

2. Locate the deploy script:

   ```powershell
   $deploy = Join-Path "${CLAUDE_PLUGIN_ROOT}" 'scripts\deploy.ps1'
   if (-not (Test-Path $deploy)) {
     # fallback: lookup via the plugin cache path
     $deploy = "$env:USERPROFILE\.claude\plugins\cache\sqlbroker-marketplace\sqlbroker\1.0.0\scripts\deploy.ps1"
   }
   ```

3. Tell the user a UAC dialog will pop up; the elevated PowerShell window will stream the install output and stay open after install (use `-NoExit`) so they can read it.

4. Launch deploy.ps1 elevated:

   ```powershell
   Start-Process powershell.exe -Verb RunAs -ArgumentList @(
     '-NoExit',
     '-NoProfile',
     '-ExecutionPolicy', 'Bypass',
     '-File', $deploy
   )
   ```

5. After the user reports the elevated window finished (or after 60s), run a health check from the regular shell:

   ```powershell
   try {
     $r = Invoke-WebRequest 'http://127.0.0.1:8765/health' -UseBasicParsing -TimeoutSec 5
     "Service health: $($r.Content)"
   } catch { "Health check failed: $_" }
   ```

6. If healthy, suggest the next step: `/sqlbroker:add <alias>` to register the first DB connection.

## What deploy.ps1 does (zero prerequisites)

- Downloads Python 3.13 embeddable distribution into `<InstallDir>\python313\` — no system Python needed.
- Bootstraps pip, installs `pyodbc` and `pywin32` from PyPI.
- Auto-installs **ODBC Driver 18 for SQL Server** if no compatible driver is detected.
- Auto-downloads **NSSM** if not on the machine.
- Copies server files, registers the NSSM service `mcp-sqlbroker` (LocalSystem, auto-start), and starts it.
- Health-checks `http://127.0.0.1:8765/health`.

## Optional flags

`-InstallDir`, `-Port`, `-BindHost`, `-NssmPath`, `-SkipOdbc`, `-SkipService`. Pass them to deploy.ps1 in the elevated window if needed.

## Notes

- The script does NOT touch existing `connections.json`, so re-running is safe.
- Passwords in `connections.json` are DPAPI-encrypted (LOCAL_MACHINE scope). Anyone with code-execution on this machine can decrypt — the trust boundary is the Windows host.
