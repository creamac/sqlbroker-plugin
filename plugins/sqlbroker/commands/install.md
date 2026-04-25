---
description: Install the mcp-sqlbroker Windows service on this machine
---

Install or update the mcp-sqlbroker Windows service on this machine.

## Steps

1. Confirm OS is Windows. If not, stop and tell the user this plugin is Windows-only for now.
2. Check that `python` is on PATH. Verify it is **not** the Microsoft Store stub (path under `WindowsApps`). If it is the Store version, warn the user that the service may fail under LocalSystem and recommend installing Python from python.org first (or running `${CLAUDE_PLUGIN_ROOT}/scripts/option-b-rebuild.ps1` after deploy).
3. Check NSSM exists. Default search: `D:\util\nssm.exe`, `C:\util\nssm.exe`, `C:\Program Files\nssm\nssm.exe`, or anywhere on PATH. If missing, ask the user to install NSSM (https://nssm.cc/download) and abort.
4. Tell the user this script registers a Windows service and will need to run in an Administrator PowerShell. Show them the exact command:

   ```powershell
   ${CLAUDE_PLUGIN_ROOT}\scripts\deploy.ps1
   ```

   Optional flags: `-InstallDir`, `-NssmPath`, `-Port`, `-BindHost`, `-SkipService`.

5. After they run it, check `http://127.0.0.1:8765/health` — expect `{"ok":true,"server":"sqlbroker"}`.
6. Suggest next: `/sqlbroker:add <alias>` to register the first DB connection.

## Notes

- The deploy script copies `server.py`, `manage_conn.py`, `requirements.txt` to the install dir, creates a venv, installs `pyodbc` + `pywin32`, and registers an NSSM service auto-starting at boot.
- The script does NOT touch existing `connections.json`, so re-running is safe.
- `connections.json` is written next to `server.py` and stores DPAPI-encrypted passwords (LOCAL_MACHINE scope). Anyone with code-execution on this machine can decrypt — the trust boundary is the Windows host.
