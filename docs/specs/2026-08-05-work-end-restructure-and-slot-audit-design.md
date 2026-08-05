# Work-end Restructure and Multi-repo Slot Audit

**Date:** 2026-08-05
**Status:** Draft
**Scope:** soredium work-end skill, slot close infrastructure, legacy slot remediation
**Tracking:** Issue to be filed on soredium before first implementation commit.

---

## Problem Statement

### Multi-repo slot close bug

work-end's slot close sequence processes only the primary repo. Non-primary
repos in multi-repo slots have their content merged (often in separate
sessions) but are never stamped. An audit of 73 slots (14 multi-repo) found
27 with problems — all stamp-related, no confirmed data loss. The root cause:
the SKILL.md describes per-repo operations using `<slot>/<repo>` syntax, but
the LLM executes only the primary repo and moves on. There is no mechanical
gate that checks all repos were processed.

### Skill complexity

work-end has ~20 steps across ~1400 lines. The LLM frequently skips steps,
complains about length, and makes judgment calls that should be mechanical.
Promotion, verification, and cleanup are scattered across steps rather than
consolidated. The inventory/plan/approval cycle (Steps 4-7) is unnecessary
ceremony — the scripts already know what to promote and where.

---

## Deliverable 1: Legacy Slot Audit Remediation

### Scope

Remediate the 27 problem slots identified by `audit_slot_merges.py`. No
content merging — the audit confirmed content reached main via rebase in
every spot-checked case. This is stamp remediation and documentation only.

### Categories

**MERGED but UNSTAMPED (~15 branches):** Content on main, branch never
stamped. Retroactively stamp with:
```
chore: branch closed — landed as <SHA> on main
  no-issue: retroactive stamp from slot audit
```
Where `<SHA>` is found by matching the branch's commit messages against
main's log (`git log --oneline --grep="<subject>" main`).

**Pre-squash landing SHAs (~5 branches):** Stamps exist but reference SHAs
that were rewritten during squash (garden entry GE-20260721-94263a documents
this). Content IS on main under different SHAs. No fix needed — document as
known limitation. The redesigned Execute step already orders stamping after
squash to prevent recurrence.

**Active slots with WIP commits (slots 54, 86):** Still in progress. No
action — flagged for awareness only.

### Implementation

1. Enhance `audit_slot_merges.py` with `--fix` mode:
   - For MERGED-but-UNSTAMPED: find the landing SHA via commit message
     matching, stamp the branch, verify SHA via `verify_stamp.py`,
     push the stamp. Roll back stamp if verification fails.
   - For pre-squash SHAs: log as "known — content verified on main"
   - Produce a summary report to stdout

2. Run `audit_slot_merges.py --fix` against `/Users/mdproctor/claude/casehub`

3. File soredium issue for Deliverable 2

### Success criteria

- All MERGED-but-UNSTAMPED branches stamped
- Summary report shows per-slot disposition
- No content merging performed
- Issue filed for work-end restructure

---

## Deliverable 2: Work-end Restructure

### Design: 5 steps

```
Context (mechanical) → Sweep (LLM) → Execute (orchestrated) → Verify (mechanical) → Close (mechanical)
```

### Lifecycle State Machine Integration

The 5-step architecture integrates with `project/lifecycle.py`'s closing
sequence. Transitions fire at the SKILL.md level (between script calls),
not inside scripts — same as the current architecture:

| Step | Gate event | New state | Notes |
|------|-----------|-----------|-------|
| Context | `work_end` | closing:review | Entry; if already closing:*, resume from that gate |
| Execute (code review pass) | `review_pass` | closing:verified | |
| Execute (promotion done) | `promote_pass` | closing:promoted | Forward-only from here |
| Execute (land phase done) | `push_pass` → `merge_pass` → `stamp_pass` | closing:pushed → closing:merged → closing:stamped | Rapid sequence after Land |
| Close | `cleanup_pass` | idle | |

**Crash recovery:** On re-entry, `META_STATE` from ctx.py tells the
SKILL.md where to resume. A `closing:promoted` state means "artifacts
promoted, restart from push" — the LLM doesn't have to reason about
what already happened. Post-promotion states are forward-only
(`abort_close` is rejected by the transition table).

**Abort:** Available from `closing:review` and `closing:verified` only.
Fires `abort_close` → returns to `active`. The `clear_closing_markers`
effect also deletes `.execute-progress` as a defensive cleanup, even
though this file cannot exist at abort-eligible states (it is created
post-promotion, and abort is blocked post-promotion).

**Lifecycle event semantics:** Events are abstract milestones, not
descriptions of individual git operations. Each event has a semantic
meaning that is stable across execution modes:

