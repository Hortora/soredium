---
layout: post
title: "Two Plans, One File"
date: 2026-08-17
entry_type: note
subtype: diary
projects: [soredium]
tags: [lifecycle, plans, workflow, slots]
---

The soredium lifecycle had a split personality problem. There were two things both called "plan" — a lifecycle queue tracking which GitHub issues to work through, and an implementation plan breaking a single issue into tasks. They lived in different files, served different audiences, and caused confusion whenever someone asked "what's the plan?"

Issue #242 started as a surgical fix: `merge_slot()` was pushing workspace clones through the same merge/push pipeline as project repos, causing silent failures and stranded content. The `.landed` marker would record SHAs that never reached the original workspace. Adding `is_workspace_clone()` with three detection signals — `.workspace` marker, `proj` symlink, naming convention — and filtering `merge_slot` to project repos only was the straightforward part.

The interesting work came from the conversation that followed. Three gaps surfaced during the session, each revealing something about how the lifecycle skills interact with each other:

**Design reviews had no incorporation step.** After a light review presented findings, the skill stopped. Findings sat in a tracker file. Whether they made it into the spec depended entirely on the user remembering to ask. We added Step 8b — show all findings with full context, then triage via the Q&A interface: incorporate all, walk through each, or skip. The per-finding walkthrough batches four questions at a time to keep the interaction tight.

**Plans had no wrap points.** An implementation plan was a flat sequence of tasks. If a session ended mid-plan, there was no concept of a safe stopping point — no guarantee the codebase was in a coherent state. We added batch grouping: tasks cluster into batches, each batch leaves the code compilable and testable, and executing-plans offers "continue or wrap" at each batch boundary.

**The two-plan problem itself.** The lifecycle queue (`.plan`) only understood issues. The implementation plan (`plans/*.md`) only understood tasks. Neither referenced the other. When a user asked for a plan, the system defaulted to issue-level batching — creating separate GitHub issues for each task — because the queue format had no concept of anything smaller than an issue. We unified them: the `.plan` now shows both levels. Issues at the top, with the current issue's task/batch breakdown indented underneath. When an issue completes, the tasks collapse to a single checked line. The detail plan doc still exists for the executor to follow; the `.plan` is the summary view.

The `plan_manager.py` changes were mechanical once the format was clear: `TaskItem` dataclass, parser for indented `Batch/Task` lines, `inject-tasks` and `check-task` CLI commands, and `advance()` stripping tasks when marking an issue complete. The skill updates were equally direct — writing-plans injects summaries, executing-plans checks off tasks and reads batch status.

One more fix came out of the conversation: Claude claiming "done" without checking for gaps. The user showed examples where they'd had to ask "was there really nothing left?" and Claude found real functional issues — unmapped entity types, unclosed GitHub issues, open epics. We added a mandatory completeness audit to executing-plans: before routing to work-end, scan for spec gaps, deferred items, skipped steps, TODOs in code, uncommitted work, and failed pushes. Present what's found, let the user triage via Q&A.

The session also audited all 80+ slot symlinks across active and archived slots. The first-pass audit flagged 87 problems; a deeper audit using `is_workspace_clone()` for classification revealed 92 were correct — slot-internal workspace references working as designed. Five were real: one active slot with a wksp pointing to a non-git directory, two archived slots with absolute paths to the original workspace, two with dangling symlinks. The reconciliation brought the worklog DB into alignment, with a small fix for FK-constrained records that couldn't be deleted.

The unified plan format makes the lifecycle's two levels of abstraction visible in one file — and more importantly, makes it clear when to use which. Issue batching for epics. Task batching for single issues. Both in the same `.plan`, both with wrap points, both collapsing when done.
