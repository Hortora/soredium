---
layout: post
title: "Verification as a shared library, not an afterthought"
date: 2026-09-07
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [verification, lifecycle, slot-isolation, work-end]
series: issue-339-shared-verification-library
---

# Verification as a shared library, not an afterthought

The integrity scanner and soredium's lifecycle code had been checking the same things independently — slot symlink escapes, CLAUDE.md absolute paths, stamp SHA validity, duplicate commits on main. Neither knew the other existed. The scanner found problems retrospectively; the lifecycle code didn't check at all, letting problems accumulate until the scanner caught them hours later.

The fix was extraction: pull every check function out of the 1,300-line scanner into a `verification/` package that both sides import. Seventeen functions, three modules (`slot_checks`, `repo_checks`, `cross_checks`), each taking a path and returning a list of findings. No side effects, no fixes, no output — just detection.

The interesting part was deciding *where* to gate. A postcondition check that runs after slot creation catches symlinks escaping the slot boundary before any work begins in the wrong directory. A precondition check before scaffold creation catches stuck `closing:*` state and plan/branch mismatches before the scaffold overwrites stale state. Neither of these existed before — the lifecycle just trusted that prior steps had succeeded.

Two other issues landed on the same branch because they fed directly into the verification work. The `update-claude-md` skill had been regenerating workspace-style headers (`# blocks Workspace`, `add-dir` with absolute paths) into project CLAUDE.md files — the exact content the verification library's `check_workspace_content_in_project` function detects. The fix was a content boundary rule: detect whether the target is a project or workspace file before writing, and never cross the boundary. The verification function provides the post-write safety net.

The work-end conflict loop was subtler. When `conflict_resolved=yes` came back to the orchestrator, it always marked `rebase` as done — even when the conflict had originated from `land`'s internal rebase. The next orchestrator call re-entered `land`, hit the same conflict, and the user was stuck. The fix checks progress: if `rebase` is already done, the conflict must have come from `land`. Additionally, `land_batch` now detects when the user has already merged the branch manually (branch HEAD is an ancestor of main) and skips straight to stamp.

What matters going forward: the verification library is the single source of truth for what "healthy" looks like. The lifecycle calls it as a gate; the scanner calls it for sweeps. Adding a new check means writing it once and it shows up in both places. The scanner shrank by 272 lines and the lifecycle gained fail-fast behaviour it never had.