| Event | Semantic meaning |
|-------|-----------------|
| `promote_pass` | Artifacts promoted to all destinations |
| `push_pass` | Work branch content safely on at least one remote |
| `merge_pass` | Content verified on authoritative remote base branch |
| `stamp_pass` | All branches stamped and stamps pushed |

In non-slot mode, `push_pass` fires after the fork push and `merge_pass`
fires after the blessed-repo push — the local rebase (step 7) lands
content on the local base branch but is NOT `merge_pass`; it is an
internal sub-step within the `closing:promoted` phase. In slot mode,
the per-repo loop processes all repos' push + merge + stamp before
returning to the SKILL.md.

In both modes, `push_pass`, `merge_pass`, and `stamp_pass` fire in
rapid succession after the Land phase script returns. The intermediate
lifecycle states (`closing:pushed`, `closing:merged`) are transient but
preserve the transition chain required by `lifecycle.py`. Fine-grained
recovery within the Land phase is handled by `.execute-progress`, not
by lifecycle state transitions. `verify_content_landed` (effect of
`merge_pass`) fires after all repos have been pushed to GitHub — always
verifiable against the remote.

### Step 1 — Context

**Nature:** Mechanical script — one call, structured status output.

**Absorbs:** Pre-conditions (0, 0b, 0c, 1-5), Step 1 (branch_recon.py),
Step 2 (Flyway), Step 3 (routing resolution).

**Implementation:** A new `work_end_context.py` script that:

1. Runs `ctx.py` internally for path resolution
2. Checks all 6 pre-conditions:
   - Branch divergence (`BRANCH_MISMATCH`)
   - Queue gate (plan_manager.py `detect`)
   - Issue-complete emission (reconcile_covers + complete_active_issue)
   - Pause stack check
   - `.meta` existence and graceful degradation
   - Clean working tree (workspace + project base branch)
3. Runs `branch_recon.py` for branch state
4. Runs Flyway re-scan
5. Resolves routing via `project/routing.py`

**Output:** Single JSON object with all context values, pre-condition
results, branch state, and routing table. Each pre-condition has a
status field (`pass`, `fail`, or `needs_input`):

```json
{
  "preconditions": {
    "branch_divergence": {"status": "pass"},
    "queue_gate": {"status": "needs_input", "detail": "mid-queue", "remaining": 3},
    "meta_exists": {"status": "needs_input", "detail": "no-meta", "inferred_issue": 42},
    "clean_tree": {"status": "fail", "detail": "uncommitted changes in workspace"}
  },
  "context": { "workspace": "...", "project": "...", "branch": "...", ... },
  "branch_recon": { ... },
  "routing": { ... }
}
```

Exit code 0 always (even with `fail` or `needs_input` conditions).
Exit code 1 only for operational errors (bad args, missing dirs).
The SKILL.md handles interactive resolution for `needs_input` conditions
(queue gate options, .meta degradation flow, branch divergence choices).
`fail` conditions are non-interactive hard stops (dirty tree, etc.).

**Crash recovery contract:** Context does NOT expose `.execute-progress`.
The lifecycle state (`META_STATE`) tells the SKILL.md which major phase
to resume from; `.execute-progress` is internal to `work_end_execute.py`
and tells the script which repos to skip within a phase. On re-entry,
the SKILL.md re-invokes the same script call; the script reads its own
progress file and resumes. This separation keeps Context as a pure
status-gathering step and Execute as a self-contained recovery unit.

**Scripts removed:** `phase_a_complete.py` (marker write absorbed into
Execute), `phase_b_gate.py` (verification logic absorbed into Verify).

**Caveat:** `slot_manager.py` depends on `.phase-a-complete` marker in
`merge_slot()`, `scan_ready()`, and `list_slots()`. Execute must continue
writing this marker after promotion succeeds until `slot_manager.py` is
updated to use the new Verify output.

### Step 2 — Sweep

**Nature:** LLM-driven. Creates files in the workspace branch.

**Four items (down from six):**

| Item | Detection | Execution | Output |
|------|-----------|-----------|--------|
| Knowledge capture | LLM scans session context | forage then protocol (sequential within item) | Garden entries, protocol files |
| ADR | LLM checks for architectural decisions | LLM writes ADR content | ADR files in workspace `adr/` |
| Doc sync | LLM detects convention/doc drift | update-claude-md then impl-doc-sync (sequential within item) | Updated CLAUDE.md, docs |
| write-content (diary) | Always runs last | LLM writes entry | Blog entry in workspace `blog/` |

