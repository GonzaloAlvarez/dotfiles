# dotfiles

Finally, my own dotfiles.

Installed and managed by **Seshat**, the stateful, ownership-aware installer embedded in this
repository.

## Install

```console
cd ~/.dotfiles
./setup
```

`./setup` installs the universal baseline (the `default` bundle) without prompting. It is the
entry point Amun uses and is safe to re-run at any time: Seshat tracks which bundle owns every
installed file and JSON key, adopts files that already match, and refuses to overwrite anything
you changed locally.

## Optional bundles

```console
seshat list                          # every bundle and its state
seshat install llm.client            # Claude Code + qwen-code → the homelab LLM router
seshat install llm.client --set local_host=127.0.0.1   # … plus direct entries for this machine's llama-server
seshat list llm.client               # per-target ownership detail
seshat remove llm.client             # remove it, restoring default-owned content
```

A later `./setup` never overwrites optional-bundle configuration: `~/.claude/settings.json#/env`
stays owned by `llm.client` while `#/statusLine` follows the default bundle.

## Layout

- `bundles/default.yml` — the baseline bundle manifest; payload directories (`bashrc/`,
  `tmux.conf/`, `claude/`, …) stay at the repository root.
- `bundles/<bundle-id>/` — one directory per optional bundle (`bundle.yml` + `files/`).
- `seshat` + `seshatlib/` — the installer engine (Python, bootstrapped into a throwaway venv).
- `.seshat/` — machine-local state (gitignored): `state.yml`, transaction journals, staging.

See `CLAUDE.md` for the full engine reference.
