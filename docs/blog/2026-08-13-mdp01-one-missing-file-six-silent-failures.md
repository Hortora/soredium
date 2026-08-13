---
layout: post
title: "One Missing File, Six Silent Failures"
date: 2026-08-13
entry_type: note
subtype: diary
projects: [soredium]
tags: [slots, work-end, merge-slot, debugging, isx]
---

The slot workflow has a clean separation: work-end owns the close sequence (review, promote, squash), and `merge-slot` owns the landing (rebase, two-hop push, stamp, archive). The handoff point is a marker file called `.phase-a-complete`. merge-slot won't land without it. work-end never wrote it.

The result was a cascade. `merge-slot` returned `not_ready` — which sounds like the branch isn't ready, not that a marker file is missing. No `.landed` marker meant `archive-slot` refused to proceed without `--force`. The two-hop push (slot clone to original repo to GitHub) never ran, leaving the original repos stale. The workspace was never synced. The archive prompt in work-end's Step 5.1 was never reached.

Six failures, one root cause. The fix is a single function: `cmd_write_marker()` in `work_end_execute.py`, called after squash completes. It writes two lines — `branch=` and `timestamp=` — to the slot root. After that, `merge-slot` picks up and handles everything it was always designed to handle.

The more interesting question was whether work-end should bypass `merge-slot` entirely and do its own slot landing. We considered it. `merge-slot` has 287 lines of tested landing logic — rebase retry, SHA verification, `.landed` audit trail, two-hop push across all repos including workspace clones. Duplicating that for a missing marker file would be the wrong trade. The restructure spec already plans a unified close sequence; for now, writing the marker and letting `merge-slot` do its job is the correct scope.

The same session also designed the ISX integration for slots — running work inside incus-spawn containers. That's a different kind of isolation: OS-level (separate filesystem, process tree, networking) versus the slot's repo-level isolation (cloned repos, isolated .m2). The design landed on a dual-existence model: ISX container for working, local clones for landing. Ten decisions, most of them straightforward once we'd established that `isx sync` wasn't in blessed upstream and the `isx://` git remote protocol was. That work is in Slot 8, waiting for implementation.

One gotcha worth knowing: when you upgrade ISX via Homebrew, the old symlink at `/opt/homebrew/bin/isx` shadows the new install. `brew link --overwrite incus-spawn` fixes it, but the error message doesn't tell you that — it just says the formula built but isn't linked.
