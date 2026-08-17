# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Personal dotfiles repository installed by **Seshat**, an embedded, stateful, ownership-aware
installer (Python 3, lives entirely in this repo as `seshat` + `seshatlib/`). Bundles declare
what gets installed; Seshat tracks which bundle owns every file and JSON key in
`.seshat/state.yml` (gitignored, machine-local).

## Commands

```bash
./setup                              # legacy entry point == seshat install default --automatic
./seshat install [bundle]            # install default (implied) or an optional bundle
./seshat list [bundle] [--json]      # bundle states: not-installed/current/outdated/modified/missing/blocked/orphaned
./seshat remove <bundle> [--yes]     # remove an optional bundle (default cannot be removed)
```

The `seshat` launcher is a sh+python polyglot: it builds a throwaway virtualenv under
`.seshat/venv` (Jinja2 + PyYAML, pinned inline), re-executes itself inside it, and deletes the
venv on every exit path. Offline it falls back to the system python if the deps happen to be
importable.

Amun clones this repo to `~/.dotfiles` and runs `./setup`. Exit codes: 0 clean, 1 error,
2 blocked/unsafe (a target was locally modified or an unmanaged file is in the way — Seshat
never overwrites those).

## Running tests

```bash
python3 -m venv /tmp/venv && /tmp/venv/bin/pip install pytest Jinja2 PyYAML
/tmp/venv/bin/python -m pytest tests/
```

Tests always run against a temporary HOME (never the real one) and use local `file://` git
origins (no network).

## Architecture

### Bundles

- `bundles/default.yml` — universal baseline, installed automatically. Sources reference the
  existing top-level payload directories (`bashrc/`, `screenrc/`, `tmux.conf/`, `zshenv/`,
  `ideavimrc/`, `aider/`, `vscode/`, `claude/`, `iterm/`).
- `bundles/<bundle-id>/bundle.yml` + `files/` — optional bundles, installed deliberately
  (first one: `llm.claude.bedrock`, which owns `~/.claude/settings.json#/env` and requires
  `kauket get aws.profile.bedrock` at install time).
- Manifests are strict YAML (unknown fields are errors). Source paths are repo-root-relative.

### Operations

| Operation | Behavior |
|-----------|----------|
| `copy` | One file to one destination; whole-file ownership; optional `mode`, `variants` |
| `combine` | Concatenate regular files in a dir, sorted by name, `\n` after each fragment |
| `link` | Symlink at destination; `target:` is `~/...` or `repo:<path>` |
| `json_merge` | Own declared top-level keys (`owns: [/key]`) in a JSON object; unmanaged keys preserved |
| `git_tree` | Clone/fast-forward an external repo; whole-directory ownership; dirty repo blocks |

Targets support `when:` conditions on facts (`os`, `arch`, `user`, `hostname`) and `variants:`
(first match wins) instead of duplicate destinations. Templates (`template: jinja2`) render with
StrictUndefined and a restricted context (`vars`, `system.*`, `user.*`, `bundle.*`) — no
includes, no environment, no filesystem.

### Ownership rules

- Exactly one owner per managed file or JSON key.
- A default install skips anything owned by an optional bundle (whole files and JSON keys).
- Optional bundles may take over a default target only via explicit `replaces: [default]`;
  removing the bundle restores current default content.
- Locally modified managed content is never overwritten or removed — it blocks (exit 2).
- With no state (fresh machine or state loss), exact matches are adopted; differing content
  blocks. Nothing is ever destructively replaced.

### seshatlib modules

`cli.py` (pipeline orchestration) → `planner.py` (classification → actions, list states,
remove planning) / `installer.py` (staging, validators, path safety, journaled transactions
with rollback + recovery) → `manifest.py` (strict parsing, facts, variants, source digest),
`ownership.py` (pure classifiers), `state.py` (atomic state + lock), `templates.py` (Jinja
sandbox), `providers.py` (kauket + git subprocess), `output.py` (reporter).

Every install re-renders everything to `.seshat/staging/` first, plans against state + the real
filesystem, then applies through a fsynced journal in `.seshat/transactions/<id>/` (backup →
temp file → `os.replace` → verify hash/mode). A crash mid-apply is rolled back on the next run;
an unrecoverable rollback refuses further operations until resolved. State is written last,
atomically, with a `.bak` of the previous version.

`current` vs `outdated` is decided by a per-bundle **source digest** (manifest + payload bytes
of facts-active targets), so unrelated repo changes never mark a bundle outdated. Bundle
variables (nonsecret only) are remembered in state; secrets never touch state or templates —
Kauket installs them directly (e.g. AWS profiles into `~/.aws`).

## Conventions

### bashrc/ Directory

Files are numbered (000-999) for concatenation order:
- `000Header.sh` - Shebang
- `2xx` - Variables, PS1, functions
- `3xx` - Environment variables
- `4xx` - Aliases
- `5xx` - History settings
- `6xx` - Completions
- `7xx` - Includes

### Agent-Friendly Shell

The bashrc detects AI coding agents (Claude Code, Cursor) via environment variables and switches
to a simplified PS1, skipping interactive-only configuration. See `__bashrc_lite_mode()` in
`bashrc/300Variables.sh`.

### zshenv Behavior

The zshenv sets up PATH and redirects interactive zsh sessions to bash (`exec bash -l`).
Non-interactive shells are unaffected.

### Unmanaged payload directories

`obsidian/`, `conky/`, `nvim/init.lua`, and `iterm/iTerm - Black Beast.json` exist in the repo
but are deliberately **not** installed by any bundle. Only manifest declarations create
ownership. `~/.config/nvim` is wholly owned by the external `GonzaloAlvarez/nvim` repository
(the old `nvim/init.lua` copy was shadowed by that clone and has been dropped).

## Operational notes

- One authoritative checkout per machine: state lives in `<repo>/.seshat/`, so a second
  checkout has its own empty state (it will adopt identical files and block on divergent ones).
- The iTerm dynamic profile (`iterm/Profiles.json` → `~/Library/Application
  Support/iTerm2/DynamicProfiles/BlackBeast.json`) is Seshat-owned as of this migration. Amun
  still copies the same bytes from the same source until its role is updated — byte-identical,
  so no drift is reported.
- Amun follow-ups (in the amun repo, not here): drop `failed_when: false` from
  `roles/dotfiles/tasks/main.yml` so Seshat failures surface (treat exit 2 as a failure), and
  remove the iTerm copy task from `roles/dotfiles/tasks/osx_iterm.yml` (keep the osx_defaults
  default-profile GUID task).
