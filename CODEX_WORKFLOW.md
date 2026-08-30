# Native Codex setup and rollback

This repository uses project-scoped Codex configuration. Sol remains the
decision-making and integration agent; bounded exploration and implementation
may be delegated to Luna, with Terra available for independent review.

## Installed files

- `.codex/config.toml`
- `.codex/agents/luna_implementer.toml`
- `.codex/agents/luna_explorer.toml`
- `.codex/agents/terra_reviewer.toml`
- `AGENTS.md`

The setup does not modify `~/.codex/config.toml`. Restart Codex after changing
these files so a new session reloads them.

Verify without starting project work:

```sh
codex doctor --summary --ascii --no-color
codex debug prompt-input "configuration verification only"
```

The doctor must report a loaded configuration with no failure. The prompt-input
result must contain the `Shengji agent workflow` instructions from `AGENTS.md`.

## Temporarily disable

Move both discovery entry points, then restart Codex:

```sh
mv .codex .codex.disabled
mv AGENTS.md AGENTS.md.disabled
```

Reverse those moves and restart to re-enable them.

## Permanently undo

If committed, remove only the setup-owned paths:

```sh
git rm -r -- .codex
git rm -- AGENTS.md CODEX_WORKFLOW.md
```

If uncommitted, remove the same exact paths rather than using a broad cleanup
command. The repository then inherits the unchanged user-level Codex defaults.
