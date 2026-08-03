# Mechanise LLM-Dependent Steps + Epic Lifecycle Awareness

**Issue:** #151
**Date:** 2026-08-03
**Principle:** Scripts do, scripts verify, LLMs decide.

---

## Problem

Two related gaps in the work lifecycle:

1. **Mechanisation:** Five steps rely on the LLM remembering to do them. LLMs
   don't carry state between sessions — "noted for next time" is not enforcement.
2. **Epic awareness:** work-end, merge_slot, work-pause, and work-resume have no
   consistent awareness of epic state. You can accidentally close mid-epic with
   no warning, lose epic context across pause/resume, and see no batch info in
   the stack picker.

Same root cause: scripts should surface state and enforce invariants; LLMs should
make decisions based on what scripts report.

### Scope

Items A, B, E, F, G, K address the mechanisation items from issue #151 (blog
index update moved to #155).
Items C, D, I, J1–J4 add epic lifecycle awareness — detecting and surfacing epic
state at every transition point in the work lifecycle. Both halves share the same
foundation (detect() in A) and are tightly coupled: mechanising slot operations
without epic awareness would leave the highest-risk scenario (mid-batch close)
unprotected. All items are tracked under #151.

### Relationship with #141

Issue #141 (issue-level lifecycle within epic slots) adds per-child-issue
start/end events, recording when work began and ended on each issue. The data
model here (stack entry fields `epic_batch` and `epic_active_issue`, display
format) is forward-compatible: #141 adds richer lifecycle events but doesn't
change how batch position or active issue are represented. If #141 later needs
additional stack fields, they can be added without breaking the schema introduced
here — the YAML format is additive.

---

## Layer 1 — Foundation

### A. `epic_manager.py` — canonical epic detection + check subcommand

**Problem:** Three independent parsers for "is this an epic?" — ctx.py (checks
`workspace/design/.epic`), work_router.py (checks `.slot` + `.epic`),
slot_manager.parse_slot_md (checks `.slot`). Should be one source of truth.

**Change:** Add two things to `epic_manager.py`:

1. `detect(path: Path) -> dict | None` — given a workspace, project, or slot
   path, find and parse the epic file. Wraps `parse_batch_plan()`: locates
   the epic file first, then delegates parsing. Returns the enriched dict
   with `epic_path` added, or `None` when no epic file is found.

   Search order:
   - `path/design/.epic` (single-repo workspace epic)
   - `path/.slot` with `Type: epic` (slot directory)
   - `path.parent/.slot` with `Type: epic` (project inside a slot)

   Return type distinction: `detect()` returns `None` for "no epic file at
   this path" (path-level). `parse_batch_plan()` returns `{"is_epic": False}`
   for "file exists but is not an epic" (content-level). Both are meaningful.

   This replaces the ad-hoc parsing in ctx.py and work_router.py.

2. `check` CLI subcommand — calls `status()` (already exists) and outputs
   KEY=VALUE lines for consumption by work-end and merge_slot:
   ```
   IS_EPIC=yes
   EPIC_COMPLETE=yes|no
   SAFE_EXIT=yes|no
   CURRENT_BATCH=2
   TOTAL_BATCHES=4
   ACTIVE_ISSUE=83
   COMPLETED_COUNT=5
   TOTAL_COUNT=12
   ```

`status()` already computes most of this (returns `current_batch`,
`current_issue`, `batches` with completion state). The `check` subcommand
is a CLI wrapper.

**`safe_exit` fix:** The current `status()` computes `safe_exit` as
`completed_batches > 0` ("has any batch ever completed"). This is wrong
for the work-end gate — it reports safe exit mid-batch when an earlier batch
completed. Fix: "at a batch boundary" — the first incomplete issue is the
first issue in its batch (all prior batches complete, no work started in
current batch), AND at least one batch is complete. This matches `advance()`'s
semantics where `safe_exit = batch_complete`.

**`EPIC_COMPLETE` derivation:** `EPIC_COMPLETE` requires
`total_issues > 0 and completed_count == total_issues`. An empty or malformed
batch plan (zero issues) must not produce `EPIC_COMPLETE=yes` — the current
`current_issue == 0` check has two meanings (all done vs. empty file) and the
guard prevents the ambiguity.

