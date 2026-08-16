---
layout: post
title: "The File That Moved Six Times"
date: 2026-08-16
entry_type: note
subtype: diary
projects: [soredium]
tags: [migration, lifecycle, work-end, debugging]
---

When `.plan` was at `design/.plan`, every new script that needed to read it implemented its own path resolution. When we moved it to workspace root, we broke every one of them. The migration itself was trivial — `src.rename(dst)`, done. The hard part was finding all the places that assumed the old path, and the harder part was stopping ourselves from creating new assumptions while fixing the old ones.

The original issue was simpler: work-end wasn't closing GitHub issues. Claude would say "done" but never run `gh issue close`. The fix was mechanical — a `close-issues` subcommand in `work_end_execute.py` and a verification check in `verify_slot_close.py` that confirms the issues are actually CLOSED before work-end can proceed. That took twenty minutes. The `.plan` migration took the rest of the session.

The `.plan` file started life inside a `design/` subdirectory because that's where the workspace scaffold put it. Reasonable at the time — group scaffold artifacts together. The problem surfaced in the casehub/engine workspace: scaffold commits landed on workspace main instead of the feature branch, spec files were never committed, and work-end couldn't find the `.plan` because it was looking in the wrong place relative to the wrong branch. Three different bugs, one root cause — the `design/` indirection created enough ambiguity that both scripts and Claude sessions made path errors.

The fix had three phases and each one exposed the next.

Phase one was a `migrate_to_root()` function in `plan_migrate.py` that moves files from `design/` to workspace root. We wired it into `ctx.py` so it runs once at session entry — every lifecycle path (start, continue, next, end, pause, resume) calls `ctx.py` first, so migration happens exactly once, before anything else reads the files. After migration, all downstream code reads from root only. No fallbacks.

That last sentence was aspirational. Phase two was a multi-agent audit that found we'd left fallbacks scattered everywhere — `pre_push_hook.py` only searched for `.meta` (completely bypassing lifecycle gates for any branch created after the unification), `branch_recon.py` read `JOURNAL.md` from `design/` only, the `commands/` layer had its own hardcoded paths, and `.pause-stack` was split between root (commands) and `design/` (scripts). The audit caught the architecture, but each fix touched new files that weren't in the original scope.

Phase three was the patch-regression check. We'd fixed so many files iteratively that the fixes themselves introduced inconsistencies: `work_end_context.py` runs as a standalone subprocess and never called `migrate_to_root()` because it doesn't go through `ctx.py`. `slot_manager.py` was reading `.artifacts-promoted` from `design/` while `close_artifacts.py` was writing it to root. Test fixtures were creating `design/.meta` while production code expected root `.plan`.

The pattern that keeps recurring: a migration that's easy to implement but hard to complete. The function that moves files is ten lines. Finding every consumer of those files is the real work — and you keep finding them. The pre-push hook. The pause/resume stack. A CLI command you forgot existed. A test fixture that sets up old-format state. Each discovery is individually trivial, but the aggregate is what makes migrations dangerous.

The defence-in-depth approach — run migration early, make all reads root-only, verify with independent auditors — caught everything eventually. But "eventually" was four audit passes before convergence. The uncomfortable question is whether a ground-up rewrite of the path resolution to use a single `find_state_file()` function everywhere would have been faster than the incremental fix-and-verify cycle. Probably not for this session, but it's the kind of structural investment that prevents the next migration from having the same blast radius.
