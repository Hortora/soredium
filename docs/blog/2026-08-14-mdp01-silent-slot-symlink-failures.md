---
layout: post
title: "The Silent Failure That Made Slots Run Blind"
date: 2026-08-14
entry_type: note
subtype: diary
projects: [soredium]
tags: [slots, symlinks, validation, silent-failures]
---

The slot system has a workspace clone for each slot — a `wksp/` symlink that connects each repo clone back to its workspace. When it works, ctx.py detects the workspace, handoffs go to the right place, and session state flows naturally. When it breaks, the slot runs as `SINGLE_REPO=yes` — no workspace, no handoffs, no design artifacts. No error. No warning. Just a session that silently drops half its capabilities.

Five slots were running like this. I found them by accident.

The root cause was `resolve_workspace_source()`, which returns `"work"` as the default workspace clone name. The collision check only looked at the repos in the current slot — not all repos in the family. If the family had a repo called `work` (which casehub does), the workspace clone landed on top of it. After that, `add_repo("work")` would fail with `repo_already_in_slot` because the directory existed — but it was the workspace, not the repo.

The second problem was downstream. When `git clone --shared` creates the workspace clone, gitignored directories don't exist in the clone. The workspace's `.gitignore` lists child repo directories (`/engine`, `/soredium`) because those are separate git repos checked out as siblings. The code already calls `mkdir` and `_unignore_subdir` to create them — but with no validation afterward, a failure in that sequence was invisible. The `wksp/` symlink would point to a directory that should exist but doesn't.

The fix has three layers. First, `_get_family_repo_names()` scans all top-level git directories in the family root for collision detection — not just the current slot's repo list. Second, `validate_slot_wksp()` runs after every `create_slot` and `add_repo` call, checking that each `wksp/` symlink resolves. If any dangle, it exits 1 with the specific failure. Third, `list_slots` now surfaces `WKSP=broken` in its output so broken symlinks don't hide until someone notices a session misbehaving.

Along the way, I hit a Python gotcha worth remembering: `Path("").is_dir()` returns `True`. An empty string becomes the current working directory. `resolve_original_repo` was calling `git remote get-url local` through a mock that returned an empty string — `Path("")` resolved to the CWD, which happened to have a `wksp/` symlink, and validation failed against the wrong repo entirely. The fix is a one-liner (`and url.strip()`), but the failure mode was genuinely confusing to trace.

The broader pattern here is worth naming: silent degradation is worse than a crash. A slot that runs as `SINGLE_REPO=yes` still works — you can edit code, run tests, make commits. Everything looks fine until you try to find the handoff or the design spec and they're not where they should be. Five slots ran like this for weeks. Post-creation validation catches the failure at the moment it happens, when the fix is obvious, instead of leaving it to surface as a confusing symptom three sessions later.
