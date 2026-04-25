# sqlbroker-marketplace

Claude Code plugins for managing local MSSQL access without ever putting credentials in the conversation.

## Plugins

### sqlbroker

Alias-based MSSQL broker on Windows. A local NSSM-managed service holds DPAPI-encrypted passwords; Claude calls by alias.

- Auto-activating skill on any DB-query intent
- Slash commands for install / add / list / test / remove / status
- MCP server registration baked in
- Three policies: `readonly` / `exec-only` / `full`

→ See [`plugins/sqlbroker/README.md`](plugins/sqlbroker/README.md)

## Install

```
/plugin marketplace add <git-url-of-this-repo>
/plugin install sqlbroker
```

After install:

```
/sqlbroker:install        # one-time service registration (admin)
/sqlbroker:add prod_main  # add your first alias
```

## License

MIT
