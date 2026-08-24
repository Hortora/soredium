# Mechanise work-end close sequence

**Issue:** #271
**Date:** 2026-08-24
**Principle:** Python drives, LLM assists. The LLM cannot skip what it cannot see.

---

## Problem

Every slot closure audit found failures caused by the LLM skipping or
partially executing mechanical steps in work-end:

| Slot | Failure | Category |
|------|---------|----------|
| 134 | Repos not switched to main before archive | LLM skip |
| 141 | Artifacts not promoted, workspaces dirty | LLM skip |
| 54 | Code not pushed to origin | LLM skip |
| 54 | Blog not promoted to public workspace | LLM skip |
| 54 | Branch deleted instead of stamped | LLM skip |
| 149 | Blog uncommitted in attic, not promoted | LLM skip |

Root cause: the LLM reads a 660-line SKILL.md and orchestrates ~20 steps.
LLMs don't reliably execute long sequences. No amount of better instructions
fixes this — the architecture is wrong.

---

## Solution: Inverted control

Replace the LLM-as-orchestrator model with Python-as-orchestrator. A single
Python script owns the close sequence. The LLM becomes a service called
when the script needs judgment.

### Current model (LLM orchestrates)

```
SKILL.md says "do steps 1-15"
LLM reads all 15, skips step 7, forgets step 12, claims success
```

### New model (Python orchestrates)

```
LLM calls work_end_orchestrator.py
  Script runs mechanical steps (push, stamp, verify...)
  Script hits judgment point (needs blog written)
  Script prints: ACTION=write_content
  Script exits

LLM reads output, writes blog, calls orchestrator again
  Script validates blog exists
  Script continues mechanical steps
  ...
  Script prints: ACTION=complete
```

The SKILL.md becomes a ~20-line dispatch loop plus ~250 lines of pre-close
context handling and reference documentation. The LLM never sees the full
step sequence, so it cannot skip steps.

---

## Architecture

### Stateless re-entrant orchestrator (D1)

`work_end_orchestrator.py` is a stateless script. Each invocation:

1. Reads `META_STATE` (from lifecycle) for the current phase and
   `.close-progress` for fine-grained position within that phase.
   - If `META_STATE` is ahead of `.close-progress` (crash between
     lifecycle transition and progress write), fast-forwards to match.
   - If `.close-progress` is ahead of `META_STATE` (stale file from a
     prior completed close), deletes it and starts fresh.
2. Runs all mechanical steps up to the next judgment point
3. Prints one `ACTION=` line with action-specific context
4. Exits

The LLM calls it repeatedly. No long-running process, no bidirectional
streaming, no watchdogs.

**Why not Claude Code Workflows:** Workflows spawn a fresh agent for each
step, losing accumulated conversation context. Work-end benefits from
context preservation — review findings inform sweep, sweep informs squash
analysis, user decisions carry forward. The re-entrant script preserves
this because the LLM maintains one continuous conversation.

### SKILL.md loop (D2)

```
loop:
  output = run("python3 work-end/work_end_orchestrator.py ...")
  parse ACTION= from output

  if ACTION=complete → print summary, done
  if ACTION=user_input → present CONTEXT to user, collect response
  if ACTION=review → full review cycle (code-review + branch-audit + forcing function)
  if ACTION=review_rebase → code-review on DIFF_RANGE only
  if ACTION=sweep_config → present toggle UI, report selections via sweep_selected=
  if ACTION=squash → classify commits per repo, write .squash-plan-<repo>.json
  if ACTION=verify_recover → present verify failures, offer recovery
  if ACTION in [forage, protocol, update_claude_md, impl_doc_sync,
                adr, write_content, trajectory] → invoke the named skill
  go to loop
```

The LLM has no knowledge of the full step sequence. It sees one
instruction at a time. The orchestrator decides what's next.

### Context resolution (pre-close)

