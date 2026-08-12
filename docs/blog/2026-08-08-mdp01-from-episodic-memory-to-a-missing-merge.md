---
layout: post
title: "From Episodic Memory to a Missing Merge"
date: 2026-08-08
entry_type: note
subtype: diary
projects: [soredium]
tags: [git, workflow, design, memory]
---

I started this session wanting to build an episodic memory system — a structured graph of work experiences that Claude could search alongside ADRs, specs, and garden entries. The design was elegant: episodes at work-end, a links column creating a traversable graph, semantic search via neocortex's memory API.

Then I asked the question that killed it: what would Claude actually use this for?

The honest answer was uncomfortable. Claude already has ADRs for architectural decisions, garden entries for gotchas, git blame for history, specs for design rationale. An episode that says "we discovered lifecycle transitions need three phases" is redundant if there's already a garden entry and an ADR saying the same thing. The synthesis and projections I liked from handover — those are human-facing value, not LLM-facing.

What survived the cull was smaller and more useful: trajectory notes. At work-end, Claude has full context about what was built and what it implies. A short "this suggests X next because Y" captured in the worklog DB persists into the next session. That's the piece that was genuinely missing — not a knowledge graph, but a "what next" recommendation grounded in recent work.

The conversation kept pulling the thread. If we're recommending "what next," we need a vocabulary for why something is next. Strategic role (quick win, load-bearing, parallelizable), readiness (ready, needs-design, needs-spike), decay (stable, compounding, perishable), blast radius (isolated, cross-cutting, foundational). Five dimensions on top of the existing scale and complexity labels, each directly mapping to a backlog management decision. All stored locally in the worklog DB as enrichment metadata — GitHub stays the source of truth for issue state, the local DB adds the fields GitHub doesn't have. No drift because the enrichment is local-only; no latency because it's SQLite.

Then the session took a hard turn. While closing the branch for the archive-prompt fix, we caught a live bug: `work_end_execute.py` pushed main to the remote without first merging the feature branch into it. Main stayed at its old position. The branch was stamped "closed" but the work never landed.

That bug led straight into the deeper problem I'd been avoiding: git push topology. Slots sometimes push to the fork when they should push to blessed. Users (me) sometimes commit directly to main. Squash-merge creates different SHAs, so fork main and blessed main diverge. The result: rebuilt branches and force pushes.

The fix is an invariant: main only moves by fast-forward merge of already-squashed branches. Four mechanical changes enforce it. First, `cmd_land` now does `checkout main && merge --ff-only branch` before pushing — the bug that started this. Second, push goes to blessed remote first (upstream in fork model), then mirrors to fork with `--force-with-lease`. Third, before landing, fetch blessed main and check for local-only commits — if someone committed to main directly, rescue those commits to a branch and reset main to blessed. Fourth, if push fails because another slot landed first, fetch blessed, rebase, retry — standard optimistic concurrency with a three-attempt cap.

The quick-fix flow — an ephemeral branch that replaces committing directly to main — is filed as a follow-up. The rescue logic handles the "committed to main by accident" case automatically, so the invariant is self-healing even without the discipline layer.

What connects these two threads — the episodic memory exploration and the git push fix — is the same question: where does useful work state actually live? The episodic memory answer was "not in a new artifact." The git push answer was "not in a local main that everyone pushes to independently." In both cases, the existing infrastructure was almost right. It just needed the missing merge.
