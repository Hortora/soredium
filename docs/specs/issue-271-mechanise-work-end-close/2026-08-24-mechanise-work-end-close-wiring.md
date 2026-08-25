# Mechanise work-end: Mechanical Wiring, Rollout, and Audit

**Issue:** #271 (continuation of #275)
**Date:** 2026-08-24
**Prior spec:** `2026-08-24-mechanise-work-end-close-design.md` (architecture, 12 decisions)
**This spec:** Mechanical wiring, SKILL.md rewrite, recovery, rollout, audit (decisions D13-D18)
**Pinned SKILL.md SHA:** `151b7a8` (revert commit — production baseline)

---

## Relationship to prior spec

The prior spec established the architecture:
- **D1:** Stateless re-entrant Python orchestrator
- **D2:** Control inversion — LLM sees one action at a time
- **D3:** Action granularity — typed actions, fine-grained progress
- **D4:** Sweep ownership — orchestrator-sequenced, LLM-executed
- **D5:** Validation stack — mechanical heuristics primary
- **D6:** Existing scripts reused as-is
- **D7:** Protocol format — KEY=VALUE with action-specific context
- **D8:** Progress file format — atomic write-then-rename
- **D9:** Slot mode — unified sequence with routing conditionals
- **D10:** Error and retry policy — two-tier (judgment escalates, mechanical skips)
- **D11:** Forward-only Execute — no rollback post-promotion
- **D12:** Concurrent session protection — lifecycle CAS

All 12 decisions are settled. This spec does not reopen them.

The first implementation attempt (c9cd4d8) was reverted (151b7a8) because:
1. All mechanical steps were stubbed — marked done without calling scripts
2. Slot mode was entirely unwired — accepted arguments but never used them
3. Cross-session state recovery was nonexistent

This spec closes those gaps with:
- **D13:** Step definition tables (exact CLI, arguments, output keys)
- **D14:** Capability matrix pinned to SHA `151b7a8` (no capability loss)
- **D15:** Evidence-based recovery (local/network split)
- **D16:** Verbatim action handler extraction
- **D17:** Shadow mode rollout with fallback telemetry
- **D18:** Scripted dry-run audit

---

## 1. Capability matrix

Every discrete capability from the current SKILL.md (662 lines at SHA `151b7a8`),
mapped to its target in the new system. Before implementation, diff current
SKILL.md against this SHA and add any new capabilities.

### Pre-close (stays in SKILL.md)

| ID | Capability | SKILL.md source | Target |
|----|-----------|----------------|--------|
| C1 | Path resolution via ctx.py | Path Resolution | pre-close |
| C2 | Lifecycle transient state resolution (scaffolded, transitioning → active) | Lifecycle §On entry | pre-close |
| C3 | Lifecycle work_end transition → closing:review | Lifecycle §Then fire | pre-close |
| C4 | Resume from closing:* state (offer to continue) | Lifecycle table row 4 | pre-close |
| C5 | Main-mode detection and routing table | Main-mode detection | pre-close |
| C6 | Main-mode diff base (drained-sha or project-sha) | Main-mode §diff base | pre-close |
| C7 | work_end_context.py invocation | Step 1 | pre-close |
| C8 | Branch alignment check (hard stop) | Step 1 preconditions | pre-close |
| C9 | Clean tree check + DIRTY-TREE-PROTOCOL | Step 1 preconditions | pre-close |
| C10 | Meta existence graceful degradation | Step 1 preconditions | pre-close |
| C11 | Queue gate (mid-queue detection, confirm-partial redirect) | Step 1 §Queue gate | pre-close |
| C12 | Issue-complete emission (complete_active_issue) | Step 1 §Issue-complete | pre-close |
| C13 | Abort from closing:review or closing:verified only | Lifecycle §Abort | pre-close |

### Review (ACTION=review handler in SKILL.md)

| ID | Capability | SKILL.md source | Target |
|----|-----------|----------------|--------|
| C14 | Code review on branch diff | Step 2.1 | handler:review |
| C15 | Security-audit suppression during work-end | Step 2.1 §suppression | handler:review |
| C16 | Findings persistence to findings.jsonl after code-review | Step 2.1 last para | handler:review |
| C17 | Branch audit (four dimensions: Conformance, Coherence, Structure, Robustness) | Step 2.2 | handler:review |
| C18 | Findings appended after each dimension (not batched) | Step 2.2 last para | handler:review |
| C19 | Loose ends sweep with cycle_start filter | Step 2.3 | handler:review |
| C20 | LLM supplements with conversation-context loose ends | Step 2.3 last para | handler:review |
| C21 | Forcing function — read all open findings | Step 2.4 | handler:review |
| C22 | Grouped presentation by category (AUDIT, REVIEW, LOOSE-END, HYGIENE, prior) | Step 2.4 template | handler:review |
| C23 | Triage filtering (only open findings) | Step 2.4 §Triage | handler:review |
| C24 | Resolution options: Fix / File / Dismiss | Step 2.4 table | handler:review |
| C25 | Severity constraints: CRITICAL cannot be dismissed | Step 2.4 severity table | handler:review |
| C26 | Re-review after fixes (code-review only, scoped to fix commits) | Step 2.4 §Re-review | handler:review |
| C27 | Batch operations (file all, file each, dismiss all NOTEs) | Step 2.4 §Batch | handler:review |
| C28 | Immediate persistence of each resolution to findings.jsonl | Step 2.4 §persistence | handler:review |
| C29 | Budget limits are not gates (warning only, surface in summary) | Step 2 §Budget | handler:review |

### Sweep config (ACTION=sweep_config handler in SKILL.md)

| ID | Capability | SKILL.md source | Target |
|----|-----------|----------------|--------|
| C30 | Toggle UI with all items ON | Step 3 template | handler:sweep_config |
| C31 | NEVER-RECOMMEND-SKIPPING constraint | Step 3 gate | handler:sweep_config |
| C32 | Session-bound items cannot be deferred (forage, write-content) | Step 3 gate | handler:sweep_config |
| C33 | Run order: forage → protocol → update-claude-md → impl-doc-sync → adr → write-content | Step 3 §Run order | orchestrator (sequence) |
| C34 | Journal validation (section_drift, unanchored_entries) | Step 3 §Journal | handler:sweep_config |
| C35 | Slot mode per-repo sweep (protocol/update-claude-md/impl-doc-sync per repo) | Step 3 §Slot mode | orchestrator (routing) |
| C36 | Session-bound items run once after per-repo loop | Step 3 §Slot mode | orchestrator (routing) |

### Sweep sub-steps (individual ACTION handlers)

| ID | Capability | SKILL.md source | Target |
|----|-----------|----------------|--------|
| C37 | Forage SWEEP invocation | Step 3 item 1 | handler:forage |
| C38 | Protocol SWEEP invocation | Step 3 item 1 | handler:protocol |
| C39 | update-claude-md invocation | Step 3 item 3 | handler:update_claude_md |
| C40 | implementation-doc-sync invocation | Step 3 item 3 | handler:impl_doc_sync |
| C41 | ADR invocation | Step 3 item 2 | handler:adr |
| C42 | write-content invocation (last, synthesises narrative) | Step 3 item 4 | handler:write_content |

### Execute (orchestrator mechanical + judgment handlers)

