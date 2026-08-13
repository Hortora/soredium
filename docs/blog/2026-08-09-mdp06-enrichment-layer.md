---
layout: post
title: "The Enrichment Layer — Strategic Metadata on the Worklog"
date: 2026-08-09
entry_type: note
subtype: diary
projects: [soredium]
tags: [worklog, enrichment, what-next, trajectory]
series: issue-190-enriched-backlog
---

The worklog DB already tracks what happens — work-start, work-pause, work-end, slot-create — as an event log. What it doesn't track is what any of that means strategically. Which issues are quick wins? Which are compounding while I ignore them? Which ones just became ready because something else landed?

I wanted a local layer that lets an LLM answer "what should I work on next?" without querying GitHub every time and without relying on my memory of what shifted since the last session.

The design split the work into three pieces: an enrichment schema for per-issue strategic metadata, a GitHub issue cache with a short TTL, and trajectory notes that capture what completed work implies for what comes next. The enrichment fields — strategic role, readiness, decay, blast radius, cohesion — give the LLM a vocabulary for classifying issues. The cache gives it fast access to issue state. The trajectory notes give it memory across sessions.

The trajectory model was the most interesting design moment. I started with a single text field on the enrichment table — overwrite it each time. Claude caught this in the design review: trajectory notes accumulate over time. Each work-end adds a note; the what-next query reads the most recent ones. A single field would erase prior context every time it was updated. The fix was a separate append-only `trajectory_notes` table with timestamps and source branches. Obvious in hindsight, but the kind of thing a spec-level review catches before you build the wrong thing.

The enrichment module lives in its own file (`enrichment.py`) rather than extending `worklog.py`. Both share the same SQLite database — `worklog.py` owns the schema and migration, `enrichment.py` imports `worklog.connect()` for access. The separation keeps lifecycle recording (what happened) and strategic classification (what it means) in distinct modules that can be reasoned about independently.

The cache refresh has a guard I'm pleased with: if `gh issue list` returns an empty JSON array, the refresh does nothing. Empty responses can mean auth failure or network problems, not an actually empty backlog. Deleting the entire cache because of a transient failure would be worse than serving stale data.

Integration touches two skills. Work-end gets a trajectory capture step after artifact promotion but before the branch is pushed — the LLM already has full session context at that point, so generating a trajectory note and proposing a couple of enrichment updates is cheap. Work-start gets a what-next recommendation when you invoke `work` from main without specifying an issue number. Both are non-blocking — enrichment capture never gates a branch closure, and the recommendation is a suggestion you can ignore.

The system bootstraps through use. Enrichment data starts empty. Each work-end populates it. After a few sessions, the what-next query has enough signal to make grounded recommendations instead of just listing open issues.