Step 1 context resolution (`work_end_context.py`, precondition handling,
queue gate, dirty-tree protocol) remains in the SKILL.md as pre-close
setup. The orchestrator's close sequence starts after context is resolved
and `closing:review` is entered. This separation keeps the orchestrator
focused on the close sequence — context resolution is interactive and
benefits from SKILL.md-level handling.

---

## Action types (D3, D4)

### Core actions

| Action | LLM does | Lifecycle state | Validation |
|--------|----------|----------------|------------|
| `review` | code-review + branch-audit + loose-ends + forcing function | `closing:review` | `findings.jsonl`: all findings status != `open` |
| `review_rebase` | code-review on conflict-resolution diff only | `closing:promoted` | `findings.jsonl`: all findings status != `open` |
| `sweep_config` | Present toggle UI, report selections | `closing:review` | `sweep_selected=` argument provided on next orchestrator call |
| `forage` | Invoke forage SWEEP | `closing:review` | Garden entry files created (or explicit skip) |
| `protocol` | Invoke protocol SWEEP | `closing:review` | Protocol files created (or explicit skip) |
| `update_claude_md` | Invoke update-claude-md | `closing:review` | CLAUDE.md timestamp (or no changes needed) |
| `impl_doc_sync` | Invoke implementation-doc-sync | `closing:review` | Docs synced (or no changes needed) |
| `adr` | Invoke adr | `closing:review` | ADR file created (or explicit skip) |
| `write_content` | Invoke write-content (diary) | `closing:review` | Blog file exists, frontmatter valid, word count > 100 |
| `squash` | Classify commits per repo | `closing:promoted` | `.squash-plan-<repo>.json` exists, valid JSON |
| `trajectory` | Draft enrichment notes | `closing:promoted` | Enrichment recorded (or skip via `skip_step=` protocol) |
| `verify_recover` | Present verify failures, offer recovery | When verify fails | Re-run verify passes |
| `user_input` | Parameterised via CONTEXT= | `closing:stamped` | Response received |

### `user_input` contexts

| CONTEXT= | What LLM presents |
|----------|-------------------|
| `arc42_scan` | ARC42 stale scan results, offer fixes |
| `session_rename` | Suggest descriptive session name |
| `garden_feedback` | Assess GE-ID relevance per category |
| `notes` | Prompt user for notes, append to NOTES.md |
| `step_failed` | Judgment step failed after 3 retries — skip/retry/abort? |
| `rebase_conflict` | Rebase conflict needs manual resolution |

### Conditional actions

- **Post-rebase re-review:** If rebase had conflicts, orchestrator yields
  `ACTION=review_rebase` with `DIFF_RANGE=` scoped to conflict resolution
  commits. Distinct action type — LLM runs code-review only (no branch-audit,
  loose-ends, or forcing function).
- **`verify_recover`:** Fires only when `verify_slot_close.py` returns
  `VERIFIED=no`. Not part of the normal sequence.
- **Sweep sub-steps:** Conditional on `sweep_config` selections. User
  toggles items off → orchestrator skips those actions entirely.

### Lifecycle state mapping

| Lifecycle state | Actions that fire | Event to advance | Evidence required |
|---|---|---|---|
| `closing:review` | review, sweep_config, [selected sweep sub-steps] | `review_pass` | `review_result` |
| `closing:verified` | promote (mechanical) | `promote_pass` | `promoted_files`, `target_repos` |
| `closing:promoted` | trajectory (non-blocking), squash, rebase (mechanical), land (mechanical) | `push_pass` → `merge_pass` → `stamp_pass` | See per-event below |
| `closing:stamped` | user_input (cleanup items) | `cleanup_pass` or `cleanup_main` | See per-event below |

**Per-event evidence:**

