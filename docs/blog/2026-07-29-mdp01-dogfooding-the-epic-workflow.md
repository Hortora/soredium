---
layout: post
title: "Dogfooding the Epic Workflow"
date: 2026-07-29
type: phase-update
entry_type: note
subtype: diary
projects: [soredium]
---

## Dogfooding the Epic Workflow

I wanted to validate the `work epic` / `work next` infrastructure we'd built for single-repo epic iteration. The temptation was to write integration tests in a temp directory, call it done. Instead I used it on real work — created an epic that bundled three genuine issues, ran the full cycle, and let the friction surface naturally.

The first epic (#105) grouped a docs update, a file extraction, and a new Python script. Three children, one batch. `work epic #105` parsed the `## Scope` checklist, created the branch, scaffolded `.meta` and `.epic`, and marked the first child active. Each `work next` advanced correctly — checked off the completed issue, moved the `← active` marker, updated Session State. When the last child finished, `epic_complete=true` came back and the epic issue itself was added to COVERS for closure.

Three friction points surfaced that wouldn't have shown up in unit tests.

First: `epic_manager.py` exposes `plan`, `advance`, and `status` as CLI subcommands, but `write_epic` was only a Python function. The `work epic` setup step had to call it via inline Python — ugly and fragile. We added a `write` subcommand that accepts the same parameters via `key=value` args.

Second: the scaffold commit only stages `.meta` and `JOURNAL.md`. The `.epic` file — written separately by `write_epic()` — was left untracked. At `work-end`, the dirty-tree pre-condition check caught it and halted. The fix: `commit-scaffold` now checks for `design/.epic` and includes it.

Third: `land_branch.py stamp` creates an empty commit with `chore: branch closed — landed as <SHA> on main`. The pre-commit hook requires issue references in every commit, and stamp commits had none. The stamp was blocked until I created it manually with `Refs #N` appended. The fix extracts the issue number from the branch name (`issue-NNN-*`) and adds it automatically.

All three are the kind of thing that only surfaces in actual use — the code was correct in isolation, the workflow was broken in combination.

The second epic (#111) fixed all three plus added a cross-repo dependency gate to `slot_manager.py`. The gate checks whether Maven provider repos in a slot have landed on main before consumers are pushed — preventing the class of broken-main bugs where blocks references APIs that only exist on engine's feature branch.

The `close_report.py` script that came out of #94 is the other notable piece. Work-end's close-out report was previously assembled by the LLM from prose instructions, which meant it was inconsistent — sometimes listing all operations, sometimes omitting steps. The replacement is deterministic: each step records its result into a JSON file, and `render` produces a structured summary. Fourteen step types, canonical ordering, failure rendering. The data was already there in structured form from each script's KEY=VALUE output — what was missing was a collector.
