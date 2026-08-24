---
name: work-end
description: >
  Use when the current branch is complete and ready to close — user says
  "work end", "close this branch", or "wrap up this issue". Must be invoked
  from a branch with active work or from main with a .plan. On main, skips
  branch-specific steps (merge, stamp, rebase, squash). Replaces "epic close".
---

# work-end

Closes the current branch cleanly. A Python orchestrator
(`work_end_orchestrator.py`) drives the close sequence, yielding to the
LLM only at judgment points. The LLM cannot skip what it cannot see.

<HARD-GATE>
**Review is mandatory before any push.** The orchestrator yields
`ACTION=review` before any Execute step. No exempt branches.

**Doc sync is mandatory.** `update-claude-md` and `implementation-doc-sync`
default to ON in the sweep config. They catch convention drift.

**Main-branch mutations go through work-end only.** Never run
`git checkout main && git merge <branch>` manually.

**Never suggest deferring work-end to another session.** Session-bound items
(forage SWEEP, write-content) are permanently lost if the session ends without
them. All other steps are Python scripts that consume no meaningful context.
Execute the full sequence every time. Session length is not a factor.
</HARD-GATE>

### Red Flags — thoughts that mean STOP

| Thought | Reality |
|---------|---------|
| "This branch was mechanical" | Mechanical changes have mechanical bugs. Review catches them. |
| "The diff is small" | Small diffs have the highest bug-per-line ratio. |
| "I'll promote artifacts manually" | Run close_artifacts.py. The verification gate catches you. |
| "I'd recommend skipping the sweep" | Present defaults ON. The user decides. |
| "Session is getting long" | Session length is never a reason to skip session-bound items. |

---

## Pre-close — Context Resolution

### Path resolution (run first, always)

```bash
python3 ~/.claude/skills/project/ctx.py
```

Use the printed values as concrete strings in all subsequent commands:
`WORKSPACE`, `PROJECT`, `CURRENT_BRANCH`, `PROJECT_SHA`, `ISSUE_N`,
`COVERS`, `OWNER_REPO`, `BASE_BRANCH`, `META_STATE`, `HAS_PLAN`,
`PLAN_PATH`, `ON_MAIN`, `IN_SLOT`, `SLOT_PATH`.

### Lifecycle auto-resolve and entry

Read `META_STATE` from ctx.py. Auto-resolve transient states:

| `META_STATE` | Action |
|-------------|--------|
| `scaffolded` | `lifecycle.py transition <PLAN_PATH> auto_setup` then `commit-transition from_state=scaffolded new_state=active event=auto_setup` |
| `transitioning` | `lifecycle.py transition <PLAN_PATH> auto_refresh` then `commit-transition from_state=transitioning new_state=active event=auto_refresh` |
| `active` | Ready — proceed below |
| `closing:*` | Already closing — skip to the orchestrator loop, pass current state |

Then enter close sequence:
```bash
python3 ~/.claude/skills/project/lifecycle.py transition <PLAN_PATH> work_end
python3 ~/.claude/skills/project/lifecycle.py commit-transition <PLAN_PATH> from_state=active new_state=closing:review event=work_end
```

### Main-mode detection

Read `ON_MAIN` from ctx.py. If `ON_MAIN=yes`, work-end runs in main mode.
The orchestrator automatically skips branch-specific steps (rebase, squash,
stamp). Key differences:

- **Diff base:** `drained-sha` from `.plan` (or `project-sha` if first close)
- **After land:** push only (no merge, no stamp)
- **Lifecycle after land:** `merge_pass` and `stamp_pass` fire with empty evidence
- **Cleanup transition:** `cleanup_main` → `drained` (plan persists)
- **Scaffold cleanup:** Keep `.plan`, remove only `JOURNAL.md`
- **Guidance after close:** "Consider a feature branch for non-trivial work."

### Context preconditions

```bash
python3 work-end/work_end_context.py workspace=<WORKSPACE> project=<PROJECT>
```