**Combined items are presentation groupings, not merged operations.** Each
combined item runs its constituent skills sequentially as separate LLM
invocations. Ordering within items is preserved from the current SKILL.md:
- Knowledge capture: forage first (while context is full), then protocol
- Doc sync: update-claude-md first (so impl-doc-sync reads updated CLAUDE.md)

**Rules:**
- All items default to ON. The LLM never recommends skipping.
- write-content runs last so it can reference forage/protocol submissions.
- Items 1 and 4 are session-bound — cannot be deferred.
- A blog is a permanent published artifact for community engagement. HANDOFF
  and journal serve different purposes and do not replace the blog.

**Journal validation decisions (from Context output):**

Context (Step 1) outputs journal state: `arc42_exists`, `section_drift`,
`unanchored_entries`, `empty_journal`. Sweep presents these to the user
for interactive decisions before Execute:

- `arc42_exists == false` → Create from journal entries or Skip
- `section_drift` non-empty → Update anchors, Skip drifted sections, or Abort
- `unanchored_entries > 0` → Fix via update-design, Skip merge, or Continue
- `empty_journal == true` → Write retrospective, Skip, or Accept loss

Present in order above if multiple conditions are true. The user's decisions
are passed to Execute as part of the Sweep output; Execute performs the
mechanical merge based on these decisions.

**Slot mode per-repo sweep:** When the project is in a slot, knowledge
capture and doc sync run per-repo before the session-bound items:

```
Per-repo (primary + secondaries):
  a. protocol sweep against R's docs/protocols/
  b. update-claude-md against R's CLAUDE.md
  c. implementation-doc-sync against R's docs/

Session-bound (once, not per-repo):
  d. forage SWEEP
  e. ADR (primary workspace adr/)
  f. write-content (last — synthesises full branch narrative)
```

Per-repo ordering matches the current SKILL.md Step 3b-slot: protocols
first (captures rules), then CLAUDE.md (syncs conventions including new
protocols), then doc-sync (reads updated CLAUDE.md).

**Not in sweep:** Journal-entry is not a sweep item. Journal merge is
conditional within Execute (see Step 3), governed by Sweep decisions.

### Step 3 — Execute

**Nature:** SKILL.md-orchestrated phase. The SKILL.md calls LLM subagents
for code review and squash analysis, and calls `work_end_execute.py` for
the mechanical per-repo loop. The script cannot dispatch LLM subagents or
prompt the user — those remain SKILL.md responsibilities.

**New script:** `work_end_execute.py` — mechanical per-repo operations
(promote, rebase, push, stamp). Called by the SKILL.md between LLM steps.

**LLM vs script boundary:**

| Responsibility | Owner | Why |
|---------------|-------|-----|
| Code review | SKILL.md (LLM subagent) | Requires Agent() invocation |
| Squash analysis (Phase B) | SKILL.md (LLM per-repo loop) | Requires commit classification; writes `.squash-plan-<repo>.json` |
| Squash plan writing | SKILL.md | Writes subagent output to plan files for Phase C |
| Blessed repo prompt | SKILL.md (interactive) | Requires user input |
| Build verification level | SKILL.md (interactive) | Requires user input |
| Phase A: Rebase all repos | `work_end_execute.py rebase` | Mechanical; single call |
| Phase C: Apply squash + build + push + stamp | `work_end_execute.py land` | Mechanical; reads plan files; core multi-repo fix |
| Per-workspace promote | `work_end_execute.py promote` | Mechanical; once per unique workspace |
| Issue closing | `work_end_execute.py land` | Mechanical; once after all repos |
| Journal merge execution | `work_end_execute.py promote` | Mechanical; decision from Sweep |
| Progress tracking | `work_end_execute.py` | Crash recovery via `.execute-progress` |

**Sequence (per-repo in slot mode):**

