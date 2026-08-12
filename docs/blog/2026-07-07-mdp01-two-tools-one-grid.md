---
layout: post
title: "Two tools, one grid"
date: 2026-07-07
type: phase-update
entry_type: note
subtype: diary
projects: [soredium]
tags: [design-review, code-review, adversarial-review]
---

The issue said "replace code-review." I disagreed with my own issue.

Phase 4 of the adversarial review pipeline was supposed to be the final code review — the one that runs before merge and catches what the per-commit checklist misses. The issue described it as replacing the existing `code-review` skill entirely. That framing collapsed under first-principles analysis.

The real structure is a 2×2 grid. One axis is scope: commit-level vs branch-level. The other is depth: checklist/mechanical vs adversarial/analytical. Each tool gets exactly one cell:

- `code-review` → commit-level × checklist. Fast, cheap, runs on every commit. Language-specific patterns and naming conventions. Stays.
- `final-review` → branch-level × adversarial. Multi-round debate between two independent agents. Catches architectural drift, cross-cutting concerns, design-intent violations. New.

`requesting-code-review` was a stopgap that filled the branch-level cell with a single subagent dispatch. It worked, but the adversarial model is stronger — two agents who disagree with each other find more than one agent who agrees with itself.

The depth system was the second insight. A one-line bugfix doesn't need a $5 multi-round review. But a major feature branch shouldn't get a one-pass checklist either. We added `--depth light|standard|deep` with auto-detection from diff stats — lines changed, files touched, new files counting double. Light depth turned out to be explicitly non-adversarial: reviewer-only, no implementor round. Claude caught this during the adversarial spec review — a 1-round "adversarial" review where the implementor never responds isn't adversarial at all. It's just a single-pass check with a fancier name. So we named it what it is.

The spec review also caught something I'd been overconfident about: the claim that "no infrastructure changes" were needed to the review loop. Wrong. The loop hardcodes spec-file semantics — git add of the spec, verification against spec section headers, `_detect_last_round` treating reviewer-only rounds as partial. Final-review operates on branch diffs, not specs. Every one of those assumptions needed mode-conditional logic. The fix added per-source-dir commits, code-change verification, and a depth-aware round detector.

`work-end` now classifies the branch diff before choosing its review gate: structural changes (new files, signature changes, config changes) get `final-review`; body-only edits get the checklist. The user sees the classification and cost estimate before anything runs. No cost surprises.

The four-phase pipeline is complete. Pre-review validates the approach. Spec-review tears apart the design. Code-review checks implementation against the reviewed spec. Final-review checks whether the code is production-ready. Four different artefacts, four different questions, one engine.