3. `tick` CLI subcommand — idempotent: reads the GitHub epic body, ticks
   checkboxes for completed issues, writes back. Callable independently for
   retry after network failure. See §G.

**Tests:** Unit tests for `detect()` with both `.epic` and `.slot` epic files,
non-epic `.slot`, and missing files. Test `check` subcommand: output format,
`SAFE_EXIT=no` mid-batch even with prior completed batches, `EPIC_COMPLETE=no`
for empty batch plan. Test `tick` idempotency.

### B. ctx.py enrichment

**Change:** Replace the inline epic detection (lines 165-170, 232-233) with
calls to `epic_manager.detect()`. Try `detect(Path(workspace))` first for
single-repo epics; if `None` and the project is in a slot (`/worktrees/` in
the project path), try `detect(Path(project))` — the `path.parent/.slot`
search in detect() catches slot-based epics. Add `EPIC_BATCH` and
`EPIC_ACTIVE_ISSUE` to output. This gives work-end batch context for both
single-repo and slot-mode epics without a separate `check` call.

The `check` subcommand (Layer 2) is still needed for `EPIC_COMPLETE` and
`SAFE_EXIT` — ctx.py stays cheap and doesn't compute completion state.

**Tests:** Update existing ctx.py tests for new output fields, including
slot-mode epic detection.

### B2. work_router.py consolidation

**Problem:** work_router.py (lines 70-137) has the largest inline epic
parser in the codebase — separate code paths for `.slot` epics and `.epic`
epics, each with duplicated `Type: epic` string matching, batch regex
extraction, and current issue parsing.

**Change:** Replace both code paths with calls to `epic_manager.detect()`:

- Slot path (lines 70-101): `detect(project.parent)` where project is
  inside a slot worktree
- Workspace .epic path (lines 104-137): `detect(Path(workspace_path))`

The `epic_batch` output format (`"N of M"`) is a presentation concern —
compute it in work_router.py from the parsed batch data rather than
embedding formatting in detect().

**Tests:** Update existing work_router.py tests to verify detect() delegation
produces identical KEY=VALUE output.

---

## Layer 2 — Gates

### C. work-end epic confirmation gate

**Change:** Add Step 0b in work-end Pre-conditions, after branch divergence
check, before pause stack check.

Read `IS_EPIC` from ctx.py output (already run in Path Resolution). If `no`,
skip silently.

If `yes`, run:
```bash
python3 ~/.claude/skills/work-slot/epic_manager.py check <EPIC_PATH>
```

Read `EPIC_PATH` from ctx.py output for the check call.

**Data flow:** From check output, read `EPIC_COMPLETE`, `SAFE_EXIT`,
`CURRENT_BATCH`, `TOTAL_BATCHES`, and `ACTIVE_ISSUE` for prompt rendering.

Three outcomes, evaluated as an if/elif/else chain in this order:

| Check (in order) | UX |
|-------------------|----|
| `EPIC_COMPLETE=yes` | Proceed silently — all children done |
| `SAFE_EXIT=yes` | "Batch `CURRENT_BATCH`/`TOTAL_BATCHES` complete. Safe exit point — close? (y/n)" |
| Neither | "⚠ Mid-batch (issue #`ACTIVE_ISSUE` of batch `CURRENT_BATCH`/`TOTAL_BATCHES`). Partial close loses context. Continue? (y/confirm-partial)" — requires typing `confirm-partial`, not just `y` |

Note: `EPIC_COMPLETE=yes` implies `SAFE_EXIT=yes`. The if/elif ordering ensures
only the most specific arm fires — a completed epic proceeds silently rather
than also triggering the safe-exit prompt.

The mid-batch confirmation is deliberately high-friction. Accidentally closing
mid-batch is the bug that surfaced this issue.

**Skill change only** — no new script (uses `check` from Layer 1).

### D. merge_slot() epic check

