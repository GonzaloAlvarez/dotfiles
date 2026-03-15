# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Personal dotfiles repository that uses a Python-based setup script to deploy configuration files to their target locations.

## Running Setup

```bash
./setup
```

The setup script is a polyglot (shell + Python). It auto-detects Python, creates a virtualenv, installs dependencies (paramiko, dulwich), and re-executes itself in the venv. The venv is deleted after completion.

## Architecture

### config.json

Central configuration file defining all deployment operations. Each entry specifies:
- `source`: Local path or git URL
- `dest`: Target path (supports `~` expansion)
- `mode`: Operation type
- `if` (optional): Conditional execution

### Deployment Modes

| Mode | Behavior |
|------|----------|
| `copy` | Direct file copy (default if mode omitted) |
| `combine` | Concatenate all files in source directory, sorted by filename |
| `link` | Create symlink from dest to source |
| `json_merge` | Merge source JSON keys into dest JSON file |
| `git` | Clone repository (removes existing dest first) |

### Conditionals

Format: `"if": "<type> == <value>"`
- `user == galvarez` - Match current username
- `os == darwin` - Match OS platform (darwin, linux, etc.)

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

The bashrc detects AI coding agents (Claude Code, Cursor) via environment variables and switches to a simplified PS1, skipping interactive-only configuration. See `__bashrc_lite_mode()` in `bashrc/300Variables.sh`.

### zshenv Behavior

The zshenv sets up PATH and redirects interactive zsh sessions to bash (`exec bash -l`). Non-interactive shells are unaffected.
