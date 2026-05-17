# Design Spec — forage CAPTURE index gap fix

**Date:** 2026-05-17
**Issue:** Hortora/soredium#54
**Epic:** epic-forage-index-fix

## Problem

forage CAPTURE's deliver step (Step 8) and SWEEP's deliver step (Step 5) commit entry files via plain `git add/commit` without calling `integrate_entry.py`. This means `_summaries/`, domain `INDEX.md`, `labels/`, `_index/global.md`, `GARDEN.md` drift counter, and `garden.db` are never updated on CAPTURE or SWEEP. Approximately 512 entries are currently present in the garden filesystem but absent from all indexes.

`git grep` (forage SEARCH Step 3) still finds all entries since it scans the filesystem. But GARDEN.md and related index files are stale for roughly half the garden.

## Approach

Make `integrate_entry.py` composable via two new flags, then wire it into both CAPTURE Step 8 and SWEEP Step 5 Deliver. No index logic is duplicated — `integrate_entry.py` remains the single canonical integration point.

## Section 1 — `integrate_entry.py` changes

Add two independent CLI flags:

```
integrate_entry.py <entry_file> [garden_root] [--skip-validate] [--skip-commit]
```

- `--skip-validate` — skips `run_validate(garden)`. Used by both CAPTURE and SWEEP since Step 7 already validates each entry before delivery.
- `--skip-commit` — skips `git_commit(garden, ge_id)`. Used by SWEEP so index files are updated on disk but committed in a single batch by the caller.

The `integrate()` function gains two boolean parameters (`skip_validate=False`, `skip_commit=False`), both defaulting to `False`. Existing callers (CI, direct invocation) are unaffected.

`garden.db` upsert (`upsert_entry_index`) is not gated on either flag — it runs regardless.

## Section 2 — forage SKILL.md CAPTURE Step 8 (Deliver)

Replace the current manual `git add/commit` block with:

```
1. Stage the entry file:
   git -C /concrete/garden add <domain>/$GE_ID.md

2. Run integration (validation already done in Step 7):
   python3 /concrete/soredium/scripts/integrate_entry.py \
     /concrete/garden/<domain>/$GE_ID.md \
     /concrete/garden \
     --skip-validate

3. Pull and push (GitHub remote only):
   git -C /concrete/garden pull --rebase origin main
   git -C /concrete/garden push origin main
```

`integrate_entry.py` handles all index updates and commits in one shot. The entry file is already staged so it lands in the same commit as the index updates. Commit message: `index: integrate <GE_ID>` (replaces the previous `submit($GE_ID): <slug>` format).

## Section 3 — forage SKILL.md SWEEP Step 5 Deliver

Replace the current batch `git add/commit` block with:

```
1. For each written entry (sequentially):
   python3 /concrete/soredium/scripts/integrate_entry.py \
     /concrete/garden/<domain>/$GE_ID.md \
     /concrete/garden \
     --skip-validate --skip-commit
   (updates all index files on disk; no commit)

2. Single batch commit:
   git -C /concrete/garden add <all written entry files>
   git -C /concrete/garden add _summaries/ _index/ labels/ GARDEN.md
   git -C /concrete/garden add --update
   git -C /concrete/garden commit -m "sweep: <N> entries — <slug1>, <slug2>, ..."

3. Pull and push (GitHub remote only):
   git -C /concrete/garden pull --rebase origin main
   git -C /concrete/garden push origin main
```

Preserves the single-commit sweep behaviour. No N×validate penalty.

## Section 4 — Testing

All new tests live in the existing `tests/` directory alongside the current suite. Unit tests extend `test_integrate_entry.py`; integration tests add a new `TestCaptureDeliverFlow` and `TestSweepDeliverFlow` class using the `GitGarden` fixture from `tests/garden_fixture.py`.

### Unit tests — flag behaviour (`test_integrate_entry.py`)

7 new tests, all mock `run_validate` and/or `git_commit`:

- `test_no_flags_calls_both` — regression guard: both `run_validate` and `git_commit` are called when no flags passed
- `test_skip_validate_only` — `run_validate` NOT called; `git_commit` IS called
- `test_skip_commit_only` — `git_commit` NOT called; `run_validate` IS called
- `test_both_flags_skip_both` — neither called
- `test_skip_commit_still_updates_indexes` — with `skip_commit=True`, `_summaries/`, domain `INDEX.md`, `labels/`, `GARDEN.md` are all written to disk (flag skips commit only, not index work)
- `test_cli_skip_validate_flag` — subprocess call with `--skip-validate`; assert exit 0
- `test_cli_skip_commit_flag` — subprocess call with `--skip-commit`; assert exit 0

### Integration tests — CAPTURE flow (`TestCaptureDeliverFlow`)

Uses `GitGarden` (real git repo, no mocks):

- `test_capture_flow_entry_and_indexes_in_same_commit` — stage entry → `integrate(skip_validate=True)` → assert single commit contains entry file + all index files (`_summaries/`, `INDEX.md`, `labels/`, `GARDEN.md`); drift counter +1
- `test_capture_flow_local_garden_no_push` — no remote; integration commits locally, no push attempted

### Integration tests — SWEEP batch flow (`TestSweepDeliverFlow`)

Uses `GitGarden`:

- `test_sweep_flow_single_batch_commit` — 3 entries → `integrate(skip_validate=True, skip_commit=True)` × 3 → batch commit → assert exactly 1 commit (not 3), all entry files present, all index updates present; GARDEN.md drift +3
- `test_sweep_preserves_batch_commit_message` — commit message matches `sweep: N entries — slug1, slug2, ...` format
- `test_sweep_mixed_domain` — entries in 2 different domains; both domain `INDEX.md` files updated in the single batch commit

## Out of Scope

Backfill of the ~512 existing unindexed entries is a separate concern. Once the forward path is solid, a dedicated backfill script should run `integrate_entry.py --skip-validate --skip-commit` for each unindexed entry and issue a single batch commit.
