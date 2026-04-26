---
description: List all configured SQL connection aliases
---

List all aliases configured on mcp-sqlbroker.

> **Maintenance note:** canonical content also at `plugins/sqlbroker/skills/sqlbroker-list/SKILL.md`. Keep in sync.

Prefer the MCP tool `mcp__sqlbroker__list_aliases` if available. Fall back to:

```powershell
# Windows
D:\util\mcp-sqlbroker\python313\python.exe D:\util\mcp-sqlbroker\manage_conn.py list
```

```bash
# Linux / macOS
/opt/mcp-sqlbroker/.venv/bin/python3 /opt/mcp-sqlbroker/manage_conn.py list
```

Show the output verbatim — do not redact aliases. Passwords are never returned (they live as `master.key`-encrypted blobs in `connections.json` under `password_enc`).