| Event | Evidence keys | Source |
|---|---|---|
| `push_pass` | `pushed_repos`, `pushed_shas` | `land` output `LANDED=yes`, `LANDED_SHA=<sha>` (branch mode); `LANDED_SHAS=repo:sha,...` (slot mode via merge-slot). Orchestrator derives `pushed_repos` from successful completion + `.execute-progress` entries. |
| `merge_pass` | `landed_shas`, `verified_on_main` | Orchestrator derives from `LANDED_SHA=` output and successful exit code (land_flow verifies via `merge-base --is-ancestor` internally, emits `PUSH_VERIFY_WARN=` only on failure). Main mode: empty dicts. |
| `stamp_pass` | `stamp_shas` | Orchestrator derives from `.execute-progress` entries (`repo:branch=stamped`) written by `land_flow._stamp_repo()`. No stdout key — stamp status is tracked in the progress file. Main mode: empty dict. |
| `cleanup_pass` | `repos_on_main`, `work_items_ended` | `checkout-main` result + `close-issues` result |
| `cleanup_main` | `work_items_ended` | `close-issues` result |

`closing:pushed` and `closing:merged` are transient — rapid succession
after land completes. The orchestrator fires lifecycle events but does
not yield LLM actions between them. In main mode, `merge_pass` and
`stamp_pass` fire with empty evidence dicts (nothing was merged or stamped).

---

## Protocol format (D7)

KEY=VALUE lines with action-specific context. The orchestrator provides
values the LLM needs to execute THIS action correctly. Does not repeat
generic context already in the conversation.

### Examples

```
ACTION=review
DIFF_RANGE=main..issue-271-mechanise-work-end-close
```

```
ACTION=review_rebase
DIFF_RANGE=abc123..def456
SCOPE=code-review only — skip branch-audit, loose-ends, forcing function
```

```
ACTION=sweep_config
ITEMS=forage:on,protocol:on,update_claude_md:on,impl_doc_sync:on,adr:on,write_content:on
```

```
ACTION=write_content
BRANCH_SUMMARY=Mechanised work-end close sequence with Python orchestrator
ISSUE=271
```

```
ACTION=squash
REPOS=soredium
PLAN_DIR=/Users/mdproctor/claude/public/cc-praxis/design
```

```
ACTION=user_input
CONTEXT=step_failed
STEP=write_content
ATTEMPTS=3
REASON=no blog file found in workspace/blog/
```

```
ACTION=complete
SUMMARY=Close complete. 14 mechanical steps, 8 judgment steps. All verified.
```

### LLM response protocol

The LLM does not pass structured responses back to the orchestrator.
It simply calls the orchestrator again. The orchestrator validates by
checking evidence (files, git state, findings.jsonl), not by reading
LLM output.

Exceptions — the LLM passes these structured arguments on specific
orchestrator calls:

| Argument | After action | Purpose |
|----------|-------------|---------|
| `sweep_selected=forage,protocol,...` | `sweep_config` | User's toggle selections |
| `skip_step=<name>` | `user_input CONTEXT=step_failed` | Skip failed judgment step |
| `abort=yes` | User requests abort | Fire `abort_close`, exit sequence |
| `conflict_resolved=yes` | `user_input CONTEXT=rebase_conflict` | Signal conflict resolved |

Example:

```
python3 work-end/work_end_orchestrator.py ... sweep_selected=forage,protocol,write_content
```

---

## Validation stack (D5)

### Primary: mechanical heuristics

| Action | Validation check |
|--------|-----------------|
| `review` | `findings.jsonl` exists, all entries have status != `open` |
| `forage` | Garden entry files created since step start, OR `skip_step=forage` |
| `protocol` | Protocol files created since step start, OR `skip_step=protocol` |
| `update_claude_md` | CLAUDE.md mtime changed, OR diff shows no changes needed |
| `impl_doc_sync` | Docs directory mtime changed, OR diff shows no changes needed |
| `adr` | ADR file created in workspace `adr/`, OR `skip_step=adr` |
| `write_content` | Blog file exists in workspace `blog/`, frontmatter valid, word count > 100 |
| `squash` | `.squash-plan-<repo>.json` exists, valid JSON, has expected fields |
| `trajectory` | Enrichment DB updated, OR `skip_step=trajectory` |

