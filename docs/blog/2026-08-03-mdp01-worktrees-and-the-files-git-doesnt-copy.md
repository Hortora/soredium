---
layout: post
title: "Worktrees and the files git doesn't copy"
date: 2026-08-03
type: phase-update
entry_type: note
subtype: diary
projects: [soredium]
tags: [ctx-py, git-worktrees]
---

Git worktrees share the object database with the main repo, but they get their
own working directory. That means untracked files — anything not committed — don't
exist in the worktree. The `proj/` and `wksp/` symlinks that ctx.py uses to find
the companion workspace are exactly this: untracked, excluded via
`.git/info/exclude`, invisible to every worktree.

The symptom was that every session in a worktree triggered the "No workspace
configured" prompt, even though the main repo had a perfectly good workspace
set up. ctx.py was looking for symlinks at `git rev-parse --show-toplevel` —
which returns the worktree root, not the main working tree.

The fix reads symlinks from the main working tree instead. The design question
was how to find that root. Two options: `git rev-parse --git-common-dir` (returns
the shared `.git` path — take its parent) or `git worktree list --porcelain`
(first entry is always the main working tree). I went with `worktree list` because
`--git-common-dir` assumes `.git`'s parent is the working tree root, which breaks
with `--separate-git-dir`. We don't use that, but the assumption felt unnecessary
when a direct answer was available.

The subtler decision was what `PROJECT` and `WORKSPACE` should mean in a worktree.
The worktree is where files live, where git operations target the branch, where
`.meta` and `JOURNAL.md` are checked out. It's the working repo. So `PROJECT`
stays as `cwd_root` (the worktree) — only the symlink *lookup location* changes
to the main root. The resolved companion repo is the same either way.

Two new output fields — `IN_WORKTREE` and `MAIN_WORKTREE_ROOT` — give downstream
skills the context they need. The IntelliJ MCP entries in the garden document a
whole class of "edits landed in the wrong project" bugs when worktrees are involved;
having the main root available should help skills pass the right `project_path`.

The open question is whether this pattern needs to extend further. ctx.py is the
path resolver, but `WORKSPACE_OK` (the fast-path check that decides whether to
offer workspace setup) had the same blind spot — it was checking for symlinks at
CWD, not the main root. Fixed in the same commit, but it's worth asking: how
many other CWD-relative checks across the skill ecosystem have the same assumption?