**Change:** At the top of `merge_slot()`, after the `.phase-a-complete` check,
call `parse_slot_md()` to check `is_epic`. (`parse_slot_md()` is the correct
call here — merge_slot already has the `.slot` file in hand; it doesn't need
`detect()`'s path discovery. `detect()` finds the file; `parse_slot_md()`
parses an already-known file.) If epic:
- Call `epic_manager.status()` on the `.slot` file
- Print `EPIC_STATUS=batch N/M, N completed, N remaining`
- Informational only — not blocking (Phase A already involved user confirmation)

**Tests:** Add test for merge_slot with epic slot — verify status is printed.

---

## Layer 3 — Mechanical Enforcement

### E. archive_slot() checkbox verification

**Change:** In `archive_slot()`, before moving to attic, if the slot is an epic
(check via `parse_slot_md`):

1. **Local checkbox verification:** Read the `.slot` file and verify all
   completed issues have `- [x]`. If any have `- [ ]` but their GitHub issue
   is CLOSED, auto-tick them and rewrite the file. Print
   `CHECKBOXES_FIXED=N` if any were fixed, plus
   `WARN=stale_checkboxes issues=83,84` — the warning surfaces potential
   workflow bugs (`advance()` not called, manual file edits).

2. **GitHub epic body catch-up:** Call `tick_epic_checkboxes()` (§G) for
   all issues in COVERS. This catches failed post-merge ticks.

If GitHub is unreachable during either check: log
`WARN=github_unreachable_for_checkbox_verify`, skip the GitHub-dependent
operations, proceed with archival. The archive is the critical operation;
checkbox fixes are best-effort.

**Tests:** Test with `.slot` containing unticked checkboxes for closed issues.
Test with GitHub unreachable — verify archive proceeds with warning.

### F. phase_b_gate.py (new script)

**Purpose:** Replace the self-certified markdown checklist for Phase B
completion. Reads actual filesystem and GitHub state, returns structured
pass/fail. The primary new value is the "issues CLOSED" check — no existing
code verifies this. The stamp and archive checks are cheap (O(1) filesystem)
defense-in-depth that catches step-skip scenarios without trusting each
step's self-report.

**Location:** `work-end/phase_b_gate.py`

**Checks:**
1. All repos in slot have stamp commits (`chore: branch closed`)
2. All issues in COVERS are CLOSED on GitHub
3. `.artifacts-promoted` stamp exists
4. Slot directory is in `worktrees/attic/` (archived)

**Why no rebase/push check:** The current SKILL.md Phase B gate (line 698) lists
"Branches rebased and pushed" as a check. This is intentionally omitted here
because stamp commits (check 1) are only written by `merge_slot()` AFTER
successful push to main (slot_manager.py line 705-716). A stamp's existence
proves the push succeeded — checking push separately would be redundant.