### Secondary: Haiku semantic validation (optional)

Haiku via Vertex AI, using Application Default Credentials. Called only
when:
- The primary heuristic check passes (file exists, structure valid)
- The action type is write-content or ADR (content quality matters)
- Vertex AI is available (graceful skip when offline, CI, quota exhaustion)

```python
def haiku_validate(prompt: str, content: str) -> ValidateResult:
    try:
        client = AnthropicVertex(region="us-east5", project_id=...)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": f"{prompt}\n\n{content}"}]
        )
        # parse yes/no + reason
    except Exception:
        return ValidateResult(valid=True, reason="Haiku unavailable — heuristic-only")
```

The close sequence never blocks on Haiku availability.

---

## Progress tracking and crash recovery (D8)

### File format

`.close-progress` — flat KEY=VALUE, one entry per line. Step names are
unique keys; additional step metadata uses `<step>_<attr>` compound keys:

```
review=done
sweep_config=done
sweep_selected=forage,protocol,write_content
forage=done
protocol=done
write_content=pending
write_content_attempt=2
promote=done
rebase=done
squash=done
land=done
```

This is the same format as `.execute-progress` (unique keys, one per line).

**Location:** workspace root, alongside `.execute-progress`.

### Atomic writes

Drop-in replacement for the existing `write_progress(path, key, value)`
signature, adding `os.replace()` for atomic write-then-rename:

```python
def write_progress(progress_path: Path, key: str, value: str) -> None:
    progress = read_progress(progress_path)
    progress[key] = value
    lines = [f"{k}={v}" for k, v in progress.items()]
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = progress_path.with_suffix('.tmp')
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, progress_path)
```

This matches `lifecycle.py`'s `write_state()` pattern. The existing
`write_progress()` in `work_end_execute.py` and `_write_progress()` in
`land_flow.py` use unsafe read-modify-write (`Path.write_text()` truncates
first) — both must be fixed to use atomic write-then-rename with the
same `(path, key, value)` signature.

### Crash recovery

On restart, the orchestrator reads `.close-progress` and skips completed
steps. The lifecycle state machine provides the major phase (`META_STATE`
from ctx.py). `.close-progress` provides fine-grained position within
a phase.

| Crash point | Recovery |
|-------------|----------|
| Mid-mechanical step | Re-run from last completed sub-step |
| After yielding ACTION but before LLM acts | Re-yield the same action |
| After LLM acts but before validation | Validate on next call |
| Between validation and progress write | Atomic write-then-rename eliminates this window |

### Concurrent protection (D12)

The lifecycle state machine's compare-and-swap in `commit_transition()`
prevents concurrent sessions. A second session attempting `work_end`
while one is in progress fails at the lifecycle level — no file-level
locking on `.close-progress` is needed.

---

## Error and retry policy (D10)

### Two-tier policy

**Judgment steps** (review, sweep sub-steps, squash, trajectory):
1. Re-yield with `REASON=` explaining what failed validation
2. Max 3 attempts
3. After 3 failures: yield `ACTION=user_input CONTEXT=step_failed STEP=<name>`
4. User decides: skip, retry, or abort
5. Never silently skip judgment work

**Mechanical steps** (push, merge, stamp, promotion):
1. Re-yield with `REASON=`
2. Max 3 attempts
3. After 3 failures: skip with warning, record in `.close-progress`
4. `verify_slot_close.py` catches gaps downstream

### Abort flow

The LLM can pass `abort=yes` to the orchestrator. The orchestrator:

1. Checks current lifecycle state — abort is valid from `closing:review`
   or `closing:verified` only
2. Deletes `.close-progress` and `.execute-progress` — stale progress
   from an aborted attempt must not confuse a subsequent `work_end`.
   This matches lifecycle's `clear_closing_markers` effect, which already
   handles lifecycle state cleanup but does not know about these files.
3. Fires `abort_close` lifecycle transition → returns to `active`
4. Yields `ACTION=complete SUMMARY=Aborted — returned to active state`