Parse JSON output. Handle:

| Precondition | Status | Action |
|-------------|--------|--------|
| `branch_alignment` | `fail` | Hard stop — both repos must be on same branch |
| `clean_tree` | `fail` | Hard stop — see DIRTY TREE PROTOCOL below |
| `meta_exists` | `needs_input` | Infer issue from branch name, confirm with user |
| `meta_exists` | `pass` | Proceed |

<DIRTY-TREE-PROTOCOL>
**When `clean_tree` fails, the ONLY acceptable actions are:**

1. `git stash push -u -m "work-end: stashing uncommitted changes"`
2. `git add -A && git commit -m "wip: uncommitted changes before work-end"`

**NEVER use `git reset --hard`, `git checkout -- .`, or `git clean -fd`.**
These DESTROY uncommitted changes — which may belong to another session
working in the same repo. A `git reset --hard` destroyed hours of work
in a real incident (Aug 2026).
</DIRTY-TREE-PROTOCOL>

### Queue gate

If `HAS_PLAN=yes`: run `plan_manager.py detect` to check queue state.
If remaining uncompleted items exist, redirect: "Queue has N remaining
issues. Run `work next` to advance, or pass `confirm-partial` to close."

After confirming close, run `complete_active_issue`.

---

## Close Sequence — Orchestrator Loop

After context is resolved and `closing:review` is entered, call the
orchestrator in a loop. It runs mechanical steps (promote, rebase,
push, stamp, verify, cleanup) internally and yields one `ACTION=` line
when it needs LLM judgment.

```
loop:
  output = run("python3 work-end/work_end_orchestrator.py
    workspace=<WORKSPACE> project=<PROJECT> branch=<BRANCH>
    base_branch=<BASE_BRANCH> meta_state=<META_STATE>
    covers=<COVERS> issue_repo=<OWNER_REPO>
    in_slot=<IN_SLOT> slot_path=<SLOT_PATH>
    on_main=<ON_MAIN>
    [sweep_selected=<CSV>] [skip_step=<NAME>]
    [abort=yes] [conflict_resolved=yes]")
  parse ACTION= from output

  if ACTION=complete       → print SUMMARY, render close report, done
  if ACTION=error          → report ERROR and REASON to user
  if ACTION=review         → run review handler below
  if ACTION=review_rebase  → code-review on DIFF_RANGE only (see below)
  if ACTION=sweep_config   → present toggle UI, report via sweep_selected=
  if ACTION=squash         → classify commits, write .squash-plan-<repo>.json
  if ACTION=trajectory     → draft enrichment notes (non-blocking)
  if ACTION=verify_recover → present verify failures, offer recovery
  if ACTION=user_input     → dispatch on CONTEXT= (see below)
  if ACTION in [forage, protocol, update_claude_md, impl_doc_sync,
                adr, write_content] → invoke the named skill
  go to loop
```

After the LLM completes an action, it calls the orchestrator again.
The orchestrator validates the action was completed (checks files,
git state, findings.jsonl), marks progress, and yields the next action.

---

## Action Handlers

### ACTION=review

Full review cycle. Run all four sub-steps in order:

1. **Code review** — invoke `code-review` on `DIFF_RANGE`.
   - Do NOT offer security-audit escalation — branch-audit Robustness
     handles security.
   - Persist unresolved findings to `$WORKSPACE/.audit/findings.jsonl`
     via `append_finding` from `project/findings.py` with
     `category: "review"`, `source: "code-review"`.

2. **Branch audit** — invoke `branch-audit` on the full branch diff.
   Four dimensions: Conformance, Coherence, Structure, Robustness.
   Append findings to `findings.jsonl` after each dimension.

