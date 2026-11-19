---
layout: post
title: "When every #42 is a collision waiting to happen"
date: 2026-09-02
entry_type: note
subtype: diary
projects: [hortora/soredium]
tags: [type-safety, plan-manager, refactor, cross-repo]
---

The `.plan` file — the queue that drives soredium's work lifecycle — tracked issues by bare number. `#42` meant issue 42. The trouble: when a queue spans multiple repos, `#42` in `casehubio/platform` is a completely different issue from `#42` in `casehubio/parent`. The plan had no way to tell them apart.

This caused two real bugs. The health check (`check_plan_state`) resolved every issue number against a single repo — whichever repo the epic lived in. When a number existed in both repos, it found the wrong issue, saw it was closed, and silently marked the plan item as done. The matching function (`_mark_completed`) had the same problem: it compared by bare int, so the first item with that number won regardless of which repo it belonged to.

The fix is a frozen dataclass called `IssueRef` that carries `repo` and `number` as an indivisible unit. Construction-time validation rejects empty repos — you can't create an `IssueRef` without saying which repo the issue lives in. Case normalization means `Hortora/Soredium` and `hortora/soredium` hash and compare equal, matching GitHub's own case-insensitivity.

The interesting part isn't the type itself — it's what happens when you replace a bare `int` with a validated wrapper across 94 sites. The parser now rejects bare `#N` queue lines outright. Every matching function keys on the full `IssueRef`, so two items with the same number in different repos are correctly distinguished. The `check_plan_state` health check groups open issues by repo and makes one GitHub API call per distinct repo instead of resolving everything against a single default. That single change is what actually eliminates the false positive bug.

At the persistence boundary — the worklog database — the schema stays as `(issue_number INTEGER, issue_repo TEXT)`. `IssueRef` decomposes into its components at the call site. Changing the DB schema would require a migration for no functional gain; the domain type handles correctness, the relational schema handles storage.

A pre-commit hook validates `.plan` file format on every workspace commit. If a bare `#N` slips through, the hook catches it before it can enter the repo. Belt and suspenders — the parser would reject it on the next read anyway, but catching it at write time gives a clearer error message than a parser crash at load time.

The refactor touches the full stack: `plan_manager.py` (the core), `events.py` (the TUI/CLI contract), five command files, `work_health.py` (the health check), and `work_chain.py` (the chaining engine). 144 tests updated and passing. The change is mechanical in nature but load-bearing in effect — every issue reference in the lifecycle pipeline now carries its repo identity, which means cross-repo queues finally work correctly.

What this opens up: multi-repo epic queues can now contain issues from arbitrary repos without collision risk. The `_resolve_ref` convenience function in the CLI means users can still type bare numbers when they're unambiguous — the plan knows which repo each item belongs to and resolves automatically, erroring only when the same number appears in multiple repos. The strict parser also means `migrate_plan_repos.py` becomes a one-time migration tool rather than a permanent crutch.