Post-promotion states (`closing:promoted` onward) are forward-only.
The orchestrator rejects `abort=yes` with an error message explaining
why abort is unavailable.

### Rationale

`verify_slot_close.py` checks: merged, stamped, landing SHA, pushed,
issues closed, landed marker, original sync, archive status. It does
NOT check: review completion, sweep outputs, trajectory, findings
resolution. Silently skipping judgment steps leaves gaps no downstream
gate catches.

---

## Slot mode (D9)

Single orchestrator, same sequence for slots and non-slots. The existing
scripts handle internal mode differences (two-hop transport, `.landed`
marker). The orchestrator has routing conditionals at 5 decision points:

| Point | Slot mode | Non-slot mode |
|-------|-----------|---------------|
| Phase A complete marker | Write `.phase-a-complete` | Skip |
| Land script | `slot_manager.py merge-slot` | `work_end_execute.py land` |
| Verify args | `slot_dir=<SLOT_PATH>` | Omit |
| Archive | `work_end_execute.py archive-slot` | Skip |
| Scaffold cleanup | Keep `.plan` (main mode: drained) | Remove `.plan` |

This is routing — which script, which arguments — not duplicated
business logic.

### Main mode routing

When `ON_MAIN=yes` (from ctx.py), the orchestrator applies a third
routing path alongside branch mode and slot mode:

| Point | Main mode difference |
|-------|---------------------|
| Review diff base | `drained-sha` from `.plan` (or `project-sha` if first close) |
| Rebase | Skip |
| Squash | Skip |
| Land | Push only (no merge, no stamp) |
| Lifecycle after land | `push_pass` only; `merge_pass` and `stamp_pass` fired with empty evidence dicts |
| Cleanup transition | `cleanup_main` → `drained` (not `cleanup_pass` → `idle`) |
| Scaffold cleanup | Keep `.plan` (state is `drained`), remove only `JOURNAL.md` |
| Checkout main | Skip (already there) |

Main mode fires `merge_pass` and `stamp_pass` with empty evidence
(`{"landed_shas": {}, "verified_on_main": {}}` and `{"stamp_shas": {}}`)
to traverse the lifecycle state machine to `closing:stamped`. The evidence
gates accept empty dicts — they validate that present keys have valid
values but do not require non-empty content.

---

## Forward-only Execute (D11)

Post-promotion states are forward-only. The lifecycle state machine
rejects `abort_close` from `closing:promoted` onward. Partial failures
recover by retrying the failed step forward, never by rolling back.

Rolling back pushed content requires force-push to shared remotes —
more dangerous than forward completion. `verify_slot_close.py` detects
incomplete forward progress. `.execute-progress` enables retry from the
last completed sub-step.

---

## Existing scripts (D6)

The orchestrator calls 6 script entry points which internally delegate
to ~11 more. They are the proven mechanical layer — all remain
unmodified (except the crash-safety fix). The orchestrator adds
sequencing, evidence collection, and validation.

### Scripts called by the orchestrator (entry points and internals)

| Script | Phase | What it does |
|--------|-------|-------------|
| `work_end_context.py` | Pre-close | Context + preconditions |
| `work_end_execute.py promote` | Execute | Artifact promotion |
| `work_end_execute.py rebase` | Execute | Rebase onto base branch |
| `work_end_execute.py land` | Execute | Push + stamp (non-slot) |
| `work_end_execute.py close-issues` | Execute | Close GitHub issues |
| `work_end_execute.py archive-slot` | Close | Archive slot to attic |
| `slot_manager.py merge-slot` | Execute | Land (slot mode) |
| `verify_slot_close.py` | Verify | Defence-in-depth audit |
| `close_artifacts.py` | Execute | Called by promote internally |
| `land_branch.py` | Execute | Called by land internally |
| `land_flow.py` | Execute | Shared land flow |
| `verify_stamp.py` | Execute | Called by land internally |
| `verify_promotion.py` | Execute | Called by promote internally |
| `branch_cleanup.py` | Close | Checkout main, cleanup scaffold |
| `loose_ends_sweep.py` | Review | Loose ends detection |
| `close_report.py` | Close | Summary generation |
| `lifecycle.py` | All | State machine transitions |

