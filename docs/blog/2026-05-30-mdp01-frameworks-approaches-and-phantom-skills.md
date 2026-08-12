---
layout: post
title: "Frameworks, approaches, and the cost of phantom skills"
date: 2026-05-30
type: phase-update
entry_type: note
subtype: diary
projects: [cc-praxis]
tags: [hortora, skill-consolidation, framework-registry]
---

The session started as a README redesign. I wanted to move cc-praxis away from skill lists toward a "work, goals, results" framing — something that would make sense to someone discovering the project cold. Claude and I built browser mockups and settled on a workflow-first structure: a table showing what you type, what Claude does, what you get.

It didn't stay a README session.

While sketching the `/work` lifecycle, I kept bumping into a gap: there was no single gateway for project setup. The session hook, workspace-init, and issue-workflow were separate entry points with no coordination between them. We built `project-init` to fix it — one skill invoked by both the hook and `work-start`, writing `workspace: declined` and `Issue tracking: declined` directly to CLAUDE.md so users stop getting re-prompted after saying no.

That decision opened a thread that ran for most of the rest of the day. If `project-init` is the gateway, do you even need the workspace-init and issue-workflow slash commands? We removed them. Then: what else in the palette is noise? We ran a full audit against a single test: "only keep a skill separate if it's independently chained in at a different moment."

The test cut through cleanly. The five principles skills (code-review-principles, security-audit-principles, and three others) all failed immediately — never independently invoked, only ever loaded as prerequisites. We moved all four live ones to `~/.hortora/garden/approaches/` and deleted the skills. The six health sub-skills went the same way — always chained from the router, never independently used — and got folded into a single `project-health` with type-conditional sections. The three Quarkus skills got the more interesting treatment: their content migrated to `~/.hortora/garden/frameworks/quarkus-flow.md`, with a thin stub skill left as a description-based trigger until the Hortora RAG client exists to replace it.

That last move crystallised something I'd been circling. Skills are good for workflow process — what to do, when to do it. They're poor for reference material: API tables, MDC field lists, production configuration checklists. That material doesn't need to be loaded every session; it needs to be retrievable when relevant. Hortora's garden is the right home. We extended the garden with an `approaches/` directory alongside `frameworks/` — approaches for cross-cutting patterns, frameworks for specific technologies. Observability got split into two files: concepts (what the three pillars are, what MDC is) and patterns (how to wire it up, the production checklist). That distinction matters — you reach for them at different moments.

By the end: 58 skills and 73 commands down to 44 and 25. The deletion that felt most satisfying wasn't the obvious one (epic was long dead) but `update-primary-doc`, which existed to keep vision and thesis documents in sync with code commits. I realised you can't auto-sweep a vision document. It changes when your thinking changes, not when your commits change. The skill was solving a problem that doesn't exist. We deleted it and stripped `custom-git-commit` back to 60 lines.

The session closed with two small fixes: `work-end` now runs `mvn install` as a final build check for Java projects before marking the branch closed, skipping tests by default but prompting if you want them. And the handover skill no longer blocks the commit on a rename prompt when the session already has a meaningful name.