| ID | Capability | SKILL.md source | Target |
|----|-----------|----------------|--------|
| C43 | Promote artifacts (work_end_execute.py promote) | Step 4.1 | orchestrator |
| C44 | Multi-repo slot dedup (each workspace promoted once) | Step 4.1 §dedup | orchestrator |
| C45 | review_pass lifecycle transition | Step 4 lifecycle table | orchestrator |
| C46 | promote_pass lifecycle transition | Step 4 lifecycle table | orchestrator |
| C47 | Trajectory capture (enrichment.py trajectory + upsert) | Step 4.1b | handler:trajectory |
| C48 | Trajectory is non-blocking | Step 4.1b §4 | handler:trajectory |
| C49 | Rebase (work_end_execute.py rebase) | Step 4.2 | orchestrator |
| C50 | Rebase conflict → user resolves, re-runs | Step 4.2 | handler:user_input(rebase_conflict) |
| C51 | Post-rebase re-review (code-review only, scoped diff) | Step 4.2 §Post-rebase | handler:review_rebase |
| C52 | Post-rebase mini-gate (Fix/File/Dismiss, severity constraints) | Step 4.2 §Post-rebase | handler:review_rebase |
| C53 | Squash analysis per repo (writes .squash-plan-<repo>.json) | Step 4.3 | handler:squash |
| C54 | Squash skips repos with existing plan files (restart safety) | Step 4.3 | handler:squash |
| C55 | Slot mode marker write (.phase-a-complete) | Step 4.3 §Slot mode | orchestrator |
| C56 | Land — branch mode (work_end_execute.py land) | Step 4.4 §Branch | orchestrator |
| C57 | Land — slot mode (slot_manager.py merge-slot) | Step 4.4 §Slot | orchestrator |
| C58 | Slot mode requires .phase-a-complete marker | Step 4.4 §Slot | orchestrator |
| C59 | push_pass, merge_pass, stamp_pass rapid succession | Step 4.4 §Lifecycle | orchestrator |

### Verify and close issues (orchestrator mechanical)

| ID | Capability | SKILL.md source | Target |
|----|-----------|----------------|--------|
| C60 | verify_slot_close.py invocation | Step 5 | orchestrator |
| C61 | Per-repo checks (merged, stamped, landing SHA, main pushed) | Step 5 | orchestrator |
| C62 | Workspace stamp check | Step 5 | orchestrator |
| C63 | Slot mode checks (slot_dir=, .landed, original sync, archive) | Step 5 §Slot mode | orchestrator |
| C64 | VERIFIED=no hard gate — blocks Step 6 | Step 5 §Hard gate | orchestrator |
| C65 | Recovery offer on verify failure | Step 5 §Hard gate | handler:verify_recover |
| C66 | cleanup_pass lifecycle (branch mode → idle) | Step 5 last para | orchestrator |
| C67 | cleanup_main lifecycle (main mode → drained) | Step 5 last para | orchestrator |
| C68 | close-issues invocation (work_end_execute.py close-issues) | Step 5b | orchestrator |
| C69 | CLOSED=N output parsing | Step 5b | orchestrator |
| C70 | Close-issues error retry | Step 5b | orchestrator |
| C71 | Verify re-run with covers= and issue_repo= | Step 5b §Verify gate | orchestrator |

### Close (orchestrator mechanical + judgment handlers)

| ID | Capability | SKILL.md source | Target |
|----|-----------|----------------|--------|
| C72 | Archive slot (work_end_execute.py archive-slot) | Step 6.1 | orchestrator |
| C73 | Archive force=yes option | Step 6.1 | orchestrator |
| C74 | Checkout main (branch_cleanup.py checkout-main) | Step 6.2 | orchestrator |
| C75 | Scaffold cleanup — branch mode (removes .plan + JOURNAL.md) | Step 6.2b §Branch | orchestrator |
| C76 | Scaffold cleanup — main mode (keeps .plan, removes JOURNAL.md) | Step 6.2b §Main | orchestrator |
| C77 | Stack cleanup (.pause-stack removal) | Step 6.3 | orchestrator |
| C78 | ARC42 stale scan | Step 6.4 | handler:user_input(arc42_scan) |
| C79 | Session rename suggestion | Step 6.5 | handler:user_input(session_rename) |
| C80 | Garden retrieval feedback (5-level relevance scale) | Step 6.6 | handler:user_input(garden_feedback) |
| C81 | Propagated entries from HANDOFF.md | Step 6.6 §2 | handler:user_input(garden_feedback) |
| C82 | Grouped gardenFeedback calls | Step 6.6 §5 | handler:user_input(garden_feedback) |
| C83 | MCP unavailability graceful skip | Step 6.6 §6 | handler:user_input(garden_feedback) |
| C84 | Session close summary | Step 6.7 | orchestrator (via close_report) |
| C85 | Notes — surface recent section, offer append | Step 6.8 | handler:user_input(notes) |
| C86 | Notes — commit to orphan notes branch | Step 6.8 | handler:user_input(notes) |

### Hard gates and constraints (stay in SKILL.md preamble)

| ID | Capability | SKILL.md source | Target |
|----|-----------|----------------|--------|
| C87 | Review mandatory before any push | HARD-GATE §1 | constraint |
| C88 | Doc sync mandatory (default ON) | HARD-GATE §2 | constraint |
| C89 | Main-branch mutations through work-end only | HARD-GATE §3 | constraint |
| C90 | Never defer work-end to another session | HARD-GATE §4 | constraint |
| C91 | Post-promotion states are forward-only | Lifecycle §Abort + D11 | constraint |
| C92 | Red flags table (5 rationalisation patterns) | Red Flags table | constraint |
| C93 | Common pitfalls table (8 anti-patterns) | Common Pitfalls | constraint |

**Total: 93 capabilities. None dropped.**

---

## 2. Step definition tables

Each step the orchestrator executes. Format per D13: exact CLI, output
keys, success/failure, evidence, mode routing, progress key.

### Mechanical steps

```
Step: report_init
Phase: closing:review
Type: mechanical
Script: python3 work-end/close_report.py init <REPORT_PATH>
Output keys: INIT=yes | ERROR=<msg>
Success: INIT=yes
Failure: ERROR → retry (max 3), then skip-with-warning
Evidence: none (no lifecycle transition)
Slot routing: identical
Main routing: identical
Progress key: report_init=done
```

```
Step: promote
Phase: closing:verified
Type: mechanical
Script: python3 work-end/work_end_execute.py promote workspace=$WS project=$PROJ branch=$BRANCH
Output keys: PROMOTED=yes | SKIPPED=already promoted | ERROR=PROMOTE_FAILED
  Forwarded from close_artifacts.py: WORKSPACE_PROMOTED=<count>, PROJECT_PROMOTED=<count>
Success: PROMOTED=yes
Failure: ERROR → retry (max 3), then skip-with-warning
Evidence for promote_pass: see §2.1 evidence derivation
Slot routing: deduplicates per workspace (C44)
Main routing: identical
Progress key: promote=done
```

```
Step: report_promote
Phase: closing:verified
Type: mechanical
Script: python3 work-end/close_report.py record $REPORT_PATH step=promote promoted_files=$PROMOTED_FILES target_repos=$TARGET_REPOS
Output keys: RECORDED=promote
Success: RECORDED=promote
Failure: skip-with-warning (non-critical)
Evidence: none
Slot routing: identical
Main routing: identical
Progress key: report_promote=done
```

