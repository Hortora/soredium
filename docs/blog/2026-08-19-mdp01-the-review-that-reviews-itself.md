---
layout: post
title: "The Review That Reviews Itself"
date: 2026-08-19
entry_type: note
subtype: diary
projects: [soredium]
tags: [review, findings-persistence, branch-audit, forcing-function, lifecycle]
series: issue-254-unified-review-findings
---

Work-end has had a code review gate since its earliest version. The problem wasn't that it was missing — it was that it was buried. Step 3.1, inside Execute, after the entire Sweep had already run. Forage, protocol capture, doc sync, write-content — ten minutes of knowledge capture before anyone looked at whether the code was actually right.

The deeper problem was scope. The code review was a per-line checklist: mutable defaults, unawaited coroutines, bare excepts. Useful, but it couldn't answer "did we build the right thing?" or "are there three deferred TODOs nobody tracked?" Those questions need a different kind of review — one that sees the full branch, not individual lines.

I started this session wanting to fix the ordering. What came out was a unified review and findings persistence system — four components that connect into a single pipeline.

The first decision was architectural: where does the branch-level audit live? Design-review already had a planned "Post-implementation" lifecycle point in `review-tiers.md`, marked "future" for over a month. The obvious move was to implement it there. But design-review's execution model — external sessions, watchdog crons, adversarial multi-round — doesn't fit a pre-merge gate that needs to be fast and inline. Claude pushed back when I suggested option 3 (extending design-review), and I initially agreed too quickly. The decision review caught the gap: `review-tiers.md` already planned this. The resolution was to treat lifecycle points as fillable slots — design-review's taxonomy maps points to dimensions, but different skills fill those slots with different execution models. Branch-audit fills post-implementation with inline single-pass. Design-review keeps post-spec with adversarial multi-round.

The four review dimensions — Conformance, Coherence, Structure, Robustness — are shared vocabulary between both skills. Structure nearly got collapsed into Coherence during the brainstorming, but decomposition and composition are opposite directions of the same concern. A design can have clean structure (good boundaries) but poor coherence (the pieces don't connect). Both deserve explicit attention.

The second discovery came from the decision review. I'd planned to retire `verification-before-completion` by folding it into the forcing function. The reviewer caught the conflation: VBC is "did you run the test before claiming it passes?" at every commit boundary. The forcing function is "are all findings resolved before merging?" at branch close. Different scopes, different lifecycle points. Both needed. VBC became a protocol in `docs/protocols/evidence-before-claims.md` instead of disappearing into the forcing function.

Findings persistence was the piece the blog entries from two days ago had already diagnosed. `findings.json` existed for hygiene findings but nothing else persisted. The Standard post-spec review ($48 across four dimensions) caught several things I'd missed in the spec: the JSON format has a concurrent write race that JSONL eliminates (append-only, O(line) lock hold instead of O(file)); freeform `detail` text breaks dedup across sessions because LLMs describe the same finding differently each time (the fix: stable `location` anchors like `file:line` or `spec:section`); and CRITICAL findings can't be dismissed — Fix or File only.

The loose ends sweep is the piece that makes the pipeline work across sessions. At every handover, it scans for deferred plan items, TODOs in code, and open findings from prior sessions, then persists them to `findings.jsonl`. They accumulate. At work-end, the forcing function drains them all — every finding must be resolved (fix, file as issue, or dismiss with reason) before the branch closes.

The implementation was five batches: findings library, loose ends sweep, branch-audit skill, work-end restructure, skill cleanup. Twenty-seven tests. The work-end flow changed from Context → Sweep → Execute (review buried in 3.1) to Context → Review → Sweep → Execute — review first, before investing in knowledge capture.

Two deprecated skills are gone. `requesting-code-review` had been marked deprecated since the `--mode final-review` addition, but its replacement was a poor fit — branch-audit fills the gap properly. Eighteen cross-references updated, `review-tiers.md` post-implementation activated, and the review landscape went from cluttered to clear: code-review for per-line, branch-audit for holistic, design-review for specs, security-audit for OWASP.

The irony of building a review system and then having it review itself isn't lost on me. The next work-end will be the first to run the new Step 2 for real — code-review, branch-audit, loose ends sweep, forcing function. If it catches something this session missed, that's the system working.
