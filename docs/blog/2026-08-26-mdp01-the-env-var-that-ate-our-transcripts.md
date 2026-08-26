---
layout: post
title: "The env var that ate our transcripts"
date: 2026-08-26
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [slots, workspace-discovery, durability, claude-code, debugging]
series: issue-297-primary-no-workspace
---

# The env var that ate our transcripts

Two slot infrastructure bugs and one mystery that turned out to be hiding in the terminal emulator's process environment.

## Slots without workspaces

Slot 160 was created for an engine epic. Three repos cloned — blocks and qhorus both got workspace clones, engine didn't. The primary repo, the one that owns the `.plan`, had no workspace. Every session in that slot thought there was no active work.

The root cause was straightforward: `resolve_workspace_source()` follows the `wksp` symlink on the original repo. If the symlink is missing, it returns None, and `create_slot` silently skips the workspace clone. For secondary repos that's acceptable — not every repo needs a workspace. For the primary repo it's catastrophic.

The fix has two parts. A `discover_workspace()` fallback searches for the workspace by checking `~/claude/public/<family>/<repo>/` and scanning sibling directories for `proj` symlinks that point back to the repo. If discovery also fails for the primary, `create_slot` now raises a hard error instead of continuing into a broken state. The warning-and-continue approach was the original bug — a slot without a primary workspace is not a degraded slot, it's a broken one.

## Unpushed commits in clone-only storage

A separate incident on slot 158 exposed a worse problem: nine commits across two repos lost when a Maven build destroyed the slot directory. The `git-commit` skill explicitly suppressed pushes in slot mode — the reasoning was that commits accumulate locally until work-end squashes and pushes. Sound logic, except that `git clone --shared` stores new objects only in the clone's `.git/objects/`. Destroy the clone, destroy the commits. No recovery.

The fix reversed the rule entirely. A `post-commit` hook in every slot clone now pushes to origin after each commit. The git-commit skill went from "never push in slots" to "always push". Work-end squashes branch history before the final merge regardless of push state, so pushed WIP commits are harmless.

## The transcript mystery

The more interesting problem emerged when we noticed that slot sessions weren't saving transcripts. `/resume` showed nothing. Session directories existed in `~/.claude/projects/` with subagent metadata and tool results, but no `.jsonl` transcript files. Working sessions on the same machine — same Claude Code version, same time — saved fine.

Claude went down the `CLAUDE_CODE_CHILD_SESSION` path first. Running `env | grep CLAUDE` from inside a session shows the variable set to `1`. The natural conclusion: this session is marked as a child, child sessions don't save transcripts, find where the variable is being set and remove it. Except the variable appears in *every* Claude Code session — Claude sets it for all subprocess environments. Its presence in `env` output is completely normal and tells you nothing about whether the session itself is a child.

I checked shell configs, settings.json, hooks, shell snapshots, tmux, the daemon — nothing. Process ancestry showed Terminal.app → login → zsh → claude, no Claude parent anywhere in the chain.

The break came from checking the other terminal. The slots run in iTerm2. Its process — PID, parent is launchd — had `CLAUDE_CODE_CHILD_SESSION=1` in its own environment. At some point iTerm2 was relaunched from a context where the variable was present, picked it up, and from that moment every shell it spawned inherited it. Every Claude Code session launched from those shells detected the variable on startup, classified itself as a child session, and never wrote a transcript.

The fix: `unset CLAUDE_CODE_CHILD_SESSION` in `.zshrc`. Defense-in-depth — strips the variable from every new shell regardless of how the terminal was launched. Restarting iTerm2 from Spotlight gives it a clean environment too, but the `unset` handles future recontamination.

Past sessions from contaminated terminals are gone — they were never written to disk. But the diagnostic is worth the price. The red herring — seeing the variable in `env` and assuming it's the cause — would catch most people. The variable is designed to prevent recursive Claude launches, not to control transcript saving, but the side effect is invisible until you notice `/resume` returning nothing.