```
Step: rebase
Phase: closing:promoted
Type: mechanical
Script: python3 work-end/work_end_execute.py rebase project=$PROJ branch=$BRANCH base_branch=$BASE
Output keys: REBASED=yes, REBASE_REMOTE=<remote> | ERROR=REBASE_CONFLICT | ERROR=<msg>
Success: REBASED=yes
Failure: ERROR=REBASE_CONFLICT → yield ACTION=user_input CONTEXT=rebase_conflict; other ERROR → retry (max 3)
Evidence: none (no lifecycle transition at this point)
Slot routing: identical (rebase runs per-repo internally)
Main routing: SKIP (C5 — main mode skips rebase)
Progress key: rebase=done
Skip condition: on_main=yes
```

```
Step: report_rebase
Phase: closing:promoted
Type: mechanical
Script: python3 work-end/close_report.py record $REPORT_PATH step=rebase branch=$BRANCH base=$BASE [conflicts=yes]
Output keys: RECORDED=rebase
Success: RECORDED=rebase
Failure: skip-with-warning
Evidence: none
Slot routing: identical
Main routing: SKIP
Progress key: report_rebase=done
Skip condition: on_main=yes
```

```
Step: report_squash
Phase: closing:promoted
Type: mechanical
Script: python3 work-end/close_report.py record $REPORT_PATH step=squash before=$BEFORE after=$AFTER strategy=$STRATEGY
  Variable sources: orchestrator reads .squash-plan-<repo>.json (written by the squash judgment step).
    $BEFORE = count of commits before squash (from plan's "commits" array length or git log count)
    $AFTER = count after squash (from plan's "groups" array length)
    $STRATEGY = squash strategy (from plan's "strategy" field, e.g., "semantic", "single")
    For multi-repo slots: aggregate across repos (sum of before/after, strategy from primary repo).
    If plan files are missing or unreadable, use before=? after=? strategy=unknown.
Output keys: RECORDED=squash
Success: RECORDED=squash
Failure: skip-with-warning
Evidence: none
Slot routing: identical
Main routing: SKIP
Progress key: report_squash=done
Skip condition: on_main=yes
```

```
Step: write_marker
Phase: closing:promoted
Type: mechanical
Script: python3 work-end/work_end_execute.py write-marker slot_path=$SLOT_PATH branch=$BRANCH
Output keys: MARKER_WRITTEN=<path> | ERROR=<msg>
Success: MARKER_WRITTEN is non-empty
Failure: ERROR → retry (max 3), report and offer retry
Evidence: none
Slot routing: SLOT ONLY
Main routing: SKIP
Progress key: write_marker=done
Skip condition: in_slot=no
```

```
Step: land
Phase: closing:promoted
Type: mechanical
Script (branch mode): python3 work-end/work_end_execute.py land project=$PROJ branch=$BRANCH base_branch=$BASE workspace=$WS
Script (slot mode): python3 work-slot/slot_manager.py merge-slot $FAMILY_ROOT slot=$SLOT_NUM
Script (main mode): (internal) orchestrator pushes directly via subprocess:
  git -C $PROJ push origin main && git -C $WS push origin main
  No merge, no stamp — work was done on main. Matches SKILL.md production baseline.
  cmd_land is NOT used (it runs the full merge+push+stamp flow, which is wrong for main).
Output keys (branch): LANDED=yes, LANDED_SHA=<sha> | ERROR=<msg>
Output keys (slot): LANDED_SHAS=<repo:sha,...> | ERROR=<msg>
Output keys (main): PUSHED=yes (emitted by orchestrator) | ERROR=<msg>
Success: LANDED=yes or LANDED_SHAS non-empty or PUSHED=yes
Failure: ERROR → retry (max 3), then yield ACTION=verify_recover
Evidence for push_pass: see §2.1 evidence derivation
Evidence for merge_pass: see §2.1 evidence derivation (main mode: empty dicts)
Evidence for stamp_pass: see §2.1 evidence derivation (main mode: empty dict)
Slot routing: calls merge-slot, requires .phase-a-complete (C58)
Main routing: push only, no merge/stamp; merge_pass and stamp_pass fire with empty evidence
Progress key: land=done
```

```
Step: report_land
Phase: closing:promoted
Type: mechanical
Script: python3 work-end/close_report.py record $REPORT_PATH step=land landed_sha=$LANDED_SHA pushed_repos=$PUSHED_REPOS
Output keys: RECORDED=land
Success: RECORDED=land
Failure: skip-with-warning
Evidence: none
Slot routing: identical
Main routing: identical
Progress key: report_land=done
```

```
Step: close_issues
Phase: closing:stamped
Type: mechanical
Script: python3 work-end/work_end_execute.py close-issues repo=$OWNER_REPO covers=$COVERS
Output keys: CLOSED=<N> | ERROR=<msg>
Success: CLOSED matches count of COVERS
Failure: ERROR → retry (max 3), then skip-with-warning
Evidence: none (consumed by cleanup_pass)
Slot routing: identical
Main routing: identical
Progress key: close_issues=done
Skip condition: covers is empty (no_covers)
```

```
Step: report_close_issues
Phase: closing:stamped
Type: mechanical
Script: python3 work-end/close_report.py record $REPORT_PATH step=close-issues closed=$CLOSED
Output keys: RECORDED=close-issues
Success: RECORDED=close-issues
Failure: skip-with-warning
Evidence: none
Slot routing: identical
Main routing: identical
Progress key: report_close_issues=done
Skip condition: covers is empty
```

```
Step: verify
Phase: closing:stamped
Type: mechanical
Script (branch/slot): python3 work-end/verify_slot_close.py $PROJ branch=$BRANCH workspace=$WS [covers=$COVERS] [issue_repo=$OWNER_REPO] [slot_dir=$SLOT_PATH]
Script (main): (internal) orchestrator verifies push only — verify_slot_close.py checks stamp/merge
  which don't apply to main mode. Orchestrator checks:
    1. git -C $PROJ log origin/main..main --oneline  → must be empty (all pushed)
    2. git -C $WS log origin/main..main --oneline    → must be empty (all pushed)
    3. If covers: gh issue view --json state for each issue → must be CLOSED
  Emits VERIFIED=yes if all pass, VERIFIED=no otherwise.
Output keys: VERIFIED=yes|no, per-check PASS/FAIL lines
Success: VERIFIED=yes
Failure: VERIFIED=no → yield ACTION=verify_recover with per-check failures
Evidence: none (consumed by cleanup_pass)
Slot routing: adds slot_dir=$SLOT_PATH
Main routing: orchestrator handles directly (verify_slot_close.py checks stamp/merge which are N/A)
Progress key: verify=done
```

```
Step: report_verify
Phase: closing:stamped
Type: mechanical
Script: python3 work-end/close_report.py record $REPORT_PATH step=verify verified=$VERIFIED
Output keys: RECORDED=verify
Success: RECORDED=verify
Failure: skip-with-warning
Evidence: none
Slot routing: identical
Main routing: identical
Progress key: report_verify=done
```

```
Step: archive_slot
Phase: closing:stamped
Type: mechanical
Script: python3 work-end/work_end_execute.py archive-slot slot_path=$SLOT_PATH family_root=$FAMILY_ROOT slot_num=$SLOT_NUM
Output keys: ARCHIVED=yes | ERROR=<msg>
Success: ARCHIVED=yes
Failure: ERROR → retry (max 3), offer force=yes
Evidence: none
Slot routing: SLOT ONLY
Main routing: SKIP
Progress key: archive_slot=done
Skip condition: in_slot=no
```

```
Step: report_archive
Phase: closing:stamped
Type: mechanical
Script: python3 work-end/close_report.py record $REPORT_PATH step=archive
Output keys: RECORDED=archive
Success: RECORDED=archive
Failure: skip-with-warning
Evidence: none
Slot routing: SLOT ONLY
Main routing: SKIP
Progress key: report_archive=done
Skip condition: in_slot=no
```

