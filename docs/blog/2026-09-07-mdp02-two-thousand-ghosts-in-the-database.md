---
layout: post
title: "Two thousand ghosts in the database"
date: 2026-09-07
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [slot-state, worklog, migration, state-machine, audit]
---

The worklog DB said 19 slots were active. Four actually were. The rest were ghosts — slots that had landed but never updated their DB state, or slots whose work items lingered after the slot itself was archived. And buried alongside them, 2,021 entries from pytest runs that had been silently writing to the production database for months.

The root cause is structural: slot state lives in two places that don't talk to each other. The worklog DB tracks transitions (`active → ready → landed → archived`). The `.slot` file on disk records what the slot is — repos, branch, issue — but not where it is in its lifecycle. When a transition fires in one store but not the other (session crash, work-end interrupted, test using the wrong DB path), they drift. And nothing notices.

I wanted a single source of truth — or at least two sources that could cross-check each other. The design: add a `state:` field to the `.slot` file, make it authoritative, and build a central API (`slot_state.py`) that writes to both stores on every transition. The `.slot` file wins on conflict because it's visible, it's in the directory, and it survives DB corruption.

The state machine got a redesign too. The old model had eight states, several of which were implementation noise (`pending`, `failed`, `purged`) or unnecessary splits (`archiving` vs `archived`). The new model has seven visible states: `active`, `paused`, `ready`, `landed`, `stale`, `abandoned`, `archived`. Each maps to observable disk signals — you can look at a slot directory and know what state it should be in without querying anything.

`stale` and `abandoned` are new. A slot where all `.plan` issues are done but work-end never ran is stale — that's the corruption case I kept hitting. A slot whose GitHub issue was closed while it sat untouched is abandoned. Both were previously invisible; now the audit flags them.

The migration script backfilled 164 existing slots across both families. The reconciler then cross-checked every slot's `.slot` state against the DB and disk markers. It found 45 divergences on the first pass — 11 state mismatches (DB said `active`, disk said `landed`), 19 orphan work items (work items still marked `active` for slots already archived), stale DB records for directories that no longer existed. Two passes of `--execute` cleaned everything.

The test pollution was a separate discovery. `worklog.py`'s `connect()` function defaults to `~/.hortora/worklog.db`. Every pytest run that exercised slot creation was writing to the real DB because nothing overrode the path. The fix is an env var (`HORTORA_WORKLOG_DB`) checked before the default, plus an autouse conftest fixture that redirects every test to a temp file. The fixture is autouse — no test needs to opt in. Claude caught one thing in review I'd missed: the postcondition verification block in `create_slot` had been accidentally deleted during the refactoring. That's the kind of collateral damage that doesn't show up in tests because it's a runtime guard, not a tested path.

The `.slot` file is now the place to look. `cat slots/174/.slot` tells you the state, the issue, the repos, the branch. The DB is queryable for cross-family views, but the file is what matters. And the audit can now tell you, definitively, whether they agree.
