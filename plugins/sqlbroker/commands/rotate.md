---
description: Rotate (replace) the password for an existing alias
argument-hint: <alias_name>
---

Rotate the password for alias `$ARGUMENTS` without re-entering host / user / db / policy.

> **Maintenance note:** canonical content also at `plugins/sqlbroker/skills/sqlbroker-rotate/SKILL.md`. Keep in sync.

## Flow

1. If `$ARGUMENTS` is empty, ask the user which alias to rotate (you can show `mcp__sqlbroker__list_aliases` first).

2. Verify the alias exists by calling `list_aliases` and checking it's in the list.

3. Tell the user to run this in their own terminal — the script prompts for the new password with `getpass` (hidden input):

   ```powershell
   D:\util\mcp-sqlbroker\python313\python.exe D:\util\mcp-sqlbroker\manage_conn.py rotate <alias>
   ```

   ```bash
   /opt/mcp-sqlbroker/.venv/bin/python3 /opt/mcp-sqlbroker/manage_conn.py rotate <alias>
   ```

4. After the user reports it ran successfully, verify with `/sqlbroker:test <alias>`.

## Notes

- DO NOT accept the new password via chat or `--password` flag — it would land in the transcript or shell history.
- `rotate` only touches `password_enc` for that one alias; all other fields stay.
- The broker re-reads `connections.json` on every request, so the change takes effect on the next query — no restart needed.