```
Step: checkout_main
Phase: closing:stamped
Type: mechanical
Script: python3 work-end/branch_cleanup.py checkout-main $PROJECT $WORKSPACE
Output keys: SWITCHED=yes | ERROR=<msg>
Success: SWITCHED=yes
Failure: ERROR → retry (max 3), then skip-with-warning
Evidence: consumed by cleanup_pass {repos_on_main: {project: true, workspace: true}}
Slot routing: identical
Main routing: SKIP (already on main)
Progress key: checkout_main=done
Skip condition: on_main=yes
```

```
Step: cleanup_stack
Phase: closing:stamped
Type: mechanical
Script: python3 work-end/branch_cleanup.py cleanup-stack $WORKSPACE branch=$BRANCH
Output keys: CLEANED=yes | NOT_IN_STACK=yes
Success: CLEANED=yes or NOT_IN_STACK=yes
Failure: skip-with-warning (non-critical)
Evidence: none
Slot routing: identical
Main routing: SKIP
Progress key: cleanup_stack=done
Skip condition: on_main=yes
```

```
Step: cleanup_scaffold
Phase: closing:stamped
Type: mechanical
Script (branch/slot): python3 work-end/branch_cleanup.py cleanup-scaffold $WORKSPACE
Script (main): SKIP cleanup-scaffold — orchestrator removes only JOURNAL.md, .execute-progress,
  .land-ledger.jsonl, .artifacts-promoted via git rm, then commits and pushes:
    git -C $WS rm -f JOURNAL.md .execute-progress .land-ledger.jsonl .artifacts-promoted
    git -C $WS commit -m "chore(work-end): cleanup branch scaffold"
    git -C $WS push  (non-fatal — matches branch_cleanup.py push behaviour)
  .plan is preserved (C76 — drained state).
Output keys: CLEANED=yes
Success: CLEANED=yes
Failure: skip-with-warning
Evidence: none
Slot routing: identical
Main routing: orchestrator handles selectively (D6 — script has no keep_plan parameter)
Progress key: cleanup_scaffold=done
```

```
Step: report_scaffold
Phase: closing:stamped
Type: mechanical
Script: python3 work-end/close_report.py record $REPORT_PATH step=scaffold-cleanup
Output keys: RECORDED=scaffold-cleanup
Success: RECORDED=scaffold-cleanup
Failure: skip-with-warning
Evidence: none
Slot routing: identical
Main routing: identical
Progress key: report_scaffold=done
```

```
Step: delete_progress
Phase: post-close
Type: mechanical
Script: (internal) delete .close-progress and .close-progress.tmp
Output keys: none (internal operation)
Success: files deleted
Failure: warn (non-critical)
Evidence: none
Slot routing: identical
Main routing: identical
Progress key: N/A (final cleanup)
```

```
Step: abort
Phase: any abortable (closing:review, closing:verified)
Type: mechanical
Script: (internal) orchestrator handles directly:
  1. Delete .close-progress and .close-progress.tmp
  2. Delete .execute-progress (if exists)
  3. Fire abort_close lifecycle transition → active
Output keys: ACTION=complete SUMMARY=Aborted
Success: lifecycle state returns to active
Failure: abort_blocked if meta_state is post-promotion (forward-only per D11)
Evidence: none
Note: Current _handle_abort only deletes .close-progress — must be extended to
  also delete .execute-progress and fire abort_close lifecycle transition per D10.
Progress key: N/A (abort resets progress)
```

```
Step: report_render
Phase: post-close
Type: mechanical
Script: python3 work-end/close_report.py render <REPORT_PATH>
Output keys: SUMMARY=<multiline rendered text>
Success: SUMMARY non-empty
Failure: skip-with-warning
Evidence: none
Slot routing: identical
Main routing: identical
Progress key: N/A (final)
```

### Lifecycle transition steps

These are not script calls — they fire lifecycle events between
mechanical steps. The orchestrator tracks expected state internally
after `land` to avoid re-reading META_STATE for rapid-fire transitions.

```
Step: review_pass
Phase: closing:review → closing:verified
Type: lifecycle
Event: review_pass
Evidence: {review_result: "pass"}
Fires after: all sweep sub-steps complete
```

```
Step: promote_pass
Phase: closing:verified → closing:promoted
Type: lifecycle
Event: promote_pass
Evidence: see §2.1 — {promoted_files: int(WORKSPACE_PROMOTED) + int(PROJECT_PROMOTED), target_repos: [project, workspace]}
Fires after: promote step
```

```
Step: push_pass
Phase: closing:promoted → closing:pushed
Type: lifecycle
Event: push_pass
Evidence: see §2.1 — {pushed_repos: [repos], pushed_shas: {repo: sha from land output}}
Fires after: land step
Main mode: {pushed_repos: [project, workspace], pushed_shas: {project: sha}}
```

```
Step: merge_pass
Phase: closing:pushed → closing:merged
Type: lifecycle
Event: merge_pass
Evidence: {landed_shas: <dict>, verified_on_main: <dict>}
Main mode: empty dicts {landed_shas: {}, verified_on_main: {}}
Fires after: push_pass (rapid succession)
```

```
Step: stamp_pass
Phase: closing:merged → closing:stamped
Type: lifecycle
Event: stamp_pass
Evidence: see §2.1 — {stamp_shas: {repo: landed_sha}} (reused from land output)
Main mode: empty dict {stamp_shas: {}}
Fires after: merge_pass (rapid succession)
```

```
Step: cleanup_pass
Phase: closing:stamped → idle
Type: lifecycle
Event: cleanup_pass
Evidence: {repos_on_main: {project: true, workspace: true}, work_items_ended: true}
Fires after: cleanup_scaffold
Main mode: fires cleanup_main instead → drained (not idle)
```

```
Step: cleanup_main
Phase: closing:stamped → drained
Type: lifecycle
Event: cleanup_main
Evidence: {work_items_ended: true}
Fires instead of cleanup_pass when on_main=yes
```

### 2.1 Evidence derivation templates

Each lifecycle transition requires an evidence dict. These templates
define exactly how to derive each key from script output.

```
promote_pass:
  promoted_files: int(WORKSPACE_PROMOTED) + int(PROJECT_PROMOTED)  — from cmd_promote forwarded output
  target_repos: [project.name, workspace.name]  — from orchestrator context (known at invocation)
```

```
push_pass:
  pushed_repos: [project.name, workspace.name]  — from orchestrator context (known repos)
  pushed_shas:
    Branch mode: {project.name: LANDED_SHA}  — parse LANDED_SHA=<sha> from cmd_land stdout
    Slot mode: parse LANDED_SHAS=<repo:sha,...> from merge_slot stdout into dict
    Main mode: {project.name: sha}  — sha from git rev-parse HEAD after push
  Note: SHAs are NOT stored in .execute-progress. The progress file tracks
    phase (merged/pushed/stamped) per repo:branch key, not SHA values.
    SHAs come from cmd_land stdout or merge_slot stdout.
```

```
merge_pass:
  landed_shas: same dict as pushed_shas from push_pass  — land_batch merges before pushing
  verified_on_main: {repo.name: True for repo in pushed_repos}  — optimistic; verify step confirms
  Main mode: {landed_shas: {}, verified_on_main: {}}  — empty dicts, no merge happens
```