### New script

| Script | Purpose |
|--------|---------|
| `work_end_orchestrator.py` | Close sequence orchestrator |

### Modified scripts (crash-safety fix)

| Script | Change |
|--------|--------|
| `work_end_execute.py` | `write_progress()` → atomic write-then-rename |
| `land_flow.py` | `_write_progress()` → atomic write-then-rename |

---

## Orchestrator sequence

The full mechanical + judgment sequence, showing what Python does silently
vs what it yields to the LLM:

```
PRE-CLOSE (SKILL.md, not orchestrator):
  work_end_context.py → preconditions → lifecycle transition to closing:review

ORCHESTRATOR SEQUENCE:

  [mechanical] close_report.py init <report-path>

Phase: closing:review
  [yield] ACTION=review → LLM runs code-review, branch-audit, forcing function
         Main mode: DIFF_RANGE uses drained-sha (or project-sha) as base
  [yield] ACTION=sweep_config → LLM presents toggle, reports selections
  [yield] ACTION=forage (if selected)
  [yield] ACTION=protocol (if selected)
  [yield] ACTION=update_claude_md (if selected)
  [yield] ACTION=impl_doc_sync (if selected)
  [yield] ACTION=adr (if selected)
  [yield] ACTION=write_content (if selected)
  [mechanical] lifecycle commit-transition: review_pass → closing:verified
    evidence={"review_result": "pass"}

Phase: closing:verified
  [mechanical] work_end_execute.py promote
  [mechanical] close_report.py record promote
  [mechanical] lifecycle commit-transition: promote_pass → closing:promoted
    evidence={"promoted_files": <from output>, "target_repos": <from output>}

Phase: closing:promoted
  [yield] ACTION=trajectory (non-blocking — skip does not block close)
  [mechanical] work_end_execute.py rebase  (skip in main mode)
  [mechanical] close_report.py record rebase
  [yield if REBASE_CONFLICT] ACTION=user_input CONTEXT=rebase_conflict
    → user resolves conflicts manually
    → LLM passes conflict_resolved=yes
    → orchestrator re-runs work_end_execute.py rebase (now succeeds)
  [yield if conflicts were resolved] ACTION=review_rebase DIFF_RANGE=<conflict-resolution-commits>
  [yield] ACTION=squash → LLM classifies commits, writes plan files  (skip in main mode)
  [mechanical] close_report.py record squash
  [mechanical] work_end_execute.py land (applies squash, pushes, stamps)
    Main mode: push only (no merge, no stamp)
  [mechanical] close_report.py record land
  [mechanical] lifecycle commit-transitions (rapid succession):
    push_pass → closing:pushed
      evidence={"pushed_repos": <list>, "pushed_shas": <dict>}
    merge_pass → closing:merged  (main mode: empty dicts)
      evidence={"landed_shas": <dict>, "verified_on_main": <dict>}
    stamp_pass → closing:stamped  (main mode: empty dicts)
      evidence={"stamp_shas": <dict>}

Phase: closing:stamped
  [yield] ACTION=user_input CONTEXT=arc42_scan (if ARC42STORIES.MD exists)
  [yield] ACTION=user_input CONTEXT=session_rename
  [yield] ACTION=user_input CONTEXT=garden_feedback (if GE-IDs in session)
  [yield] ACTION=user_input CONTEXT=notes (if .notes/ exists)

VERIFY:
  [mechanical] work_end_execute.py close-issues (if COVERS non-empty)
  [mechanical] close_report.py record close-issues
  [mechanical] verify_slot_close.py (with covers= and issue_repo= when applicable)
  [mechanical] close_report.py record verify
  [yield if failed] ACTION=verify_recover → LLM presents failures

CLOSE:
  [mechanical] work_end_execute.py archive-slot (slot mode)
  [mechanical] close_report.py record archive (slot mode)
  [mechanical] branch_cleanup.py checkout-main  (skip in main mode)
  [mechanical] branch_cleanup.py cleanup-stack <workspace> branch=<name>  (skip in main mode)
  [mechanical] branch_cleanup.py cleanup-scaffold
  [mechanical] close_report.py record scaffold-cleanup
  [mechanical] lifecycle commit-transition:
    Branch mode: cleanup_pass → idle
      evidence={"repos_on_main": <dict>, "work_items_ended": true}
    Main mode: cleanup_main → drained
      evidence={"work_items_ended": true}
    Post-commit: write_handoff is not surfaced as an orchestrator action.
    HANDOFF.md is a session-end concern handled by the session's handover
    protocol, not a close-sequence step. The current SKILL.md also does
    not consume this effect.
  [mechanical] delete .close-progress (and .close-progress.tmp if present)
  [mechanical] close_report.py render <report-path>
  [yield] ACTION=complete SUMMARY=<rendered report>
```

