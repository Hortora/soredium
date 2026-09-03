---
layout: post
title: "The whack-a-mole that wasn't"
date: 2026-09-03
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [lifecycle, parsing, false-positives, plan-io]
---

# The whack-a-mole that wasn't

Four out of five commits to `corruption.py` were fixing false positives. Each time the `.plan` format evolved — cross-repo issue refs, epic markers, batch headers — the corruption detector's inline regex quietly stopped seeing queue items it couldn't parse. No error. No warning. Just an empty list where three items should have been.

The symptom was always the same: a corruption warning at session start claiming all issues were closed when the queue plainly had uncompleted work. Each fix updated the specific regex or added a skip condition. Each fix worked. And two weeks later, another format evolution would hit the same gap in a different check.

The root cause was structural: thirteen independent implementations of the same section parser, nineteen copies of `covers.split(",")`, and three copies of the queue item regex — each subtly different. The canonical parser in `plan_manager.py` handled every format variant. The consumers didn't know it existed.

The interesting failure mode is silence. A regex that can't match a line doesn't raise an exception — it returns an empty list. The consumer code handles empty lists correctly (returns None, meaning "no inconsistency found"). The false positive fires from a *different* check that aggregates the empty result into "no remaining work, but all covered issues are closed — must be corruption." Tracing from symptom to root cause means following data flow across three functions and noticing what *isn't* there.

The fix is a shared parser module — `plan_io.py` — that owns all read and write operations on `.plan` files. One regex. One section walker. One `parse_covers()` function. Every consumer imports from here instead of reimplementing. The module also tracks unparsed lines: queue items that match the `- [ ]` prefix but don't match the full regex get collected into `PlanState.unparsed_lines` rather than being silently dropped. It's a format-evolution signal — if the queue format changes and the regex doesn't keep up, the unparsed lines accumulate as a visible diagnostic instead of disappearing.

Claude caught two things during code review that the plan missed: `write_state()` in `lifecycle.py` still had its full 43-line inline section walker (the migration script had silently failed to match), and `check_active_all_closed` still had a `covers.split(",")` — in the very function the issue was about.

What makes this worth writing about isn't the fix itself — extracting a shared module is textbook DRY. It's the failure mode that made the duplication invisible for months. When a parser silently drops what it can't match, the system appears to work. Every check runs. Every check returns a result. The result is just wrong, because the parser pretended the data wasn't there.