```
stamp_pass:
  stamp_shas: same dict as pushed_shas from push_pass  — land_batch stamps after pushing,
    the stamp commit references the landed SHA ("landed as <sha> on main")
  Note: .execute-progress records "repo:branch=stamped" (phase only, no SHA).
    Successful land implies successful stamp — the orchestrator reuses the
    landed SHAs from the land step output.
  Main mode: {stamp_shas: {}}  — empty dict, no stamp happens
```

```
cleanup_pass:
  repos_on_main: {project.name: True, workspace.name: True}  — confirmed by checkout_main success
  work_items_ended: True  — invariant at this point in the sequence
```

```
cleanup_main:
  work_items_ended: True  — invariant at this point in the sequence
```

### Judgment steps (yield ACTION= to LLM)

These are points where the orchestrator yields control. The LLM
executes the action using the handler instructions (Section 4).

```
Step: review
Phase: closing:review
Type: judgment
Action: ACTION=review DIFF_RANGE=<base>..<branch>
Validation: findings.jsonl exists, all entries status != open
Retry: re-yield with REASON=<N open findings remain>
Max attempts: 3, then ACTION=user_input CONTEXT=step_failed
Main mode: DIFF_RANGE uses drained-sha or project-sha as base
Progress key: review=done
```

```
Step: sweep_config
Phase: closing:review
Type: judgment
Action: ACTION=sweep_config ITEMS=forage:on,protocol:on,update_claude_md:on,impl_doc_sync:on,adr:on,write_content:on
Validation: sweep_selected= argument provided on next call
Retry: re-yield (user may not have responded)
Max attempts: 3, then ACTION=user_input CONTEXT=step_failed
Progress key: sweep_config=done
Progress stores: sweep_selected=<csv of selected items>
```

```
Step: forage (conditional on sweep_selected)
Phase: closing:review
Type: judgment
Action: ACTION=forage
Validation: garden entry files created since step start, OR skip_step=forage
Retry: re-yield with REASON=no garden entries found
Max attempts: 3, then ACTION=user_input CONTEXT=step_failed
Progress key: forage=done
Skip condition: forage not in sweep_selected
```

```
Step: protocol (conditional on sweep_selected)
Phase: closing:review
Type: judgment
Action: ACTION=protocol [REPO=<repo-path> in slot mode per-repo loop]
Validation: protocol files created since step start, OR skip_step=protocol
Retry: re-yield with REASON=no protocol files found
Max attempts: 3, then ACTION=user_input CONTEXT=step_failed
Progress key: protocol=done
Skip condition: protocol not in sweep_selected
```

```
Step: update_claude_md (conditional on sweep_selected)
Phase: closing:review
Type: judgment
Action: ACTION=update_claude_md [REPO=<repo-path> in slot mode per-repo loop]
Validation: CLAUDE.md mtime changed, OR diff shows no changes needed
Retry: re-yield with REASON=CLAUDE.md unchanged
Max attempts: 3, then ACTION=user_input CONTEXT=step_failed
Progress key: update_claude_md=done
Skip condition: update_claude_md not in sweep_selected
```

```
Step: impl_doc_sync (conditional on sweep_selected)
Phase: closing:review
Type: judgment
Action: ACTION=impl_doc_sync [REPO=<repo-path> in slot mode per-repo loop]
Validation: docs directory mtime changed, OR diff shows no changes needed
Retry: re-yield with REASON=docs unchanged
Max attempts: 3, then ACTION=user_input CONTEXT=step_failed
Progress key: impl_doc_sync=done
Skip condition: impl_doc_sync not in sweep_selected
```

```
Step: adr (conditional on sweep_selected)
Phase: closing:review
Type: judgment
Action: ACTION=adr
Validation: ADR file created in workspace adr/, OR skip_step=adr
Retry: re-yield with REASON=no ADR file found
Max attempts: 3, then ACTION=user_input CONTEXT=step_failed
Progress key: adr=done
Skip condition: adr not in sweep_selected
```

```
Step: write_content (conditional on sweep_selected)
Phase: closing:review
Type: judgment
Action: ACTION=write_content BRANCH_SUMMARY=<one-line> ISSUE=$ISSUE_N
Validation: blog file exists in workspace blog/, frontmatter valid, word count > 100
Retry: re-yield with REASON=<specific failure — no file / invalid frontmatter / too short>
Max attempts: 3, then ACTION=user_input CONTEXT=step_failed
Progress key: write_content=done
Skip condition: write_content not in sweep_selected
```

```
Step: trajectory
Phase: closing:promoted
Type: judgment
Action: ACTION=trajectory COVERS=$COVERS OWNER_REPO=$OWNER_REPO
Validation: enrichment DB updated, OR skip_step=trajectory
Retry: re-yield with REASON=enrichment not updated
Max attempts: 3, then skip (non-blocking — C48)
Progress key: trajectory=done
Non-blocking: failure does not gate close
```

```
Step: squash
Phase: closing:promoted
Type: judgment
Action: ACTION=squash REPOS=<csv> PLAN_DIR=<workspace path>
Validation: .squash-plan-<repo>.json exists and valid JSON for each repo
Retry: re-yield with REASON=<missing or invalid plan files>
Max attempts: 3, then ACTION=user_input CONTEXT=step_failed
Progress key: squash=done
Skip condition: on_main=yes
```

```
Step: arc42_scan
Phase: closing:stamped
Type: judgment
Action: ACTION=user_input CONTEXT=arc42_scan
Validation: response received
Progress key: arc42_scan=done
Skip condition: no ARC42STORIES.MD
```

```
Step: session_rename
Phase: closing:stamped
Type: judgment
Action: ACTION=user_input CONTEXT=session_rename
Validation: response received
Progress key: session_rename=done
```

```
Step: garden_feedback
Phase: closing:stamped
Type: judgment
Action: ACTION=user_input CONTEXT=garden_feedback GE_IDS=<pipe-separated>
Validation: response received
Progress key: garden_feedback=done
Skip condition: no GE-IDs in session or HANDOFF.md
```

```
Step: notes
Phase: closing:stamped
Type: judgment
Action: ACTION=user_input CONTEXT=notes
Validation: response received
Progress key: notes=done
Skip condition: no .notes/ directory
```

```
Step: verify_recover (conditional — only on verify failure)
Phase: closing:stamped
Type: judgment
Action: ACTION=verify_recover FAILURES=<per-check failure details>
Validation: re-run verify passes
Progress key: verify_recover=done
Not in normal sequence — fires only when verify step returns VERIFIED=no
```

```
Step: review_rebase (conditional — only after conflicted rebase)
Phase: closing:promoted
Type: judgment
Action: ACTION=review_rebase DIFF_RANGE=<conflict-resolution commits>
Validation: findings.jsonl — all findings from this review status != open
Progress key: review_rebase=done
Not in normal sequence — fires only when rebase had conflicts
```

---

## 3. Orchestrator full sequence

The complete ordering, showing the interleave of mechanical steps,
lifecycle transitions, and judgment yields.

