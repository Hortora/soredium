# Review Handlers

## code_review

Invoke `code-review` on the diff specified by DIFF_RANGE.

**Security-audit suppression:** Do NOT offer security-audit escalation —
branch-audit Robustness dimension handles security escalation.

After code-review completes, persist any unresolved findings to
`$WORKSPACE/.audit/findings.jsonl` via `append_finding` from
`project/findings.py` with `category: "review"` and `source: "code-review"`.

Mark done with `step_done=code_review produced=N` (N = finding count).

**Budget limits are not gates.** If code-review reports a budget warning
("coverage may be incomplete"), proceed. The forcing function processes
whatever findings were collected. Surface the warning text.

## branch_audit_dimension

The orchestrator yields each dimension separately:
`branch_audit_conformance`, `branch_audit_coherence`,
`branch_audit_structure`, `branch_audit_robustness`.

Run the specific dimension from `branch-audit` on the full branch diff.
The DIMENSION field tells you which one:

| Dimension | Key question |
|-----------|-------------|
| Conformance | Did we build what we said we'd build? |
| Coherence | Does the branch hold together as a whole? |
| Structure | Are the boundaries right? |
| Robustness | What could go wrong? |

Append findings to `$WORKSPACE/.audit/findings.jsonl` with
`source: "branch-audit"` and `dimension: "<DIMENSION>"`.

Mark done with `step_done=<ACTION> produced=N`.

**Budget limits are not gates.** Complete what you can, report what
you skipped.

## loose_ends

Run the loose ends sweep script:

```bash
python3 work-end/loose_ends_sweep.py workspace=$WORKSPACE project=$PROJECT branch=$BRANCH cycle_start=<ISO>
```

Pass `cycle_start` as the timestamp when code_review started — this
filters out findings just written by prior review steps.

Supplement script output with conversation-context items
("I'll come back to this") and append those to `findings.jsonl`.

Mark done with `step_done=loose_ends produced=N`.

## forcing_function (HARD GATE)

Read all open findings from `$WORKSPACE/.audit/findings.jsonl` via
`read_findings` from `project/findings.py`. OPEN_FINDINGS tells you
how many are open. Present grouped by category:

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
| **Fix** | Fix the issue now. Status -> resolved, resolution includes commit SHA |
| **File** | Create a GitHub issue. Status -> filed, resolution includes issue number |
| **Dismiss** | Not a real problem. Status -> dismissed, resolution includes reason |

**Severity constraints:**

| Severity | Fix | File | Dismiss |
|----------|-----|------|---------|
| CRITICAL | Yes | Yes  | No      |
| WARNING  | Yes | Yes  | Yes     |
| NOTE     | Yes | Yes  | Yes     |

**Re-review after fixes:** When "Fix" creates new commits, re-run
code-review on those commits only. New findings join the queue.
Branch-audit dimensions do not re-run.

**Batch operations:**
- "File all remaining as single issue" — one issue with checklist
- "File each remaining" — one issue per finding
- "Dismiss all NOTEs" — blanket dismiss with user-provided reason

Each resolution is persisted to `findings.jsonl` immediately.
No finding survives branch close with status `open`.

Mark done with `step_done=forcing_function`.

## review_rebase

Code-review ONLY on the conflict-resolution diff specified by DIFF_RANGE.

Scope constraint: NO branch-audit, NO loose-ends sweep, NO forcing function.
This is a scoped review of conflict-resolution commits only.

If findings: mini-gate with Fix/File/Dismiss (same severity constraints).
Persist to findings.jsonl. All findings must be resolved before continuing.