3. **Loose ends sweep:**
   ```bash
   python3 work-end/loose_ends_sweep.py workspace=<WS> project=<PROJ> branch=<BRANCH> cycle_start=<ISO>
   ```
   Pass `cycle_start` as timestamp when review started — filters out
   findings just written by sub-steps 1 and 2. The LLM supplements
   script output with conversation-context items ("I'll come back to
   this") and appends to `findings.jsonl`.

4. **Forcing function (HARD GATE)** — read all open findings from
   `findings.jsonl` via `read_findings`. Present grouped by category:

   ```
   Open findings — N items require resolution before branch close

   AUDIT (branch-audit):
     1. [conformance/WARNING] ...
   REVIEW (code-review):
     2. [WARNING] ...
   LOOSE-END:
     3. [WARNING] ...
   ```

   **Triage filtering:** Only present findings whose status is `open`.

   Resolution options per finding:

   | Option | Effect |
   |--------|--------|
   | **Fix** | Fix now. Status → `resolved` with commit SHA |
   | **File** | Create GitHub issue. Status → `filed` with issue number |
   | **Dismiss** | Not real. Status → `dismissed` with reason |

   Severity constraints: **CRITICAL cannot be dismissed.**

   **Re-review after fixes:** When "Fix" creates commits, re-run
   code-review on those commits only. New findings join the queue.
   Branch-audit does not re-run.

   **Batch operations:** "File all remaining as single issue", "File
   each remaining", "Dismiss all NOTEs".

   Each resolution persists to `findings.jsonl` immediately. No finding
   survives branch close with status `open`.

**Budget limits are not gates.** If code-review or branch-audit reports
a budget warning ("coverage may be incomplete"), proceed. Surface the
warning in the close summary.

### ACTION=review_rebase

Code-review only on `DIFF_RANGE` (conflict resolution commits). No
branch-audit, loose ends, or forcing function. If findings: mini-gate
with Fix/File/Dismiss (same severity constraints). Persist to
`findings.jsonl`. All findings must resolve before proceeding.

### ACTION=sweep_config

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

After user confirms, pass `sweep_selected=forage,protocol,...` to the
orchestrator with the selected items on the next call.

### ACTION=forage

Invoke `forage` SWEEP — while context is full. First in sweep order.

### ACTION=protocol

Invoke `protocol` SWEEP.

### ACTION=update_claude_md

Invoke `update-claude-md`.

### ACTION=impl_doc_sync

Invoke `implementation-doc-sync`.

### ACTION=adr

Invoke `adr`.

### ACTION=write_content

Invoke `write-content` (diary type). Run last — synthesises full
branch narrative. Session-bound — cannot be deferred.

### ACTION=squash

Classify commits per repo and write `.squash-plan-<repo>.json`. Repos
with existing plan files are skipped on restart.

**Slot mode marker:** After squash completes for all repos, if
`IN_SLOT=yes`:
```bash
python3 work-end/work_end_execute.py write-marker slot_path=<SLOT_PATH> branch=<BRANCH>
```

### ACTION=trajectory

Non-blocking — if this fails or the user declines, continue. Does not
block close.

1. **Generate trajectory note** — one-line per completed issue:
   "This work suggests X next because Y."

2. **Propose enrichment updates** — how completed work shifts the
   landscape for 2-3 sibling/related issues. Present as table:

   | Issue | Field | Old | New | Reason |
   |-------|-------|-----|-----|--------|
   | #192 | readiness | needs-design | ready | Schema it depends on just landed |

3. **User confirms → persist:**
   ```bash
   python3 scripts/enrichment.py trajectory --issue <N> --repo <REPO> --text "<note>" --branch <BRANCH>
   python3 scripts/enrichment.py upsert --issue <N> --repo <REPO> --readiness ready
   ```

### ACTION=user_input

Dispatch on `CONTEXT=`:

**CONTEXT=arc42_scan:** If `ARC42STORIES.MD` exists, scan for stale
statuses and offer fixes.

**CONTEXT=session_rename:** Suggest a descriptive session name if
auto-generated.

**CONTEXT=garden_feedback:** Record which garden entries were useful.

1. Review `gardenSearch` results from this session. Collect GE-IDs.
2. Read `## Garden Entries Consulted` from HANDOFF.md (propagated from
   earlier sessions).
3. Combine. If empty, skip silently.
4. Assess relevance per 5-level scale:
   - HIGHLY_RELEVANT — directly solved the problem
   - RELEVANT — useful and informed the work
   - PARTIALLY_RELEVANT — tangentially related
   - NOT_RELEVANT — appeared but wasn't useful
   - OUTDATED — right topic but advice no longer applies (requires `stack`)
5. Group by outcome, call `gardenFeedback` once per group:
   ```
   gardenFeedback(geIds: "GE-...|GE-...", outcome: "RELEVANT",
       issueRepo: "<OWNER_REPO>", issueNumber: <ISSUE_N>)
   gardenFeedback(geIds: "GE-...", outcome: "OUTDATED",
       stack: "quarkus:3.36.1|jdk:26",
       issueRepo: "<OWNER_REPO>", issueNumber: <ISSUE_N>)
   ```
6. If call fails (MCP unavailable), log warning and continue — never block.

**CONTEXT=notes:** If `$WORKSPACE/.notes/NOTES.md` exists, surface the
most recent date section. Offer to append:
> "Anything worth noting for future sessions? (Enter to skip)"

If user provides notes, append under today's date and commit:
```bash
git -C $WORKSPACE/.notes add NOTES.md
git -C $WORKSPACE/.notes commit -m "notes: work-end"
```
Skip silently if no `.notes/` directory exists.

**CONTEXT=step_failed:** A judgment step failed after 3 retries. Present
`STEP` and `REASON` from orchestrator output. Options: skip (pass
`skip_step=<NAME>`), retry, or abort (pass `abort=yes`).

**CONTEXT=rebase_conflict:** Rebase conflict needs manual resolution.
After user resolves, pass `conflict_resolved=yes` to the orchestrator.

### ACTION=verify_recover

`verify_slot_close.py` returned failures. Present per-check failures
and offer recovery (re-run the failing Execute sub-step).

### ACTION=complete

Print `SUMMARY` from the orchestrator. Render the close report:
```bash
python3 work-end/close_report.py render <WORKSPACE>/.close-report.json
```

Close sequence is done.

---

## Common Pitfalls

| Mistake | Why It's Wrong | Fix |
|---------|----------------|-----|
| Skip code review | #1 failure mode | Review is a HARD GATE |
| Manual artifact promotion | Leaves orphans | Orchestrator runs close_artifacts.py |
| Recommend skipping sweep | Loses session-bound content | Present defaults ON |
| `git reset --hard` on dirty tree | Destroys other sessions' work | `git stash push -u -m "..."` |
| Suggest deferring to another session | Session-bound items lost forever | Execute full sequence every time |
| Stamp before squash | SHAs become unreachable | Orchestrator enforces order |
| Push main without verify | Broken content on remote | Verify gate blocks close |

---

## Skill Chaining

**Invoked by:**
- `work` — routing skill, when user says "work end"
- `executing-plans` — after all plan tasks complete
- `subagent-driven-development` — final close step

**Invokes:**
- `code-review` — review handler
- `branch-audit` — review handler (four dimensions)
- `forage` — SWEEP
- `protocol` — SWEEP
- `update-claude-md` — sweep
- `implementation-doc-sync` — sweep
- `adr` — sweep
- `write-content` — sweep (last)
- `publish-blog` — via close_artifacts.py
- `git-squash` — squash handler

**Complements:**
- `work` — routing entry point
- `work-pause` — alternative (pause vs. close)
- `work-start` — opens branches; work-end closes them
- `work-slot` — slot detection triggers per-repo loop in Execute
- `evidence-before-claims` (protocol) — per-boundary evidence gate

**Reads from:** `ctx.py`, `.plan`, `.pause-stack`, CLAUDE.md,
`.close-progress`, `.execute-progress`, `.squash-plan-*.json`,
`findings.jsonl`