```
PHASE: closing:review
  [mechanical] report_init
  [yield]      review
  [yield]      sweep_config
  [yield]      forage          (if selected)
  [yield]      protocol        (if selected)
  [yield]      update_claude_md (if selected)
  [yield]      impl_doc_sync   (if selected)
  [yield]      adr             (if selected)
  [yield]      write_content   (if selected)
  [lifecycle]  review_pass → closing:verified

PHASE: closing:verified
  [mechanical] promote
  [mechanical] report_promote
  [lifecycle]  promote_pass → closing:promoted

PHASE: closing:promoted
  [yield]      trajectory      (non-blocking)
  [mechanical] rebase          (skip: on_main)
  [mechanical] report_rebase   (skip: on_main)
  [yield if conflict] user_input(rebase_conflict)
  [yield if resolved] review_rebase
  [yield]      squash          (skip: on_main)
  [mechanical] report_squash   (skip: on_main)
  [mechanical] write_marker    (skip: not slot)
  [mechanical] land
  [mechanical] report_land
  [lifecycle]  push_pass → closing:pushed
  [lifecycle]  merge_pass → closing:merged  (rapid)
  [lifecycle]  stamp_pass → closing:stamped (rapid)

PHASE: closing:stamped
  [mechanical] close_issues    (skip: no covers)
  [mechanical] report_close_issues (skip: no covers)
  [mechanical] verify
  [mechanical] report_verify
  [yield if failed] verify_recover
  [mechanical] archive_slot    (skip: not slot)
  [mechanical] report_archive  (skip: not slot)
  [mechanical] checkout_main   (skip: on_main)
  [mechanical] cleanup_stack   (skip: on_main)
  [mechanical] cleanup_scaffold
  [mechanical] report_scaffold
  [yield]      arc42_scan      (skip: no ARC42)
  [yield]      session_rename
  [yield]      garden_feedback (skip: no GE-IDs)
  [yield]      notes           (skip: no .notes/)
  [lifecycle]  cleanup_pass → idle  OR  cleanup_main → drained

POST-CLOSE:
  [mechanical] delete_progress
  [mechanical] report_render
  [yield]      complete
```

### Slot mode per-repo sweep

When `in_slot=yes`, the sweep sub-steps that are per-repo
(update_claude_md, impl_doc_sync, protocol) run for each repo
in the slot. The orchestrator manages this:

```
For each repo in slot (primary first, then secondaries):
  [yield] protocol        (if selected, with REPO=<repo-path>)
  [yield] update_claude_md (if selected, with REPO=<repo-path>)
  [yield] impl_doc_sync   (if selected, with REPO=<repo-path>)

Then once (session-bound):
  [yield] forage          (if selected)
  [yield] adr             (if selected)
  [yield] write_content   (if selected)
```

**Per-repo progress tracking:** In slot mode, per-repo sweep steps use
compound progress keys: `protocol:soredium=done`, `protocol:domain=done`.
The orchestrator marks a step complete for the overall sequence only when
all repos have been processed. This enables fine-grained recovery — if the
session crashes after completing protocol for repo 1 of 3, only repos 2
and 3 re-run on resume. The single-key variants (`protocol=done`) are used
in non-slot mode and remain unchanged.

The orchestrator discovers repos from the slot's `.slot` file (markdown format).
Repo discovery: parse the `## Repos` section for markdown bullet items (`- repo_name`).
The primary repo has a `(primary)` suffix: `- soredium (primary)`. Parse with
`line.strip().startswith("- ")`, strip suffix with `.split(" ")[0]`. Resolve paths
relative to the slot directory (e.g., `slots/134/soredium`). Primary repo
is the first entry; secondaries follow in order. The orchestrator passes
`REPO=<absolute-repo-path>` as action context so the LLM knows which
repo to target for each per-repo sweep iteration.

---

## 4. SKILL.md action handler content

Verbatim extraction from the current SKILL.md per D16. Each handler
contains the judgment instructions the LLM needs when executing
that action. The dispatch loop shows only the action name —
the handler section provides the full instructions.

### Handler: review

```markdown
Code review, branch audit, loose ends sweep, and forcing function.
All four sub-steps are hard gates — review does not complete until
the forcing function has resolved all findings.

**Budget limits are not gates.** If code-review or branch-audit reports
a budget warning ("coverage may be incomplete"), proceed to the next
sub-step. The forcing function processes whatever findings were
collected. Do not restart the review, do not block, do not retry.
Surface the warning in the close summary.

### Code review

Invoke `code-review` on the diff specified by DIFF_RANGE.

**Security-audit suppression:** Do NOT offer security-audit escalation —
branch-audit Robustness dimension handles security escalation.

After code-review completes, persist any unresolved findings to
`$WORKSPACE/.audit/findings.jsonl` via `append_finding` from
`project/findings.py` with `category: "review"` and `source: "code-review"`.

### Branch audit

Invoke `branch-audit` on the full branch diff. Four dimensions:
Conformance, Coherence, Structure, Robustness.

Findings are appended to `findings.jsonl` after each dimension completes
(not batched). This ensures partial progress survives session interruption.

### Loose ends sweep

```bash
python3 work-end/loose_ends_sweep.py workspace=$WS project=$PROJ branch=$BRANCH cycle_start=<ISO>
```

Pass `cycle_start` as the timestamp when the review action started — this
filters out findings just written by code-review and branch-audit.

Supplement script output with conversation-context items
("I'll come back to this") and append those to `findings.jsonl`.

### Forcing function (HARD GATE)

Read all open findings from `$WORKSPACE/.audit/findings.jsonl` via
`read_findings` from `project/findings.py`. Present grouped by category:

```
Open findings — N items require resolution before branch close

AUDIT (branch-audit):
  1. [conformance/WARNING] ...

REVIEW (code-review):
  2. [WARNING] ...

LOOSE-END:
  3. [WARNING] ...
```

**Resolution options per finding:**

| Option | What happens |
|--------|-------------|
| **Fix** | Fix the issue now. Status → resolved, resolution includes commit SHA |
| **File** | Create a GitHub issue. Status → filed, resolution includes issue number |
| **Dismiss** | Not a real problem. Status → dismissed, resolution includes reason |

**Severity constraints:**

| Severity | Fix | File | Dismiss |
|----------|-----|------|---------|
| CRITICAL | Yes | Yes  | No      |
| WARNING  | Yes | Yes  | Yes     |
| NOTE     | Yes | Yes  | Yes     |

**Re-review after fixes:** When "Fix" creates new commits, re-run
code-review on those commits only. New findings join the queue.
Branch-audit does not re-run.

**Batch operations:**
- "File all remaining as single issue" — one issue with checklist
- "File each remaining" — one issue per finding
- "Dismiss all NOTEs" — blanket dismiss with user-provided reason

Each resolution is persisted to `findings.jsonl` immediately.
No finding survives branch close with status `open`.
```

### Handler: review_rebase

```markdown
Code-review ONLY on the conflict-resolution diff specified by DIFF_RANGE.

Scope constraint: NO branch-audit, NO loose-ends sweep, NO forcing function.
This is a scoped review of conflict-resolution commits only.

If findings: mini-gate with Fix/File/Dismiss (same severity constraints as
the full review handler). Persist to findings.jsonl. All findings must be
resolved before the orchestrator continues.
```

### Handler: sweep_config

```markdown
Present the pre-close checklist with all items ON:

```
Pre-close sweep — create before closing?

[x] 1  Knowledge capture   (forage then protocol — sequential)
[x] 2  ADR                 record architectural decisions
[x] 3  Doc sync            (update-claude-md then implementation-doc-sync)
[x] 4  write-content       capture branch narrative as diary entry

Type numbers to toggle, "all" to toggle all, or "go" to proceed:
```

<NEVER-RECOMMEND-SKIPPING>
Present all items ON. Do not recommend skipping. The user decides.
"Go" means proceed with current selections — all ON by default.
Session-bound items (1, 4) cannot be deferred.
</NEVER-RECOMMEND-SKIPPING>

Report selected items back to orchestrator via sweep_selected= argument:
```
python3 work-end/work_end_orchestrator.py ... sweep_selected=forage,protocol,update_claude_md,impl_doc_sync,adr,write_content
```

**Journal validation:** If JOURNAL_DRIFT or UNANCHORED_ENTRIES in
orchestrator output, present decisions interactively before proceeding.
```

