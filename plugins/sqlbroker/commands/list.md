---
description: List all configured SQL connection aliases
---

List all aliases configured on mcp-sqlbroker.

Prefer the MCP tool `mcp__sqlbroker__list_aliases` if available. Fall back to:

```powershell
D:\util\mcp-sqlbroker\.venv\Scripts\python.exe D:\util\mcp-sqlbroker\manage_conn.py list
```

Show the output verbatim — do not redact aliases. Passwords are never returned (they live as DPAPI-encrypted blobs in `connections.json`).
