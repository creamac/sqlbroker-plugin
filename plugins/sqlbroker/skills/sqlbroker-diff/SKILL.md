---
name: sqlbroker-diff
description: Diff the source code (CREATE statement) of a proc/view/function across two aliases (or two databases on the same alias). Triggers on "/sqlbroker-diff", "/sqlbroker:diff", "compare proc across environments", "diff usp_X between staging and prod", "is proc X same on prod and dev".
---

# Diff an object across two environments

Compare the CREATE statement of an object on two different environments. Args: `$ARGUMENTS` (Claude) or `$1 $2 $3` (Codex) — expected `<alias_a> <alias_b> <object_name>` (3 tokens).

## Steps

1. Parse the args into three tokens. If fewer, ask the user for the missing pieces:
   - **alias_a** (e.g. `prod_main`)
   - **alias_b** (e.g. `staging_main`)
   - **object_name** (e.g. `dbo.usp_FsData_Admin_FinancialData_Approve_Workflow` or `t_orders`)

2. Optionally let the user override `database_a` / `database_b` if the alias's default isn't right.

3. Call the MCP tool:

   ```
   mcp__sqlbroker__compare_definitions(
       alias_a=<alias_a>, alias_b=<alias_b>, object_name=<object_name>,
       database_a=<optional>, database_b=<optional>
   )
   ```

4. Render the result:
   - If `match: true` → "✅ identical on `<alias_a>` and `<alias_b>`"
   - If `match: false` → show the unified diff in a fenced ` ```diff ` block; if `truncated: true`, say so and offer to fetch full definitions via `get_definition` for both aliases.
   - If one side is missing → say "Object missing on `<alias_a>`" / `alias_b`, and suggest `list_objects` to find the right name.

## When to use

- Before deploying a proc to prod: confirm staging matches what you tested
- Audit drift: "did anyone hand-edit usp_X on prod?"
- Cherry-pick: "what changed in usp_Y between dev and uat?"

## Notes

- The diff is computed on the broker side using Python's `difflib.unified_diff`.
- Both aliases must be reachable when this runs (otherwise the tool returns `definition_a_present` / `definition_b_present` flags).
- Encrypted procs (sp_helptext returning NULL) show as missing — same as `get_definition`.