### Handler: forage

```markdown
Invoke forage SWEEP. Run while conversation context is full — this is
why forage runs first in the sweep order.
```

### Handler: protocol

```markdown
Invoke protocol SWEEP.
```

### Handler: update_claude_md

```markdown
Invoke update-claude-md.
```

### Handler: impl_doc_sync

```markdown
Invoke implementation-doc-sync.
```

### Handler: adr

```markdown
Invoke adr to record architectural decisions made during this branch.
```

### Handler: write_content

```markdown
Invoke write-content (diary type) to capture the branch narrative.
This runs LAST in the sweep — it synthesises the full narrative from
everything that happened on the branch, including forage and protocol
discoveries from earlier sweep steps.

Session-bound — cannot be deferred to another session.
```

### Handler: trajectory

```markdown
After artifacts are promoted and before the branch is pushed. Non-blocking —
if this step fails or the user declines, the orchestrator continues.

1. Draft a one-line trajectory note for each completed issue.
2. Propose enrichment updates — assess how completed work shifts the
   strategic landscape for 2-3 sibling/related issues.
3. Present table for user confirmation. On YES:
   ```bash
   python3 scripts/enrichment.py trajectory --issue <N> --repo <REPO> --text "<note>" --branch <BRANCH>
   python3 scripts/enrichment.py upsert --issue <N> --repo <REPO> --readiness ready
   ```
4. Failure is non-blocking.
```

### Handler: squash

```markdown
For each repo listed in REPOS: classify commits and write
`.squash-plan-<repo>.json`. Repos with existing plan files are
skipped (restart safety).

**Slot mode marker:** If in_slot=yes, the orchestrator writes the
.phase-a-complete marker mechanically after squash completes — the
LLM does not need to handle this.
```

### Handler: user_input (parameterised by CONTEXT=)

```markdown
**CONTEXT=arc42_scan:**
If ARC42STORIES.MD exists, scan for stale statuses and offer fixes.

**CONTEXT=session_rename:**
Suggest a descriptive session name if auto-generated.

**CONTEXT=garden_feedback:**
Record which garden entries were useful.
1. Collect all GE-IDs from session context and HANDOFF.md
2. Assess relevance: HIGHLY_RELEVANT, RELEVANT, PARTIALLY_RELEVANT,
   NOT_RELEVANT, OUTDATED (requires stack parameter)
3. Group by outcome, call gardenFeedback once per group
4. MCP unavailable → warn once, continue (never block)

**CONTEXT=notes:**
Surface most recent date section from $WORKSPACE/.notes/NOTES.md.
Offer to append. If user provides notes, append under today's date
and commit to orphan notes branch.

**CONTEXT=step_failed:**
Judgment step failed after 3 retries. Present STEP, ATTEMPTS, REASON.
Options: skip / retry / abort.

**CONTEXT=rebase_conflict:**
Rebase conflict needs manual resolution. User resolves, then pass
conflict_resolved=yes to the orchestrator.
```

### Handler: verify_recover

```markdown
Verify returned VERIFIED=no. Present per-check failures from FAILURES=.
Offer recovery: re-run the failing Execute sub-step, then re-run verify.
```

---

## 5. Cross-session state recovery

Per D15 (revised): two-tier evidence reconciliation.

### Tier 1 — Local checks (every invocation, <1s)

| Step | Evidence check |
|------|---------------|
| review | findings.jsonl exists, all statuses != open |
| promote | promoted files exist in project docs/ matching workspace artifacts |
| rebase | branch is fast-forward from base (`git merge-base --is-ancestor`) |
| land | .execute-progress has landed entries |
| stamp | empty stamp commit exists on branch (`git log --grep "branch closed"`) |
| cleanup_scaffold | .plan absent (branch mode) or state=drained (main mode) |
| archive | slot directory in attic/ |

### Tier 2 — Network checks (first invocation only, cached in .close-progress)

| Step | Evidence check | Cache key |
|------|---------------|-----------|
| push | SHA exists on remote (`git ls-remote`) | push_verified=yes |
| close_issues | `gh issue view --json state` shows CLOSED | issues_verified=yes |

### Expanded STEP_TO_PHASE map

The `close_progress.py` STEP_TO_PHASE map must be extended to cover
all step names introduced by the orchestrator. Unknown steps default
to `closing:review` which is safe but prevents fine-grained recovery.

```python
STEP_TO_PHASE = {
    # closing:review
    "report_init": "closing:review",
    "review": "closing:review",
    "sweep_config": "closing:review",
    "forage": "closing:review",
    "protocol": "closing:review",
    "update_claude_md": "closing:review",
    "impl_doc_sync": "closing:review",
    "adr": "closing:review",
    "write_content": "closing:review",
    # closing:verified
    "promote": "closing:verified",
    "report_promote": "closing:verified",
    # closing:promoted
    "trajectory": "closing:promoted",
    "rebase": "closing:promoted",
    "report_rebase": "closing:promoted",
    "squash": "closing:promoted",
    "report_squash": "closing:promoted",
    "write_marker": "closing:promoted",
    "land": "closing:promoted",
    "report_land": "closing:promoted",
    # closing:stamped
    "close_issues": "closing:stamped",
    "report_close_issues": "closing:stamped",
    "verify": "closing:stamped",
    "report_verify": "closing:stamped",
    "archive_slot": "closing:stamped",
    "report_archive": "closing:stamped",
    "checkout_main": "closing:stamped",
    "cleanup_stack": "closing:stamped",
    "cleanup_scaffold": "closing:stamped",
    "report_scaffold": "closing:stamped",
    "arc42_scan": "closing:stamped",
    "session_rename": "closing:stamped",
    "garden_feedback": "closing:stamped",
    "notes": "closing:stamped",
    "cleanup": "closing:stamped",
}
```

### Reconciliation flow

```
1. Read .close-progress
2. Read META_STATE from lifecycle
3. If .close-progress ahead of META_STATE → stale file, delete and start fresh
4. If META_STATE ahead of .close-progress → fast-forward .close-progress
5. For each step marked "done" in .close-progress:
   a. Run Tier 1 check
   b. If first invocation AND late-stage step: run Tier 2 check
   c. If evidence contradicts → remove "done" marker, report correction
6. Emit RECONCILIATION_REPORT=<corrections made> (or RECONCILIATION_REPORT=clean)
```

---

## 6. Fallback telemetry (D17 revised)

When the SKILL.md dispatch loop detects an orchestrator error and falls
back to old instructions for a step:

```
FALLBACK_TRIGGERED=<step_name>
FALLBACK_REASON=<error message from orchestrator>
```

The LLM emits this BEFORE executing the fallback. The marker is:
1. Printed to stdout (visible in conversation)
2. Appended to .close-progress as `fallback_<step>=<reason>`

Post-deployment audit greps for FALLBACK_TRIGGERED in .close-progress
files across completed closes. Zero triggers = safe to remove fallback.

---

## 7. Testing strategy

### Unit tests (orchestrator logic)