---

## Testing strategy

The orchestrator requires its own test suite — the risk shifts from
"LLM skips steps" (observable) to "orchestrator mis-sequences steps"
(opaque). Tests must cover:

### Orchestrator tests (`test_work_end_orchestrator.py`)

| Test | Assert |
|------|--------|
| Full sequence (branch mode) | All mechanical steps called in order, correct actions yielded |
| Full sequence (slot mode) | Routing conditionals fire correctly for 5 decision points |
| Crash recovery: resume from each progress state | Completed steps skipped, next action yielded |
| Crash recovery: `.close-progress.tmp` exists (mid-write crash) | Old `.close-progress` used, `.tmp` ignored |
| Validation: write-content produces valid blog | `ACTION=complete` after validation passes |
| Validation: write-content produces empty file | Re-yield with `REASON=` |
| Validation: 3 consecutive failures on judgment step | `ACTION=user_input CONTEXT=step_failed` |
| Validation: 3 consecutive failures on mechanical step | Skip-with-warning, continues |
| Sweep config: user deselects items | Deselected sub-steps never yielded |
| Sweep config: all items off | Jumps to post-sweep mechanical steps |
| Post-rebase conflict | `ACTION=review_rebase` with scoped `DIFF_RANGE=` |
| Verify failure | `ACTION=verify_recover` yielded |
| Concurrent session | Lifecycle `ConcurrentModification` raised |
| Main mode | Branch-specific steps skipped (rebase, squash, stamp) |
| Abort from `closing:review` | `.close-progress` + `.execute-progress` deleted, `abort_close` fires, yields `ACTION=complete SUMMARY=Aborted` |
| Abort from `closing:promoted` | Rejected with explanation, sequence continues forward |
| `skip_step=` handling | Progress updated with skip, next action yielded |
| `conflict_resolved=yes` handling | Rebase re-run succeeds, proceeds to `review_rebase` |
| Evidence dict construction | Correct keys derived from script output for each lifecycle event |
| Main mode empty evidence dicts | `merge_pass` and `stamp_pass` accept empty dicts |
| `close_report.py` integration | init → record (all steps) → render produces valid summary |
| META_STATE ahead of `.close-progress` | Fast-forwards to match lifecycle phase |
| Stale `.close-progress` (ahead of META_STATE) | File deleted, fresh sequence starts |
| `.close-progress` cleanup on normal completion | File deleted before `ACTION=complete` yielded |
| Stack cleanup (branch was paused) | `branch_cleanup.py cleanup-stack` called with correct args |
| Stack cleanup (main mode) | `cleanup-stack` step skipped |

### Crash-safety tests

| Test | Assert |
|------|--------|
| `write_progress` atomic | Process kill mid-write preserves old file |
| `write_progress` round-trip | Write then read produces identical dict |
| `.close-progress` + `.execute-progress` coexistence | Both files independent |

