---
name: using-git-worktrees
description: Use when starting feature work that needs isolation from current workspace or before executing implementation plans - ensures an isolated workspace exists via native tools or git worktree fallback
---

# Using Git Worktrees

## Overview

Ensure work happens in an isolated workspace. Prefer your platform's
native worktree tools. Fall back to manual git worktrees only when no
native tool is available.

**Core principle:** Detect existing isolation first. Then use native
tools. Then fall back to git. Never fight the harness.

**Announce at start:** "I'm using the using-git-worktrees skill to set
up an isolated workspace."

## Distinction from workspace-init

Two workspace concepts exist — they are orthogonal:

| | `workspace-init` | `using-git-worktrees` |
|---|---|---|
| **Creates** | Companion methodology workspace (`~/claude/private/<project>/`) | Isolated git worktree for a feature branch (`.worktrees/<branch>`) |
| **Purpose** | Plans, specs, handovers, blog entries — methodology artifacts | Code isolation — protect current branch from changes |
| **Lifecycle** | One-time setup, persists across branches | Per-branch, cleaned up when work is done |

## Step 0: Detect Existing Isolation

**Before creating anything, check if you are already in an isolated
workspace.**

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
BRANCH=$(git branch --show-current)
```

**Submodule guard:** `GIT_DIR != GIT_COMMON` is also true inside git
submodules. Before concluding "already in a worktree," verify you are
not in a submodule:

```bash
git rev-parse --show-superproject-working-tree 2>/dev/null
```

**If `GIT_DIR != GIT_COMMON` (and not a submodule):** You are already
in a linked worktree. Skip to Step 2 (Project Setup). Do NOT create
another worktree.

Report with branch state:
- On a branch: "Already in isolated workspace at `<path>` on branch
  `<name>`."
- Detached HEAD: "Already in isolated workspace at `<path>` (detached
  HEAD, externally managed). Branch creation needed at finish time."

**If `GIT_DIR == GIT_COMMON` (or in a submodule):** You are in a normal
repo checkout.

Has the user already indicated their worktree preference in your
instructions? If not, ask for consent before creating a worktree:

> "Would you like me to set up an isolated worktree? It protects your
> current branch from changes."

Honor any existing declared preference without asking. If the user
declines consent, work in place and skip to Step 2.

## Step 1: Create Isolated Workspace

**You have two mechanisms. Try them in this order.**

### 1a. Native Worktree Tools (preferred)

The user has asked for an isolated workspace (Step 0 consent). Do you
already have a way to create a worktree? It might be a tool with a name
like `EnterWorktree`, `WorktreeCreate`, a `/worktree` command, or a
`--worktree` flag. If you do, use it and skip to Step 2.

Native tools handle directory placement, branch creation, and cleanup
automatically. Using `git worktree add` when you have a native tool
creates phantom state your harness can't see or manage.

Only proceed to Step 1b if you have no native worktree tool available.

### 1b. Git Worktree Fallback

**Only use this if Step 1a does not apply.**

#### Directory Selection

Follow this priority order. Explicit user preference always beats
observed filesystem state.

1. **Check your instructions for a declared worktree directory
   preference.** If the user has already specified one, use it without
   asking.

2. **Check for an existing project-local worktree directory:**
   ```bash
   ls -d .worktrees 2>/dev/null     # Preferred (hidden)
   ls -d worktrees 2>/dev/null      # Alternative
   ```
   If found, use it. If both exist, `.worktrees` wins.

3. **If there is no other guidance available**, default to `.worktrees/`
   at the project root.

#### Safety Verification (project-local directories only)

**MUST verify directory is ignored before creating worktree:**

```bash
git check-ignore -q .worktrees 2>/dev/null || \
  git check-ignore -q worktrees 2>/dev/null
```

**If NOT ignored:** Add to .gitignore, commit the change, then proceed.

#### Create the Worktree

```bash
path="$LOCATION/$BRANCH_NAME"
git worktree add "$path" -b "$BRANCH_NAME"
cd "$path"
```

**Sandbox fallback:** If `git worktree add` fails with a permission
error (sandbox denial), tell the user the sandbox blocked worktree
creation and you're working in the current directory instead.

## Step 2: Project Setup

Auto-detect and run appropriate setup:

```bash
# Node.js
if [ -f package.json ]; then npm install; fi

# Rust
if [ -f Cargo.toml ]; then cargo build; fi

# Python
if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
if [ -f pyproject.toml ]; then poetry install; fi

# Go
if [ -f go.mod ]; then go mod download; fi
```

## Step 3: Verify Clean Baseline

Run tests to ensure workspace starts clean:

```bash
# Use project-appropriate command
npm test / cargo test / pytest / go test ./...
```

**If tests fail:** Report failures, ask whether to proceed or
investigate.

**If tests pass:** Report ready.

```
Worktree ready at <full-path>
Tests passing (<N> tests, 0 failures)
Ready to implement <feature-name>
```

## Quick Reference

| Situation | Action |
|-----------|--------|
| Already in linked worktree | Skip creation (Step 0) |
| In a submodule | Treat as normal repo (Step 0 guard) |
| Native worktree tool available | Use it (Step 1a) |
| No native tool | Git worktree fallback (Step 1b) |
| `.worktrees/` exists | Use it (verify ignored) |
| `worktrees/` exists | Use it (verify ignored) |
| Both exist | Use `.worktrees/` |
| Neither exists | Check instructions, then default `.worktrees/` |
| Directory not ignored | Add to .gitignore + commit |
| Permission error on create | Sandbox fallback, work in place |
| Tests fail during baseline | Report failures + ask |

## Red Flags

**Never:**
- Create a worktree when Step 0 detects existing isolation
- Use `git worktree add` when you have a native worktree tool (e.g.,
  `EnterWorktree`) — this is the #1 mistake
- Skip Step 1a by jumping straight to Step 1b's git commands
- Create worktree without verifying it's ignored (project-local)
- Skip baseline test verification
- Proceed with failing tests without asking

## Skill Chaining

**Invoked by:**
- `subagent-driven-development` — ensures isolated workspace for
  execution

**Complements:**
- `work-start` — work-start creates branches; worktree isolation is
  an additional layer when uncommitted work needs protecting
- `workspace-init` — different concept. workspace-init creates the
  companion methodology workspace. This skill creates git worktree
  isolation. They are orthogonal.
- `work-end` — worktree cleanup happens during branch closure
  (provenance-based: only clean up worktrees created by the tool,
  under `.worktrees/`).