**Output:**
```
GATE=pass
```
or (definite failures):
```
GATE=fail
MISSING=stamps:engine,issues:83,archive
```
or (network errors — can't verify):
```
GATE=warn
MISSING=issues:83,84
REASON=github_unreachable
```

**Usage in work-end Phase B:** After B7 (archive), before B8 (post-merge),
run the gate. If `GATE=fail`, hard stop with the missing items listed.
If `GATE=warn`, prompt the user with context ("GitHub unreachable — issues
may be closed but can't verify. Proceed? y/n") rather than hard-stopping.

**Tests:** Tests for each check (stamps missing, issues open, no archive).
Test GitHub unreachable produces `GATE=warn` not `GATE=fail`.

### G. merge_slot() GitHub epic checkbox tick

**Change:** After `merge_slot()` succeeds (`.landed` written), if the slot is
an epic, tick the completed child issues' checkboxes on the GitHub epic body.

Implementation: read the epic issue body via `gh api`, find `- [ ] #N` lines
for each issue in COVERS, replace with `- [x] #N`, update via `gh api`.

Add a helper function `tick_epic_checkboxes(issue_repo: str, epic_number: int,
completed_issues: list[int])` to `epic_manager.py`. merge_slot calls it after
writing `.landed`.

**New dependency:** This introduces `slot_manager → epic_manager` (first time).
The direction is correct — slot operations delegate to epic logic. Import
`tick_epic_checkboxes` from `epic_manager` in `merge_slot()`.

**Error handling:** The tick is cosmetic — the merge has already succeeded
(`.landed` written, code on main). If `gh api` fails, print
`WARN=epic_tick_failed` and continue. Do not fail `merge_slot()` for a
GitHub API error. The `tick` CLI subcommand (§A) provides an independent
retry path when re-running `merge_slot()` would return
`ERROR=already_landed`. Additionally, `archive_slot` (§E) calls
`tick_epic_checkboxes` as a catch-up mechanism before archival.

The function is idempotent — already-ticked checkboxes are left unchanged.

**Concurrent merge constraint:** The read-modify-write on the GitHub epic
body is not atomic. Concurrent merges of different slots for the same epic
could lose checkbox ticks. This is acceptable: slot merges are sequential
in practice (manual, one-at-a-time workflow), and `archive_slot` (§E)
corrects any cosmetic drift.

**Tests:** Mock `gh api` calls, verify checkbox replacement regex handles
various formats (`- [ ] #83`, `- [ ] #83 — title`, `- [ ] https://...`).
Test idempotency (running twice doesn't double-tick).

### ~~H. update_blog_index.py~~ — moved to #155

Removed from this spec — structurally unrelated to epic lifecycle and
work-end mechanisation. Filed as Hortora/soredium#155 for independent delivery.

---

## Layer 4 — Context Propagation

### I. work-pause stack enrichment

**Change:** In `stack.py`, when pushing an entry, detect epic state:
- If IS_EPIC (from ctx.py or by checking `.epic`/`.slot`): add `epic_batch`
  and `epic_active_issue` fields to the stack entry
- If not epic: omit (backward compatible — existing stack entries without
  these fields are handled gracefully)

Stack entry format becomes:
```
branch=issue-151-...
issue=151
paused=2026-08-03T14:00:00
wip_project=yes|no
wip_workspace=yes|no
slot=72
epic_batch=2/4
epic_active_issue=83
```

**Serialization fix:** `_entries_to_text()` currently uses a hardcoded key
tuple `("issue", "paused", "wip_project", "wip_workspace", "slot")` that
silently drops any other keys. Change to serialize all keys present in the
dict — known keys first in stable order, then any additional keys
alphabetically. This makes the serializer forward-compatible.

**Output fix:** `cmd_list()` must include `ENTRY_N_EPIC_BATCH` and
`ENTRY_N_EPIC_ACTIVE_ISSUE` in its output for the display improvements in §J
to work.

**Tests:** Test push with and without epic state, pop with missing fields
(backward compat). Test that `_entries_to_text` round-trips unknown keys.

### J. Display improvements (skill documentation)

**J1. Router "end" option epic annotation** (`work/SKILL.md` Step 4):
When `IS_EPIC=yes` (from work_router output), change:
```
> N+1. **end** — close this branch, merge, push, return to main
```
to:
```
> N+1. **end** — ⚠️ epic Batch N of M — close this branch, merge, push, return to main
```

**J2. work-start Epic Overlay numbered** (`work-start/SKILL.md`):
Number the Epic Overlay section as Step 3d in the resume path. Change "After
the standard resume steps complete" to an explicit numbered step so it can't
be skipped.

**J3. work-resume epic context** (`work-resume/SKILL.md`):
Add Step 9b after Step 9 (work-start pre-checks): "If stack entry has
`epic_batch`, display: `Epic — Batch N, active: #M`."

**J4. work-pause/work-resume confirmation messages** (SKILL.md changes):
- work-pause confirmation: include "Epic Batch N/M, active: #X" when epic
- work-resume confirmation: include epic context from stack entry

**J5. Slot clones: no remote pushes until Phase A** (`work-slot/SKILL.md`,
`work-start/SKILL.md`, `git-commit/SKILL.md`):

Slot clones (`git clone --shared`) are isolated workspaces. Their `origin`
points to the local parent repo, not GitHub. During regular work (committing,
advancing issues), branches should accumulate commits locally in the clone.
No pushes to origin (local parent) or to GitHub until:

- **Phase A:** squash + push branch to origin (`--force-with-lease`)
- **Phase B:** merge_slot pushes to origin, then original pushes to GitHub

Currently the LLM offers "push the branch to remote" after advancing issues
or completing work. This creates branch noise on the parent repo and can
cause conflicts when Phase A squashes. Fix:

- `work-slot/SKILL.md` `work-slot next` — remove any push instruction after
  advancing. The only remote operation is the GitHub checkbox tick (§G, Step 3).
- `work-start/SKILL.md` Step 10 — when in slot mode (`IN_SLOT=yes`), skip
  the scaffold push. The scaffold lives in the clone only.
- `git-commit/SKILL.md` — when in slot mode, suppress the post-commit push
  offer. Commits stay local until Phase A.

Add to each skill: "**Slot mode:** commits stay local in the clone. No pushes
until Phase A."

---

## Layer 5 — Audit

### K. Stamp verification

**Finding:** `land_branch.py cmd_stamp()` (line 144-160) always calls
`verify_stamp.py` before writing the stamp. There is no code path that
skips verification. `merge_slot()` (line 706-713) stamps directly without
calling `verify_stamp.py` — but it stamps in the clone after push, and
the push itself is the verification (content must be on main for the push
to succeed).

**Verdict:** No code change needed. The slot path has a different verification
mechanism (push success = content landed). Document this difference in the
work-end skill for clarity.

---

## Execution Order

```
A (epic_manager detect+check+safe_exit fix) → B (ctx.py) + B2 (work_router.py)
  → C (work-end gate) + D (merge_slot check)
  → E (archive checkbox) + F (phase_b_gate) + G (github tick)
  → I (stack enrichment)
  → J1-J4 (skill display changes)
  → K (audit — verify only, note in spec)
```

A→B+B2 is the foundation everything depends on. C+D use the foundation for
gates. E-G are independent mechanical tasks. I needs A for detection. J is
documentation. K is read-only.

---

## Test Strategy

Every new script and every modified function gets unit tests per the
`externalised-scripts-require-tests` protocol.

| Item | Test file | Tests |
|------|-----------|-------|
| A | test_epic_manager.py | detect() with .epic, .slot, non-epic, missing |
| A | test_epic_manager.py | check: output format, SAFE_EXIT mid-batch, EPIC_COMPLETE empty plan |
| B | test_ctx.py | EPIC_BATCH, EPIC_ACTIVE_ISSUE in output (slot + single-repo) |
| B2 | test_work_router.py | detect() delegation, identical KEY=VALUE output |
| D | test_slot_manager.py | merge_slot prints EPIC_STATUS for epic slot |
| E | test_slot_manager.py | archive_slot auto-ticks stale checkboxes |
| F | test_phase_b_gate.py (new) | pass, fail-stamps, fail-issues, fail-archive, warn-github-unreachable |
| G | test_epic_manager.py | tick_epic_checkboxes regex, idempotency |
| I | test_stack.py | push/pop with epic fields, _entries_to_text keys, backward compat |

Items C, J1–J4, K are skill-documentation or audit-only changes — no script
tests needed.

---

## Files Changed

**Scripts (new or modified):**
- `work-slot/epic_manager.py` — detect(), check subcommand, safe_exit fix, tick_epic_checkboxes()
- `work-slot/slot_manager.py` — archive_slot() checkbox fix, merge_slot() epic check + tick
- `work-end/phase_b_gate.py` — new
- `project/ctx.py` — epic enrichment (both .epic and slot-based detection)
- `work/work_router.py` — replace inline epic parsing with detect()
- `project/stack.py` — epic fields + _entries_to_text key list update

**Skills (documentation):**
- `work-end/SKILL.md` — Step 0b epic gate, stamp verification note
- `work/SKILL.md` — Step 4 "end" epic annotation
- `work-start/SKILL.md` — Epic Overlay → Step 3d
- `work-resume/SKILL.md` — Step 9b epic context
- `work-pause/SKILL.md` — epic state recording

**Tests (new or modified):**
- `tests/test_epic_manager.py`
- `tests/test_slot_manager.py`
- `tests/test_phase_b_gate.py` (new)
- `tests/test_work_router.py`
