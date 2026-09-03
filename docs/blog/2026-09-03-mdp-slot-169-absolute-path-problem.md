---
title: Slot 169 and the absolute path problem
date: 2026-09-03
entry_type: note
subtype: diary
projects: Hortora/soredium
series: issue-328-fix-absolute-paths
tags: [slots, isolation, infrastructure, workspace-init]
---

## Slot 169 and the absolute path problem

Slot 169 committed to the shared casehub repos instead of its own clones. The whole point of slots is isolation — giving a session its own copies so other sessions can't stomp on the same branches mid-work. And the slot infrastructure did its job: symlinks were correctly repointed, topology resolution worked, ctx.py gave the right paths. But the session followed the instructions in CLAUDE.md instead.

The workspace CLAUDE.md said `add-dir /Users/mdproctor/claude/casehub/work` and `**Project repo:** /Users/mdproctor/claude/casehub/work` — absolute paths pointing to the shared repos, not the slot clones. The session obeyed those instructions, mounted the shared repos as working directories, opened IntelliJ with the shared paths, and committed there. The symlink isolation was bypassed entirely because CLAUDE.md told the session to go somewhere else.

### The root cause was workspace-init

The workspace-init template generated absolute paths by design. Every `add-dir`, every `**Project repo:**` field, every `git -C` example — all used `<absolute-path-to-project>`. Every workspace created from this template inherited the problem. Nine workspace CLAUDE.md files across casehub, hortora, and standalone repos had absolute paths baked in.

The fix replaced the template with the `proj/`/`wksp/` convention. These symlinks are the indirection layer that gets repointed per-context — in a slot, `proj/` points to the slot clone, so any path that goes through `proj/` automatically resolves to the right place. The engine workspace already used this convention. The rest didn't.

### A second bug hiding behind the first

While fixing the template, I traced a second issue (#329): `close_artifacts.py` failed in slots because topology couldn't find the workspace. The project clone `casehub/work` had `proj -> .` — a self-referencing symlink. Topology checks `proj` before `wksp` (an elif), so it treated the directory as both project and workspace simultaneously, never finding the actual workspace clone.

The fix: topology now detects self-referencing `proj` symlinks and falls through to `wksp`. Defence-in-depth: `close_artifacts.py` resolves its paths to git roots before operating.

### Structural integrity checks

The investigation made clear that detecting corruption after the fact wasn't enough. I added two new checks to the corruption detection system that runs at every session start:

**S10 — Symlink round-trip.** Does `workspace/proj` → project and `project/wksp` → back to the same workspace? If not, the pointers are crossed — engine's workspace pointing to work's project, for instance. This was a recurring problem before.

**S11 — Slot boundary.** Are all resolved paths inside the slot directory? If not, the session has escaped isolation. This would have caught slot 169 immediately.

Both checks now gate every lifecycle entry point — work-start, work-end, git-commit, work-pause, work-resume, handover. Previously only the `work` router checked corruption; the other entry points ran ctx.py but never looked at the results. Work-end and git-commit were the highest-risk gaps — those are where commits, merges, and pushes happen.

### What's left

The audit Claude is fixing the nine existing workspace CLAUDE.md files and converting the 55 absolute symlinks across all repos. The soredium changes (template, validation, topology, corruption checks) are landed. New workspaces will generate correct relative paths. Existing slots will warn at creation time if they inherit stale CLAUDE.md content.
