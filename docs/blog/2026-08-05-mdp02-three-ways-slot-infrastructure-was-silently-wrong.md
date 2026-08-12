---
layout: post
title: "Three ways slot infrastructure was silently wrong"
date: 2026-08-05
type: phase-update
entry_type: note
subtype: diary
projects: [soredium]
tags: [slot-infrastructure, maven, merge-safety, handoff]
---

## Three ways slot infrastructure was silently wrong

Maven's `.mvn/maven.config` parser splits on whitespace. So `-s /path/to/settings.xml` becomes two tokens — the flag and the path — and the path goes through a resolver that prepends the project basedir with a literal space separator. The resulting path looks like `/Users/me/project/ /Users/me/settings.xml`. The error message says "The specified user settings file does not exist" and the file very much does exist.

I'd been seeing slots jump around — builds failing with path errors that made no sense given the file was right there. The root cause wasn't the path. It was Maven's config file parser treating `-s value` differently from `--settings=value`. The equals form keeps flag and value as a single token, bypassing the broken resolver entirely.

The fix in `slot_manager.py` was straightforward: switch from `-s /absolute/path` to `--settings=.mvn/slot-settings.xml`, copy the settings file into each repo's `.mvn/` directory so the path stays short and relative, and auto-fix any legacy `-s` lines in existing configs. We patched all nine active slots in place.

But the settings bug was only the most visible problem. Two others had been quietly wrong for longer.

`merge_slot()` — the function that lands slot work back into the original repos — had no preflight check. It would resolve the original repo, run `git rebase origin/main`, then `git merge --ff-only <branch>` — on whatever branch happened to be checked out. If the original was on a feature branch instead of main, the slot's work got merged into the wrong branch. Silently. No error, no warning. The `--ff-only` flag might catch it if the histories diverged enough, but for a fast-forward-compatible branch it would just succeed and corrupt the target.

We added a preflight stage that checks every original repo before touching anything. Is it on main? Is the working tree clean? If any repo fails, none gets merged — all-or-nothing. The error output names the offending repo, its current branch, and the path, so there's something actionable to fix.

The third bug was in `work_router.py`. The handover skill commits `HANDOFF.md` to workspace main — that's where it belongs, since it's a session artifact, not a branch artifact. But `work_router.py` was checking for it with `.exists()` on the filesystem. When the workspace is on a feature branch, `HANDOFF.md` isn't in the working tree. `.exists()` returns False. The router reports `HAS_HANDOFF=no` and the next session starts cold, missing context that's right there in the git history.

The irony is that the function that actually reads the handoff — `_handoff_references_branch` — already uses `git show main:HANDOFF.md`. The right approach was ten lines above the wrong one. The fix was a `git cat-file -e main:<filename>` check with a `.exists()` fallback for non-git workspaces.

Three bugs, three places where the infrastructure was silently doing the wrong thing. The Maven one at least produced an error message, even if it was misleading. The other two just succeeded — merging into wrong branches, losing handoff context — with no indication anything was wrong. The pattern is familiar: the failure mode that produces an error gets fixed fast; the one that succeeds quietly can run for months.
