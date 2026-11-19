---
layout: post
title: "Thirteen State Locations and What to Do About Them"
date: 2026-08-06
type: phase-update
entry_type: note
subtype: diary
projects: [soredium]
tags: [lifecycle, state-management, architecture]
series: issue-188-unified-work-state
---

I started with a stale HANDOFF.md item. "WI 490 — work-end interrupted, not merged, not stamped." It had been sitting there for days. The branch was already merged. Nobody validated it because the resume cross-check only validates GitHub issue state, not git branch state.

That single item opened a larger question: how many places in the system track the same fact, independently, without consistency guarantees?

The answer is thirteen.

Five places track "is this issue done?" — `.plan` checkboxes, `.meta` covers, HANDOFF.md What's Left, HANDOFF.md What's Next, and the resume cross-check against GitHub. Five track "is this branch closed?" — EPIC-CLOSED.md, stamp commits on project and workspace branches, `verify_slot_close.py`, and `audit_slot_merges.py`. Three more provide cross-cutting validation that re-derives the same facts from different angles.

Each is maintained independently. When an external actor changes state — another session closes an issue, another context merges a branch — cross-location consistency is never re-established until a validation path happens to run. The system caches state that has authoritative sources elsewhere, then adds reactive validation to detect cache staleness. The caches go stale. That's what caches do.

## The design

The fix is to stop caching and start deriving. Each fact gets one source of truth. Everything else queries it.

**`is_closed()`** is the clearest example. Five different tools were implementing their own "is this branch done?" logic with slight variations in stamp format checking, merge detection, and workspace handling. One function in `lifecycle.py` replaces all of them. It returns a `ClosureState` enum — `CLOSED`, `MERGED_UNSTAMPED`, `STAMPED_UNMERGED`, `OPEN`, `DELETED` — and every tool uses it. All local git, sub-second. The interesting subtlety: when combining project and workspace state, worst state wins. If the project branch is closed but the workspace branch is open, the result is open. I got this backwards on first implementation — `min()` instead of `max()` against the priority list — and the tests caught it immediately.

**`work_health.py`** consolidates the scattered validation into a single check registry. Eight entry-scope checks run on session start: meta consistency, pause stack validity, workspace alignment, main divergence, dirty main, partial pause/resume detection, and branch closure. One script, one invocation, one output format. The handover skill's eight epic hygiene checks, the resume cross-check, and the ARC42 stale scan all collapse into this.

**`.plan` on main** replaces HANDOFF.md's What's Left and What's Next. The key insight came from a simple question: where does work state live between branches? HANDOFF.md was a prose cache of information that GitHub issues already track. `.plan` is already a structured format with issue numbers, titles, completion markers, and queue position. Putting it on main gives it persistence across branches. One `gh issue list` call batch-validates the entire queue against GitHub on session start.

**HANDOFF.md shrinks to session context.** Last Session, Immediate Next Step, Cross-Module blockers, References. Under 200 tokens. No work tracking, no backlog. The narrative gloss — "we tried X, it failed because Y, pivoted to Z" — is genuinely valuable for session continuity. The work items are not.

## What EPIC-CLOSED.md was doing wrong

EPIC-CLOSED.md is a marker file on the workspace branch that says "this branch is closed." But the stamp commit on the project branch already says the same thing. Two markers for the same fact, checked by different tools, created at different lifecycle points. A branch can have one without the other. `is_closed()` eliminates the need for the marker file entirely — the stamp commit is the single closure signal.

## The scratchpad gap

The brainstorming surfaced something unexpected: there's no home for persistent cross-session notes. Things like "remember to check if trellis reads worklog.db" or "the handover commit dance has eight git operations — revisit later." These aren't issues (not actionable yet), aren't HANDOFF.md (overwritten each session), aren't CLAUDE.md (conventions, not notes). A simple `$WORKSPACE/NOTES.md` — append-only, committed to main — fills the gap. Items that become actionable get filed as issues. Items that become conventions move to CLAUDE.md. The rest just sits there until it's relevant or forgotten.

The adversarial design review ran four dimensions and surfaced 54 issues. The most interesting was from the structure dimension: the original design included a "State Cache" section in `.plan` that cached GitHub issue state locally. The reviewer correctly identified this as contradicting the "derive, don't cache" principle that motivated the entire design. I'd already removed it before the review finished — the user had edited the spec directly. Both arrived at the same conclusion independently.

Six commits landed. The open question is whether the remaining phases — removing EPIC-CLOSED.md from work-end, eliminating `.meta` covers, adding crash recovery for pause/resume — will surface more of these hidden contradictions in the existing state model, or whether the foundation is now clean enough to build on mechanically.