```
1. Code review          — LLM subagent gate; blocks on critical findings
2. Promote artifacts    — once per unique workspace; workspace branch →
                          workspace main → project main (per routing config)
3. Publish blogs        — once per unique workspace; workspace main →
                          destination (blog-routing.yaml)
4. Archive plans        — plans/ → plans/attic/<branch>/
5. Close issues         — all COVERS issues via gh (ONCE, not per-repo)
6. Journal merge        — conditional: execute the merge decision from Sweep
                          (create, update, skip, etc.); mechanical only

--- Per-repo phases (eliminates LLM/script interleaving) ---

Phase A — Rebase (single script call, all repos):
7. Rebase               — branch onto base branch

Phase B — Squash analysis (SKILL.md LLM loop, per-repo):
8. Squash analysis      — LLM subagent for commit classification;
                          writes .squash-plan-<repo>.json per repo.
                          Resumable: repos with existing plan files
                          are skipped on restart.

Phase C — Land (single script call, all repos):
9. Apply squash plan    — mechanical: applies Phase B plan via git rebase
10. Build verification  — Java: mvn install; others: skip
                          (PRE-PUSH — if build fails, nothing pushed yet)
11. Push                — fork first (mandatory), then blessed repo (prompt)
12. Stamp + push stamp  — verify_stamp.py first, then stamp commit,
                          then push work branch to origin (--force-with-lease);
                          idempotent: skips if branch tip is already a
                          "chore: branch closed" commit

--- Post-loop (ONCE) ---

13. Stamp workspace     — stamp workspace branch (ONCE after per-repo loop)
14. Write .phase-a-complete marker (slot mode compatibility)
15. Write .landed marker — slot mode only; records branch, repos, landed
                          SHAs, timestamp (matches merge_slot() format)
```

**Three-phase rationale:** The per-repo steps are organized into three
phases to eliminate LLM/script interleaving in the SKILL.md's control
flow. The SKILL.md makes two script calls with an LLM loop between them:

| Phase | Steps | Owner | Per-repo? |
|-------|-------|-------|-----------|
| A — Rebase | 7 | `work_end_execute.py rebase` | All repos, single call |
| B — Squash | 8 | SKILL.md LLM per-repo loop | Yes — but pure LLM, no script interleaving |
| C — Land | 9-12 | `work_end_execute.py land` | All repos, single call |

Phase B is the only per-repo loop in the SKILL.md. It is pure analysis
(no script calls between iterations). The SKILL.md writes each subagent's
output to `.squash-plan-<repo>.json` in the slot directory (or workspace
`design/` for non-slot mode). Phase C reads these plan files and applies
them mechanically.

**Slot mode per-repo looping:**

```python
repos = parse_slot(slot_dir / ".slot")  # from .slot file
primary = repos[0]  # marked (primary) in .slot
promoted_workspaces: set[Path] = set()

# Step 1: code review — ONCE before per-repo loop (LLM subagent)
code_review(context)

# Steps 2-4: promotion, blogs, plans — once per unique workspace
for repo in repos:
    ws = resolve_workspace(repo)
    if ws not in promoted_workspaces:
        promote_and_publish(ws, repo.project, context)  # Steps 2-3
        verify_promotion(ws, repo.project)               # Post-promote gate
        archive_plans(ws, context)                        # Step 4
        promoted_workspaces.add(ws)

# Step 6: journal merge — ONCE (decision from Sweep)
journal_merge(context)

# Phase A: Rebase all repos (single script call)
work_end_execute("rebase", repos, context)              # Step 7

# Phase B: Squash analysis — LLM per-repo loop
for repo in repos:                                      # Step 8
    if not squash_plan_exists(repo):
        plan = squash_analysis_subagent(repo)
        write_squash_plan(repo, plan)  # .squash-plan-<repo>.json

# Phase C: Land all repos (single script call)
# Applies squash plans, builds, pushes, stamps           Steps 9-12
work_end_execute("land", repos, context)

# Post-loop steps (ONCE)
close_issues(context.covers, context.issue_repo)       # Step 5
stamp_workspace(slot_dir, context)                      # Step 13
write_landed_marker(slot_dir, repos, landed_shas)       # Step 15 (slot mode)
```

Issue closing, workspace stamping, and `.landed` marker write run once
after all per-repo work. Workspace branches are not project repos and
are not in `.slot` — they must be stamped separately. In non-slot mode,
the single workspace branch is stamped after the project branch; no
`.landed` marker is written (it is a slot-mode concept).

**Existing scripts reused:**

| Script | Called by Execute | Per-repo? | Modified? |
|--------|------------------|-----------|-----------|
| `close_artifacts.py` | Promotion + blog publish | Once per unique workspace | No |
| `verify_promotion.py` | Post-promote gate | Once per unique workspace | No |
| `land_branch.py rebase` | Step 7 | Yes | No |
| `land_branch.py push` | Step 10 | Yes | No |
| `land_branch.py stamp` | Step 11 | Yes | Yes — adds push |
| `verify_stamp.py` | Called by land_branch.py stamp | Yes (internal) | No |
| `artifact_promote.py` | Called by close_artifacts.py | Yes (internal) | No |
| `blog_dest.py` | Called by close_artifacts.py | No (once) | No |

**close_artifacts.py per-workspace calling:** In multi-repo slots,
`close_artifacts.py` runs once per unique workspace, not once per repo.
Workspace artifacts belong to the workspace; promoting the same artifacts
into multiple project repos creates duplicates. Each unique workspace is
promoted once, targeting the primary project for that workspace. `covers=`
is never passed — issue closing is handled by the orchestrator (Step 5)
after all repos complete.