| Test category | What it verifies |
|--------------|-----------------|
| Full sequence — branch mode | All mechanical steps called in order, correct actions yielded |
| Full sequence — slot mode | All 5 routing conditionals fire correctly |
| Full sequence — main mode | Branch-specific steps skipped, empty evidence dicts |
| Script invocation | Each mechanical step calls the correct script with correct arguments (NOT stubs) |
| Validation per judgment step | Each validator correctly accepts/rejects |
| Retry counting | 3 failures → user escalation (judgment) or skip-with-warning (mechanical) |
| Abort from review/verified | .close-progress + .execute-progress deleted, abort_close fires |
| Abort from promoted | Rejected with explanation |
| Sweep config → conditional steps | Deselected sub-steps never yielded |
| Evidence dict construction | Correct keys derived from script output for each lifecycle event |
| skip_step= handling | Progress updated, next action yielded |
| conflict_resolved= handling | Rebase re-run, review_rebase yielded |

### Integration tests (subprocess calls)

| Test | What it verifies |
|------|-----------------|
| promote calls work_end_execute.py | subprocess.run invoked with correct arguments |
| land calls correct script per mode | branch: work_end_execute.py land; slot: slot_manager.py merge-slot |
| verify calls verify_slot_close.py | slot_dir= present in slot mode, absent otherwise |
| lifecycle transitions fire | commit-transition called with correct from/to/evidence |
| close_report integration | init → record (all steps) → render produces valid summary |

### Crash recovery tests

| Test | What it verifies |
|------|-----------------|
| Resume from each progress state | Completed steps skipped, next action yielded |
| .close-progress.tmp exists | Old .close-progress used, .tmp ignored |
| META_STATE ahead of progress | Fast-forwards to match lifecycle phase |
| Stale progress (ahead of META_STATE) | File deleted, fresh sequence starts |
| Evidence contradicts progress | Progress corrected, correction reported |

### Audit tests (dry-run mode)

| Test | What it verifies |
|------|-----------------|
| Branch mode dry-run | All 93 capabilities exercised |
| Slot mode dry-run | All slot-specific routing exercised |
| Main mode dry-run | All main-specific routing exercised |
| Fallback detection | FALLBACK_TRIGGERED captured in dry-run |

---

## 8. Rollout plan

### Phase 1: Wire mechanical steps (context-dependent batch)

Wire every stubbed and missing mechanical step in the orchestrator.
This batch benefits from holding all step definition tables in context.

**Deliverable:** All mechanical steps call real scripts with correct
arguments. All lifecycle transitions fire. All output keys parsed.

**Verification:** Integration tests pass. Dry-run audit shows zero
FALLBACK_TRIGGERED for mechanical steps.

**Wrap boundary:** Yes — this is a natural wrap point. The SKILL.md
rewrite (Phase 2) doesn't need the wiring session's context; it
needs the wiring's output (a working orchestrator).

### Phase 2: SKILL.md rewrite (context-independent)

Rewrite the SKILL.md with:
- Pre-close section (C1-C13, adapted from current Steps 0-1)
- Dispatch loop (~20 lines)
- Action handlers (verbatim from Section 4 above)
- Fallback section (old instructions, hidden)
- Constraints section (C87-C93)

**Deliverable:** New SKILL.md that delegates to the orchestrator for
the close sequence. Fallback instructions present for safety.

**Verification:** `validate_all.py --tier commit` passes.
Dry-run audit shows orchestrator path taken for all steps.

**Wrap boundary:** Yes — the audit (Phase 3) is independent.

### Phase 3: Audit and fallback removal (context-independent)

1. Run dry-run audit across all 3 modes
2. Run real work-end on a test branch
3. Grep .close-progress for FALLBACK_TRIGGERED
4. If zero triggers: remove fallback section from SKILL.md
5. Final commit

**Deliverable:** Clean SKILL.md with no fallback. Audit passes.

---

## 9. Post-deployment audit script

`audit_work_end.py` — runs the orchestrator in `dry_run=yes` mode.

### Interface

```bash
python3 work-end/audit_work_end.py mode=branch
python3 work-end/audit_work_end.py mode=slot
python3 work-end/audit_work_end.py mode=main
```

### What it checks

For each mode, creates a synthetic workspace with:
- .plan with appropriate state
- .close-progress (empty — fresh start)
- Mocked git repos (project + workspace)
- Mocked slot structure (slot mode only)

Runs the orchestrator repeatedly, verifying:
1. Every step in the sequence is reached
2. Every script call has correct arguments
3. Every lifecycle transition fires with valid evidence keys
4. Every capability from the matrix (Section 1) is exercised
5. No FALLBACK_TRIGGERED markers emitted

### Output

```
Mode: branch
  ✅ report_init          called with correct args
  ✅ review               yielded with DIFF_RANGE
  ✅ sweep_config         yielded with ITEMS
  ✅ forage               yielded (conditional: selected)
  ...
  ✅ cleanup_pass          lifecycle fired with evidence
  ✅ report_render         called with correct args
  ✅ complete              yielded with SUMMARY

Capabilities: 93/93 exercised
Fallback triggers: 0
RESULT: PASS
```

### Implementation constraint (from R1-15)

`dry_run=yes` must reuse the same dispatch logic as the real path.
The only difference: the final `subprocess.run()` call is captured
(arguments recorded) instead of executed. All conditional logic,
argument construction, output parsing, and progress tracking use
the real code path.

---

## 10. What is already implemented

The first implementation (Batches 1-2 from the prior plan) completed:

| Component | Status | Notes |
|-----------|--------|-------|
| `close_progress.py` | Done, tested | Atomic progress tracking module |
| `work_end_orchestrator.py` | Partial — stubs | Judgment sequencing works; mechanical steps stubbed |
| `close_report.py` updates | Done, tested | Step names updated for orchestrator |
| Atomic write-then-rename | Done, tested | write_progress() in work_end_execute.py and land_flow.py |
| `test_close_progress.py` | Done | 10 tests passing |
| `test_work_end_orchestrator.py` | Partial | Tests verify action sequence but not script invocations |

The continuation work must:
1. Wire real script calls into work_end_orchestrator.py (replacing stubs)
2. Add slot mode routing
3. Add cross-session recovery
4. Add integration tests verifying subprocess calls
5. Rewrite SKILL.md with dispatch loop + handlers
6. Implement audit script
7. Remove fallback after verification

---

## References

- `2026-08-24-mechanise-work-end-close-design.md` — prior spec (architecture, D1-D12)
- `decisions.md` — all 18 decisions (D1-D12 settled, D13-D18 new)
- Issue #271 — 8 failures across 4 slot closures (original evidence)
- Issue #275 — implementation gaps: stubbed steps, missing slot mode, no recovery
- Revert commit `151b7a8` — "stubs all mechanical steps and has no slot awareness"
- `work-end/SKILL.md` at SHA `151b7a8` — capability matrix baseline (93 capabilities)
- `work-end/work_end_orchestrator.py` — existing partial implementation
- `work-end/close_progress.py` — existing progress tracking module
- `project/lifecycle.py` — state machine, atomic write pattern
- `work-end/work_end_execute.py` — existing Execute scripts
- `work-end/land_flow.py` — shared land flow
- `work-end/verify_slot_close.py` — verification gate
- `work-end/close_report.py` — summary generation
- `work-end/branch_cleanup.py` — checkout-main, cleanup scaffold
- `work-slot/slot_manager.py` — slot mode merge-slot
- `docs/protocols/externalised-scripts-require-tests.md`
- `docs/protocols/evidence-before-claims.md`
- GE-20260824-c09677 — inverted control pattern for Claude Code
- GE-20260821-ebba3b — work-end atomicity and stamp failures
- Decision review: `/Users/mdproctor/reviews/hortora-soredium/issue-271-decision-20260824-163559/`