### Integration with existing test suites

Existing tests (`test_work_end_execute.py`, `test_land_flow.py`,
`test_verify_slot_close.py`) continue to test individual scripts.
Orchestrator tests mock script calls and test sequencing logic.

---

## Implementation order

1. **Crash-safety fix** — atomic write-then-rename in `work_end_execute.py`
   and `land_flow.py`. Low risk, immediate value, no dependency.

2. **`work_end_orchestrator.py`** — the orchestrator script with progress
   tracking, action yielding, and validation. Tests first (TDD).

3. **SKILL.md rewrite** — replace 660-line skill with ~20-line loop plus
   pre-close context handling.

4. **Haiku validation** (optional, deferred — tracked as #274) — add
   semantic validation for write-content and ADR when heuristic checks
   prove insufficient.

Step 1 can ship independently. Steps 2-3 ship together.

---

## Files changed

### New files

| File | Purpose |
|------|---------|
| `work-end/work_end_orchestrator.py` | Close sequence orchestrator |
| `tests/test_work_end_orchestrator.py` | Orchestrator test suite |

### Modified files

| File | Change |
|------|--------|
| `work-end/SKILL.md` | Rewrite to ~20-line dispatch loop + ~250-line pre-close and reference |
| `work-end/work_end_execute.py` | `write_progress()` → atomic write-then-rename |
| `work-end/land_flow.py` | `_write_progress()` → atomic write-then-rename |
| `work-end/close_report.py` | Update STEP_ORDER, STEP_LABELS, `_format_detail()` for orchestrator step names (`promote`, `land`, `close-issues`, `verify`) |

### Unchanged files

All other existing work-end scripts remain unchanged. The orchestrator
calls them as-is.

---

## Risks

**Orchestrator sequencing bugs:** The orchestrator replaces one failure
class (LLM skip) with another (script mis-sequence). Mitigated by TDD,
the orchestrator test suite, and `verify_slot_close.py` as defence-in-depth.

**Haiku API availability:** Graceful degradation — heuristic-only validation
when Vertex AI is unavailable. Close sequence never blocks on API.

**Progress file corruption:** Atomic write-then-rename eliminates the
truncation-then-write crash window. Same pattern as `lifecycle.py`.

**Context loss across yield points:** The LLM's conversation context
persists across orchestrator calls. Forage discoveries inform protocol,
protocol informs write-content. No context is lost.

---

## References

- Issue #271 — audit evidence (8 failures across 4 slots)
- `docs/specs/issue-151-mechanise-llm-steps/2026-08-03-mechanise-llm-steps-design.md` — prior mechanisation spec
- `docs/specs/2026-08-05-work-end-restructure-and-slot-audit-design.md` — work-end restructure spec
- `project/lifecycle.py` — state machine, `write_state()` atomic pattern
- `work-end/work_end_execute.py` — existing Execute orchestrator, `write_progress()` crash-safety issue
- `work-end/land_flow.py` — shared land flow, `_write_progress()` crash-safety issue
- `work-end/verify_slot_close.py` — verification gate (check inventory)
- GE-20260821-ebba3b — work-end atomicity and stamp failures
- GE-20260821-e9c59e — worklog.db as lifecycle source of truth
- `docs/protocols/externalised-scripts-require-tests.md` — test requirements
- `docs/protocols/evidence-before-claims.md` — verification discipline
- [Oracle: AI Agent Loop Architecture](https://blogs.oracle.com/developers/what-is-the-ai-agent-loop-the-core-architecture-behind-autonomous-ai-systems)
- [Google Cloud: Agentic AI Design Patterns](https://docs.google.com/architecture/choose-design-pattern-agentic-ai-system)
- [GitHub: AgenticStateMachines](https://github.com/adamterlson/AgenticStateMachines) — FSM patterns for agent control
- [Claude Code Workflows](https://code.claude.com/docs/en/workflows) — deterministic orchestration precedent
