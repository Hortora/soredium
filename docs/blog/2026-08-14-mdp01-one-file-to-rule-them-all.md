---
layout: post
title: "One File to Rule Them All"
date: 2026-08-14
entry_type: note
subtype: diary
projects: [soredium]
tags: [lifecycle, refactoring, first-principles]
---

Three files tracked the same thing. `.meta` held branch identity and lifecycle state. `.plan` held the work queue. `.epic` was a legacy fallback that `.plan` had already made redundant but nobody had removed. Between them, "what issue am I working on right now?" had three answers: the `← active` marker in `.plan`, the `Current: #N` line in `.plan`'s Session State, and the `issue: N` field in `.meta`. They were kept in sync by a function called `_update_meta_issue()` that ran on every queue advance.

The symptom that surfaced this: in slots, after finishing an issue, Claude would suggest running `work end` instead of `work next` — even when the queue had remaining items. The routing signal was fragmented across files, and the mid-session completion check wasn't firing consistently.

I started with a plan to just kill `.epic` and drop `issue:` from `.meta` — clean separation, two files with distinct responsibilities. But when we looked at it from first principles, the separation didn't hold up. `.meta` and `.plan` are always created together, deleted together, live in the same directory. No consumer reads one without the other being present. Two files meant two parsers, two paths to resolve, two places for state to diverge. The "different concerns" argument sounded principled but the reality was ten key-value lines and a markdown queue — not enough to justify the overhead.

We merged them. The unified `.plan` has a `## State` section (the old `.meta` content) and a `## Queue` section (unchanged). One file. One parse. The format is a natural fit — `.meta` was flat key-value, and `.plan` already had key-value in its `## Session State` section.

The review caught four things the plan missed. The migration function only took the first issue from `covers:` — a branch with `covers: 42,43,44` would have lost #43 and #44 from the queue. The `.epic` migration imported `epic_manager` at runtime, but the plan deleted that module in a later task — any branch with `.epic` that was first opened after the delete would silently fall back to a single-issue queue. The `write_state()` function scanned all lines for `state:`, which would false-match a queue item titled "state: machine refactor". And `rewrite_plan()` used direct `write_text()` — previously safe because lifecycle state survived in `.meta` even if `.plan` was corrupted, but now both live in the same file. All four were fixed before execution.

The end state: `epic_manager.py` (531 lines) and its tests (709 lines) are gone. `ctx.py` outputs `ACTIVE_ISSUE` instead of separate `PLAN_ACTIVE_ISSUE` and `EPIC_ACTIVE_ISSUE` fields. A new D4 directive fires mid-session when an issue completes — always check the queue before suggesting work-end. Migration-on-read handles old branches transparently: detect `.meta`, merge into `.plan`, delete `.meta`. Three scenarios covered — `.meta` alone, `.meta` plus old `.plan`, `.meta` plus `.epic`.

The interesting thing about this kind of refactoring is how the first-principles question — "do we really need two files?" — collapses a design that looked clean on paper but was creating real problems in practice. The separation of concerns was aesthetically satisfying. The single file is operationally correct.