**land_branch.py per-repo calling:** Each subcommand takes a project path
as its first positional arg. No shared state between calls. The
`cmd_push()` workspace stamp check is read-only — multiple repos can
verify the same `.artifacts-promoted` stamp.

**land_branch.py stamp modification:** `cmd_stamp()` currently writes the
stamp commit but does not push. The stamp must be pushed so remote
branches show as closed (unstamped remote branches look live to hygiene
scan and audit tools). Modification: after writing the stamp commit,
push the work branch to the fork remote (`--force-with-lease`). This
matches `merge_slot()`'s behaviour (slot_manager.py:938-943) where the
stamp is pushed immediately after being written.

**merge_slot() bypass:** The new Execute orchestrator bypasses
`slot_manager.py`'s monolithic `merge_slot()`. `merge_slot()` remains
available for other slot operations but is not used by work-end.

**Slot mode Execute variant:**

In slot mode, `land_branch.py` is NOT used for rebase/push/stamp. Slot
clones have a different remote topology: `origin` points to the on-disk
original repo, not a GitHub remote. `land_branch.py`'s `detect_topology()`
would resolve the wrong remotes.

Instead, the Execute orchestrator implements the slot-specific sequence
directly, using the three-phase structure:

```
Phase A — Rebase (script, all repos):
  Per-repo (slot clone):
    a. Rebase onto origin/main:
       git -C <slot>/<repo> fetch origin main
       git -C <slot>/<repo> rebase origin/main

Phase B — Squash analysis (LLM, per-repo):
    b. Squash (LLM subagent — same as non-slot)
       Writes .squash-plan-<repo>.json

Phase C — Land (script, all repos):
  Per-repo (slot clone):
    c. Apply squash plan (mechanical)
    d. Build verify (if applicable — same as non-slot)

  Per-repo (sync slot → original → GitHub):
    e. Push branch from slot clone to original:
       git -C <slot>/<repo> push origin <branch> --force-with-lease
    f. Land in original (fetch + ff-only merge):
       git -C <original>/<repo> fetch origin
       git -C <original>/<repo> merge --ff-only <branch>
    g. Push original to GitHub:
       git -C <original>/<repo> push origin main
    h. Stamp in slot clone (idempotent — skips if tip is already stamped):
       git -C <slot>/<repo> commit --allow-empty \
         -m "chore: branch closed — landed as <SHA> on main"
       git -C <slot>/<repo> push origin <branch> --force-with-lease
```

If `--ff-only` fails or push fails at step (f) or (g), retry from (e)
for the affected repo — max 3 attempts, matching `merge_slot()` behaviour.
After 3 failures, hard stop with manual instructions.

`land_branch.py` is used only in non-slot mode (single-repo and two-repo),
where the project repo has standard GitHub remote topology.

**Code review placement:** Runs as the first action in Execute. Reviews the
post-sweep diff (which is the final state — includes write-content, doc-sync
outputs). If review surfaces critical issues, fixes are applied and review
re-runs before any promotion begins.

**Build verification placement (changed from current):** Runs AFTER
rebase+squash, BEFORE push. Currently Step 8k runs after 8j which includes
push — meaning build failures leave pushed-but-broken code. Pre-push
placement means a failed build has nothing to roll back.

**Build failure recovery:** In non-slot mode, the rebase (step 7) modifies
the local base branch (main), not the work branch. The work branch retains
its original commits throughout. If the build fails after rebase+squash:

1. Reset base branch: `git reset --hard origin/<base_branch>`
2. Fix the build issue on the work branch
3. Re-run Execute from step 7 (progress journal skips steps 1-6)

