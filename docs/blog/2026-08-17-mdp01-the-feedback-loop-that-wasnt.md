---
layout: post
title: "The Feedback Loop That Wasn't"
date: 2026-08-17
entry_type: note
subtype: diary
projects: [soredium]
tags: [garden, mcp, audit, quality-loop]
series: issue-244-garden-feedback-wiring
---

The hortora garden engine has had a `gardenFeedback` MCP tool since the CBR design landed — fully implemented, unit tested, wired into the retrieval tracking database. It records whether garden entries returned by `gardenSearch` were actually useful for the work. That signal feeds `gardenUnretrieved`, which flags entries that get retrieved often but never help — the HIGH_RETRIEVAL_LOW_QUALITY category that's supposed to surface garden entries worth revising or retiring.

Zero feedback records. Ever. The tool existed, the database schema existed, the quality signal computation existed — but nothing in the skill layer called it. The loop was open.

The fix was twenty lines in `work-end/SKILL.md`: a new Step 5.6 that tells Claude to review which `gardenSearch` results appeared during the session, assess their relevance, group by outcome, and call `gardenFeedback`. Non-blocking — if the engine isn't running, skip silently. The tool already handles all the hard work: resolving GE-IDs to document IDs, finding the most recent retrieval record, writing the feedback row. The skill step just needs to provide the GE-IDs and a judgment.

What made this interesting wasn't the fix — it was the conversation about why the gap existed and what it revealed. The garden engine has three tracking tools: `gardenRecordProvenance` (wired into brainstorming and work-start), `gardenRecordOutcome` (not wired anywhere), and `gardenFeedback` (not wired anywhere). Provenance got wired because the spec explicitly said "call this from brainstorming." The other two got built, tested, and deployed, then sat idle because nothing in the skill layer knew to call them.

This points to a structural gap: the completeness audit in `executing-plans` checks spec-vs-code coverage, but only runs inside the executing-plans path. Ad-hoc work, manual implementation, and resumed sessions bypass it entirely. And even when it does run, findings are ephemeral — they print to conversation context and vanish when the session ends. The next session has no idea what was deferred, dismissed, or left unfinished.

The same problem shows up in the handover skill's epic hygiene checks — eight checks for workspace health (orphaned plans, stale branches, unrecovered artifacts) that are toggleable in the wrap checklist and whose findings die with the session.

Three issues capture the broader pattern: the gardenFeedback wiring itself, the ephemeral hygiene findings, and a unified persistent audit system covering completeness, gaps, and coherence. The audit system is the interesting one — it needs a persistence mechanism, accumulation across sessions, and a forcing function at work-end where every open finding must be resolved before the branch closes. No "defer indefinitely" — fix it, file it as an issue, or dismiss with a reason.

The gardenFeedback wiring was a twenty-minute fix. The audit persistence system it revealed will take real design work. That's usually how it goes — the small fix you came to make shows you the structural gap you didn't know was there.
