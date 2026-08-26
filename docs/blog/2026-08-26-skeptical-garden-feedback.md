---
title: "Making garden feedback honest"
date: 2026-08-26
entry_type: note
subtype: diary
projects: [Hortora/soredium]
series: soredium-lifecycle
author: mdp
tags: [garden, feedback, retrieval, staleness]
---

# Making garden feedback honest

The garden feedback step at session end was a formality. The LLM either rubber-stamped everything as RELEVANT or skipped entirely — both produce useless signal. The fix inverts the default and separates mechanical checks from judgment.

Two changes make this work.

The first is a Python script (`garden_feedback_table.py`) that reads from the retrieval tracking DB instead of conversation context. The DB knows what was returned even when the conversation has been compressed and the LLM has forgotten half the entries it saw three hours ago. The script cross-references each entry's `verified_on` field against the project's current stack versions (parsed from pom.xml, package.json, or CLAUDE.md) and flags mismatches. It also flags entries with no `verified_on` at all — "unverified for current stack" is a different signal from "verified on an older version" — and entries whose `last_reviewed` date is more than six months old.

The second is a framing change: all entries default to RELEVANT, and the LLM's job is to be skeptical — find the ones that shouldn't be. "Skip = all RELEVANT" is better than "skip = no data," and skepticism is a specific task with a clear success criterion. The mechanical flags from the script handle version staleness; the LLM only needs to catch unflagged entries that weren't actually useful.

The same flow now runs in both work-end and handover, so feedback happens at every session boundary — not just branch close.