The base branch has not been pushed, so remote state is unaffected. No
pre-squash backup ref is needed — the work branch is the backup. In slot
mode, the same principle applies: slot clone's main can be reset to
`origin/main` (the original repo's main), and the work branch in the
clone is untouched.

**Per-repo progress tracking:** `work_end_execute.py` maintains an
`.execute-progress` file in the slot directory (or workspace design/
for non-slot mode). Records which repos have completed each sub-step:

```
soredium=promoted
soredium=rebased
soredium=squashed
soredium=built
soredium=pushed:abc1234
soredium=stamped
casehub=promoted
casehub=rebased
```

Phase B (squash analysis) progress is tracked by the existence of
`.squash-plan-<repo>.json` files rather than `.execute-progress` entries.
The SKILL.md owns these files; the script reads them in Phase C.

On crash recovery, the script reads this file and skips completed steps.
Analogous to `merge_slot()`'s `.merge-progress` mechanism. The file is
deleted on successful completion of all repos.

**Stamp idempotency:** Before creating a stamp commit, the script checks
if the branch tip is already a `chore: branch closed` commit. If so, the
stamp step is skipped (only the push is retried if needed). This prevents
duplicate stamp commits on retry. The `repo=stamped` progress entry
provides the primary guard; the tip-check is defense-in-depth.

**Recovery contract:** `.execute-progress` is internal to
`work_end_execute.py`. The SKILL.md does not read or interpret it.
The lifecycle state tells the SKILL.md which phase to re-invoke; the
script handles per-repo granularity. `.execute-progress` may exist at
`closing:verified` (created during the `promote` subcommand, before
`promote_pass` fires). At `closing:promoted` and later, abort is blocked
by the transition table. The `clear_closing_markers` effect deletes
`.execute-progress` and `.squash-plan-*.json` on abort, covering the
`closing:verified` window where the file may already exist.

### Step 4 — Verify

**Nature:** Mechanical script — defense-in-depth audit for the
multi-repo close sequence. The primary fix for the multi-repo bug is
Execute's mechanical per-repo loop; Verify catches bugs in Execute itself.

**New script:** `verify_slot_close.py`

**Checks (all mechanically verifiable via git/gh/filesystem):**

```
Per-repo checks (for each repo in .slot, or single repo):
  □ Branch merged to main
    Command: git log main..<branch> --oneline
    Pass: empty output (excluding stamp commit)

  □ Branch stamped
    Command: git log -1 --format=%s <branch>
    Pass: starts with "chore: branch closed"

  □ Landing SHA valid
    Command: git merge-base --is-ancestor <SHA> main
    Pass: exit code 0

  □ Main pushed to remote
    Command: git log origin/main..main --oneline
    Pass: empty output

Workspace checks (ONCE, not per-repo):
  □ Workspace branch stamped
    Command: git log -1 --format=%s <workspace-branch>
    Pass: starts with "chore: branch closed"

Workspace artifact checks:
  □ Specs at expected destination (per routing config)
    Command: verify_promotion.py (existing script)

  □ ADRs at expected destination
    Command: verify_promotion.py

  □ Blogs published to destination
    Command: compare workspace blog/ against destination

  □ Plans archived
    Command: ls plans/attic/<branch>/

Issue checks:
  □ All COVERS issues closed
    Command: gh issue view <N> --json state (per issue)

Build check:
  □ Build passed (if applicable)
    Source: recorded by Execute via close_report.py step=build-verify
```

**Output:** `VERIFIED=yes` or `VERIFIED=no` with per-check results.

**Hard gate:** Blocks Step 5 (Close/archive) on any failure. The LLM
cannot rationalize past a script that reads git state across all repos.

**Calls or absorbs:**
- `verify_promotion.py` — called for artifact destination checks
- `hygiene_scan.py` — called for unpublished blog detection, unstamped branch detection
- `phase_b_gate.py` — logic absorbed (script removed)
- Slot completion gate (current SKILL.md S9 checklist) — logic absorbed

**Recovery on failure:** If Verify reports `VERIFIED=no`, the SKILL.md
presents the per-check failure list and offers recovery actions:

| Failure | Recovery |
|---------|----------|
| Branch not merged | Re-run Execute rebase+push for the affected repo |
| Branch not stamped | Re-run Execute stamp for the affected repo |
| Landing SHA invalid | Investigate: squash may have rewritten SHAs |
| Main not pushed | Re-run push for the affected repo |
| Artifact missing | Re-run close_artifacts.py for the affected repo |
| Issue still open | Re-run issue close |
| Build not recorded | Re-run build verification |

Most failures are recoverable by re-running the affected Execute sub-step.
The `.execute-progress` file preserves what succeeded; only the failing
step needs to re-run. After recovery, re-run Verify to confirm.

**Protocol compliance:** Satisfies `archive-requires-promotion-verification`
protocol — the `.artifacts-promoted` stamp is checked as part of the
verification pass.

### Step 5 — Close

**Nature:** Mechanical script.

**Sequence:**

1. Write `EPIC-CLOSED.md` on workspace branch
2. Archive slot to `slots/attic/<N>/` (slot mode only)
3. Return both repos to main (checkout + pull)
4. ARC42 stale scan (if ARC42STORIES.MD exists)
5. Write HANDOFF.md to workspace main
6. Session rename suggestion
7. Session close summary (tick-list of all steps)

**Existing scripts reused:**
- `branch_cleanup.py create-epic-closed`
- `branch_cleanup.py checkout-main`
- `close_report.py render`

---

## Testing Strategy

Every promotion and verification operation is a pure function of inputs —
testable in isolation with temp git repo fixtures.

### Test matrix

| Test | Input | Assert |
|------|-------|--------|
| Context: clean state | Valid branch, clean tree, no queue | Exit 0, all preconditions status=pass |
| Context: branch divergence | Branch behind base | Exit 0, branch_divergence status=needs_input |
| Context: queue gate mid-queue | plan_manager detect returns active | Exit 0, queue_gate status=needs_input |
| Context: dirty working tree | Uncommitted changes | Exit 0, clean_tree status=fail |
| Context: .meta missing | No .meta file | Exit 0, meta_exists status=needs_input |
| Context: .meta exists | .meta with valid SHA | Exit 0, meta_exists status=pass, PROJECT_SHA populated |
| Context: pause stack active | Branch in pause stack | Exit 0, pause_stack status=pass with info |
| Context: bad arguments | Missing project path | Exit 1, usage error |
| Workspace branch → workspace main | Artifact file on branch | File on main, commit exists |
| Workspace main → project main | Artifact on ws main, routing=project | File in project repo |
| Workspace main → project main | routing=workspace | No change to project |
| Workspace main → project main | routing=none | No change to project |
| Blog → destination | Entry on ws main, blog-routing.yaml | Entry at destination |
| Plan → attic | Plan file | Plan in `plans/attic/<branch>/` |
| Multi-repo slot promotion | 4 repos, mixed routing | Each repo promoted per own config |
| Stamp after squash | Rebased+squashed branch | Stamp SHA matches post-squash HEAD |
| Stamp with pre-squash SHA | SHA rewritten by squash | verify_stamp.py blocks stamp |
| Verify: all pass | Clean state | VERIFIED=yes |
| Verify: missing stamp | One repo unstamped | VERIFIED=no, identifies repo |
| Verify: missing artifact | Spec not at destination | VERIFIED=no, identifies file |
| Verify: unclosed issue | COVERS issue still OPEN | VERIFIED=no, identifies issue |
| Verify: unpushed main | Local ahead of origin | VERIFIED=no, identifies repo |
| Issue close once | 4 repos, covers=5,19 | gh issue close called once |
| Journal conditional | No journal entries | Journal merge skipped silently |
| Journal conditional | Journal entries exist | Journal merge runs |
| Build pre-push | Rebase+squash done, push not | mvn install succeeds on working tree |
| Execute resume (Phase B) | Squash analysis fails on repo 2 of 4 | Phase A skipped (all rebased), Phase B skips repo 1 (plan file exists), re-analyzes repo 2 |
| Execute resume (Phase C) | Push fails on repo 2 of 4 | Phases A-B skipped, Phase C skips repo 1 (stamped in progress file), resumes repo 2 from push |
| .landed marker | Slot mode, all repos pushed | .landed exists with correct SHAs and timestamp |
| Workspace dedup | 3 repos, 2 share workspace | close_artifacts.py called twice, not thrice |
| Stamp push (non-slot) | land_branch.py stamp completes | Work branch pushed to origin with stamp |
| --fix verify | UNSTAMPED branch, squashed commit | verify_stamp.py rejects bad SHA, stamp rolled back |

`verify_slot_close.py` IS the test assertions extracted into a runtime gate.

### Protocol compliance

Per `externalised-scripts-require-tests`: every new .py script ships with
pytest tests covering happy path, at least two edge cases, and bad argument
handling.

---

## SKILL.md Impact

~1400 lines → ~400 lines. Mechanical complexity moves into scripts.

The SKILL.md describes:
- The 5-step structure and what each does
- Red flags and common pitfalls
- What the LLM does in Sweep (creative judgment)
- How to handle Execute/Verify failures (re-run failing step)
- Slot mode vs single-repo differences

The SKILL.md does NOT describe:
- Per-file promotion mechanics (script handles)
- Routing resolution details (script handles)
- Git command sequences (script handles)
- Verification check details (script handles)

---

## Implementation Order

1. **`audit_slot_merges.py --fix`** — retroactive stamp remediation
2. **`verify_slot_close.py`** — the Verify gate (tests first)
3. **`work_end_context.py`** — Context script (tests first)
4. **`work_end_execute.py`** — Execute orchestrator (tests first)
5. **Work-end SKILL.md rewrite** — 5-step version
6. **`slot_manager.py` update** — remove `.phase-a-complete` dependency (deferred — compatibility marker written by Execute until then)

---

## Scripts Inventory (post-restructure)

### New scripts

| Script | Step | Purpose |
|--------|------|---------|
| `work_end_context.py` | 1 | Unified context + pre-conditions |
| `work_end_execute.py` | 3 | Per-repo orchestrator |
| `verify_slot_close.py` | 4 | Unified verification gate |

### Retained scripts

| Script | Called by | Purpose |
|--------|----------|---------|
| `close_artifacts.py` | Execute | Promotion + blog publish |
| `land_branch.py` | Execute | Rebase + push + stamp (modified: `cmd_stamp` adds push) |
| `verify_stamp.py` | land_branch.py | Content landing verification |
| `verify_promotion.py` | Execute (post-promote) + Verify | Artifact destination check |
| `artifact_promote.py` | close_artifacts.py | Individual promotion ops |
| `blog_dest.py` | close_artifacts.py | Blog destination resolver |
| `workspace_artifacts.py` | close_artifacts.py | Artifact path resolver |
| `branch_recon.py` | Context | Branch state gathering |
| `branch_cleanup.py` | Close | EPIC-CLOSED, checkout-main |
| `close_report.py` | Execute + Close | Report generation (modified: `build-verify` step type added) |
| `hygiene_scan.py` | Called by Verify | Workspace hygiene checks |
| `common.py` | All | Shared utilities |

### Removed scripts

| Script | Reason |
|--------|--------|
| `phase_a_complete.py` | Marker write moved into Execute |
| `phase_b_gate.py` | Logic absorbed into verify_slot_close.py |

---

## Risks

**merge_slot() bypass and .phase-a-complete callers:** The new Execute
orchestrator bypasses `slot_manager.py`'s `merge_slot()`. Analysis of
callers: `merge_slot()` is callable via the `slot_manager.py merge-slot`
CLI subcommand (manual use). `scan_ready()` uses `.phase-a-complete` to
list merge-ready slots and is callable via the `scan-ready` subcommand.
No other skills call `merge_slot()` directly — the current work-end
SKILL.md implements its own slot close sequence (S3-S8) with inline git
commands. The compatibility marker must be retained for `scan_ready()`
until `slot_manager.py` is updated (implementation step 6).

**Routing implicit disable:** The routing vocabulary does not support an
explicit disable value. Absence of files in a category directory serves
as implicit disable — `close_artifacts.py` skips empty categories. If an
explicit `none` routing value is needed, it can be added to `routing.py`
as a future enhancement without changing the Execute orchestrator.

**Journal merge conditional:** Journal merge is conditional on entries
existing. `branch_recon.py` still validates journal state — its output
contract (JSON with `journal_validation` field) must remain stable even
when Execute skips the merge.

**Squash SHA ordering:** Stamps must be written AFTER squash (garden entry
GE-20260721-94263a). The Execute sequence enforces this: squash (step 8)
before stamp (step 11). The current SKILL.md already has this ordering
but the per-repo loop makes it explicit.

---

## Issue #95 Cross-reference

Issue #95 ("Mechanize LLM-executed state-changing operations across
skills") identifies 10 HIGH-severity findings for work-end. This
restructure addresses a subset:

| # | Finding | Status |
|---|---------|--------|
| 1 | Slot stamp commits (inline git) | **Addressed** — `land_branch.py stamp` per repo |
| 2 | Slot merge+push (inline git) | **Addressed** — `land_branch.py rebase/push` per repo |
| 3 | Hygiene scan stamp (inline git) | **Not addressed** — remains inline in SKILL.md |
| 4 | Journal merge commit/push | **Not addressed** — remains inline in SKILL.md |
| 5 | Blessed repo push | **Partially addressed** — fork push via `land_branch.py push`; blessed repo delivery remains interactive |

Findings 3-4 remain as open items in issue #95. This restructure does
not attempt to close #95 — it addresses the multi-repo bug and skill
complexity, which overlap with #95's scope.

---

## Worklog Integration

The existing scripts already emit worklog events:
- `land_branch.py cmd_stamp()` calls `_wl.record_work_end()`
- `slot_manager.py merge_slot()` calls `_wl.record_slot_merge()`
- `lifecycle.py commit_transition()` calls `_emit_to_worklog()`

The restructured architecture preserves these:
- `land_branch.py` continues to emit `record_work_end` on stamp (unchanged)
- Lifecycle transitions continue to emit via `commit_transition()` (unchanged)
- `merge_slot()` worklog emission is NOT needed — work-end bypasses it;
  `land_branch.py` and lifecycle transitions cover the same events

`work_end_execute.py` does not need its own worklog emission — it
delegates to scripts that already emit. No worklog gaps introduced.
