# Unified Review and Findings Persistence

**Date:** 2026-08-19
**Status:** Reviewed (Standard, 3 rounds × 4 dimensions, $48.56)
**Decisions:** [decisions.md](decisions.md)

## Problem

Work-end misses gates. Code review is buried in Step 3 (Execute), after
the entire Sweep (forage, protocol, doc sync, write-content). The review
itself is a per-line checklist — it catches mutable defaults and unawaited
coroutines but not "you didn't implement requirement 3" or "this branch
has three deferred TODOs nobody tracked."

Findings are ephemeral. Code review findings, design review deferred
items, completeness audit gaps, and loose ends all die with the session.
The next session has no idea what was deferred, dismissed, or left
unfinished. Only hygiene findings (stale branches, unrecovered artifacts)
persist via `findings.jsonl`.

The blog entries from 2026-08-17 ("The Feedback Loop That Wasn't" and
"Four Fixes, One Already Done") diagnosed this gap and identified the
architecture: extend `findings.jsonl` to cover all finding categories,
with accumulation across sessions and a forcing function at work-end.

## Solution Overview

Four architectural components:

1. **Branch audit** — new skill for holistic branch-level code review
2. **Loose ends sweep** — captures deferred/skipped/missing items at
   every lifecycle gate
3. **Findings persistence** — extends `findings.jsonl` to all categories
4. **Forcing function** — drains all accumulated findings at work-end

Two implementation tasks:

5. **Lifecycle integration** — reorders work-end and adds sweep to handover
6. **Skill cleanup** — removes deprecated skills, preserves VBC as protocol

## Component 1 — Branch Audit

New skill `branch-audit`. Reviews the full branch diff across four
dimensions (D1, D6).

### Dimensions

Each dimension includes (but is not limited to) the listed sub-concerns.

**Conformance** — did we build what we said we'd build?

The reference document varies by context:
- With spec: implementation vs spec
- With issue only: implementation vs issue description and acceptance criteria
- With neither: implementation vs commit messages and conversation
  context (lightest form — confirms code does what was described;
  fewer, lower-severity findings expected)

Includes: issue conformance, completeness, missing requirements, gaps in
edge case coverage, untested scenarios, acceptance criteria not met.

**Coherence** — does the branch hold together as a whole?

Includes: internal consistency, uniform patterns across changes, naming
consistency, architectural fit with the rest of the codebase.

**Structure** — are the boundaries right?

Includes: decomposition, module boundaries, dependency cleanliness,
separation of concerns, file organisation.

**Robustness** — what could go wrong?

Includes: failure modes, error paths, surface-level security (auth,
input validation, data exposure), regression risk (downstream callers
affected), boundary conditions, silent failures.

When Robustness identifies security concerns (auth, PII, payment, user
input code), it offers to escalate to `security-audit` for the full
OWASP pass (D7).

At work-end, branch-audit's Robustness dimension owns the security-audit
escalation. code-review suppresses its own escalation offer at work-end
to avoid presenting the same offer twice. During development (per-commit
review), code-review continues to offer security-audit escalation as
today.

### Execution Model

Runs inline in the current session. Single pass per dimension. No
external sessions, no adversarial rounds, no watchdog crons.

Produces findings with severity (CRITICAL / WARNING / NOTE). Findings
are appended to `findings.jsonl` (Component 3) after each dimension
completes — not batched after all four. This ensures partial progress
survives session interruption. Dedup prevents duplicates on re-run.

### Relationship to design-review

Branch-audit is an independent skill, not a child of design-review.
Both share a common lifecycle model documented in `review-tiers.md`:

- `review-tiers.md` maps lifecycle points to dimensions and depths.
  Post-implementation is one lifecycle point, currently marked "future."
- Branch-audit implements the post-implementation lifecycle point with
  a single-pass inline execution model — fundamentally different from
  design-review's multi-round adversarial model.
- `review-tiers.md` should be updated to change the post-implementation
  row from "future" to "Implemented by: branch-audit" — completing the
  lifecycle model, not creating an ownership dependency.

The four dimensions (Conformance, Coherence, Structure, Robustness) are
shared vocabulary between design-review and branch-audit. Cross-cutting
remains a design-review synthesis step and does not apply to branch-audit.

### Relationship to code-review

Both run at work-end (D10). code-review is the per-line checklist (safety,
types, async, testing, performance). Branch-audit is the holistic review
(conformance, coherence, structure, robustness). Different concerns, both
valuable at the final gate.

During development, only code-review runs (per-commit). Branch-audit
requires the full branch diff and only runs at lifecycle gates.

## Component 2 — Loose Ends Sweep

First-class concept for capturing unfinished work (D8). Distinct from
epic hygiene, which checks workspace/branch lifecycle state (branches
closed correctly, artifacts promoted, blogs published).

### What it checks

- Deferred plan items (from `.plan`)
- Skipped or deferred review findings from this session
- TODOs in code referencing this branch/issue
- Open findings from prior sessions (reads `findings.jsonl`)
- Uncommitted changes
- Unresolved "I'll come back to this" items from conversation context

### Execution model

Hybrid skill (SKILL.md) — mechanical checks via script calls, conversation
recall via LLM. Same pattern as handover combining `ctx.py` calls with
conversation memory.

| Check | Method | Notes |
|-------|--------|-------|
| Deferred plan items | Script: read `.plan` | Mechanical |
| Skipped/deferred findings | Script: read `findings.jsonl` where `status: open` | Writers persist unresolved findings at source |
| TODOs referencing branch/issue | Script: code search scoped to changed files | Mechanical |
| Open findings from prior sessions | Script: read `findings.jsonl` | Mechanical |
| Uncommitted changes | Script: `git status` | Skipped at work-end (Step 1 `clean_tree` handles it) |
| "I'll come back to this" | LLM: conversation recall | Best-effort — marked as LLM-sourced in output |

At handover, all six checks run (uncommitted changes is the primary
signal since work-end Step 1 hasn't run). At work-end, the uncommitted
changes check is skipped — already handled by Step 1 Context.

### Lifecycle behavior

**At handover:** capture and persist only. New findings written to
`findings.jsonl`. No forcing function — session is ending, work continues.

**At work-end:** capture, persist, then force-resolve all accumulated
findings (Component 4).

### Relationship to epic hygiene

Same persistence mechanism (findings.jsonl), different concerns:

| Check | Epic hygiene | Loose ends sweep |
|-------|-------------|-----------------|
| Branches closed correctly | Yes | No |
| Artifacts promoted | Yes | No |
| Main diverged from remote | Yes | No |
| Deferred review findings | No | Yes |
| Skipped plan items | No | Yes |
| TODOs referencing this branch | No | Yes |
| Open findings from prior sessions | No | Yes |

Same pipe, different taps.

## Component 3 — Findings Persistence

Extends the existing findings architecture (D9). Storage format is JSONL
(one JSON object per line) at `$WORKSPACE/.audit/findings.jsonl`. Writers
append lines under an advisory flock — lock hold time is O(line), not
O(file) as with JSON read-modify-write, making concurrent session
contention negligible.

### Current format (hygiene only)

```json
{
  "category": "hygiene",
  "check": "unrecovered_artifact",
  "detail": "blog entry on closed branch issue-200",
  "status": "open",
  "timestamp": "2026-08-17T14:30:00Z"
}
```

### Extended format

```json
{
  "category": "review|audit|loose-end|hygiene",
  "dimension": "conformance|coherence|structure|robustness|null",
  "severity": "critical|warning|note",
  "check": "missing-requirement|dead-code|deferred-plan-item|...",
  "location": "src/sync.py:42|spec:req-3|plan:add-integration-tests",
  "detail": "Requirement 3 (user notifications) not implemented",
  "source": "branch-audit|code-review|loose-ends-sweep|hygiene-scan",
  "branch": "issue-123-feature-name",
  "status": "open|resolved|dismissed|filed",
  "resolution": "fixed in abc1234|filed as #456|dismissed: out of scope|null",
  "timestamp": "2026-08-19T10:00:00Z"
}
```

**`location`** is the stable dedup anchor — a reference to WHERE the
finding was found, independent of how it's described:

| Finding source | Location format | Example |
|----------------|----------------|---------|
| Code issue (file-level) | `file:line` | `src/sync.py:42` |
| Requirement gap | `spec:§N` or `spec:req-N` | `spec:req-3` |
| Plan item | `plan:item-slug` | `plan:add-integration-tests` |
| Hygiene (artifact) | `artifact:file:branch` | `artifact:blog.md:issue-200` |
| Hygiene (branch) | `branch:name` | `branch:issue-200` |
| TODO in code | `file:line` | `handler.py:88` |
| Session context (LLM-sourced) | `context:anchor` | `context:edge-case-handler` |

`location` is distinct from `detail`: location identifies WHAT finding
(stable across sessions), detail describes it for humans (may vary).
When `location` is absent (legacy hygiene entries), readers fall back
to `detail` for dedup.

### Semantics

- **Dedup** by `(check, location, branch)` — branch-scoped findings are
  independent per branch; workspace-level findings use `branch: null`
  and dedup without branch (preserving current hygiene behavior).
  When `location` is absent (legacy entries), falls back to
  `(check, detail, branch)` for backward compatibility
- **Accumulate** across sessions — findings persist until explicitly resolved
- **Read at session entry** — `work_health.py` `check_prior_findings()`
  already reads `$WORKSPACE/.audit/findings.json` and surfaces open
  findings (implemented at line 427, in `ENTRY_CHECKS` list at line 456).
  `hygiene_scan.py` `persist_findings()` already writes hygiene findings
  to the same path (implemented at line 246). Migration to `.jsonl`
  format requires updating both functions and enhancing the display to
  show severity and category.
- **Resolution statuses:**
  - `resolved` — fixed in code (include commit SHA)
  - `filed` — created as GitHub issue (include issue number)
  - `dismissed` — not a real problem (include reason)

### Who writes

Each writer persists findings immediately after its step completes —
before the next step begins. This ensures partial progress survives
session interruption at any point in the pipeline.

| Source | Category | When | Persistence point |
|--------|----------|------|-------------------|
| `hygiene_scan.py` | `hygiene` | work-end, handover | After scan completes |
| `code-review` | `review` | work-end Step 2.1 | After Step 2.1 completes, before Step 2.2 |
| `branch-audit` | `audit` | work-end Step 2.2 | After each dimension (§1 execution model) |
| loose ends sweep | `loose-end` | work-end Step 2.3, handover | After sweep completes |

### Who reads

- `work_health.py` at session entry — surfaces all open findings
- Forcing function at work-end — presents all open findings for resolution
- Loose ends sweep — reads prior findings as part of its scan
  (filters by timestamp: only findings older than current work-end
  cycle start, to avoid double-counting current-session findings)

### Reader contract

JSONL is append-only — writers blind-append, never read. Dedup and
status resolution are reader-side operations. All readers (work_health.py,
forcing function, loose ends sweep) implement the same contract:

1. **Group** entries by dedup key `(check, location, branch)` — when
   `location` is absent, fall back to `(check, detail, branch)`
2. **Status:** latest timestamp within the group determines the finding's
   current status. An `open` entry at T3 re-opens a finding `resolved`
   at T2. (If code-review independently surfaces the same issue after
   a fix, the fix was incomplete — re-opening is correct.)
3. **Severity:** highest severity across ALL entries in the group,
   regardless of status. A CRITICAL from branch-audit is not downgraded
   by a WARNING re-open from code-review.
4. **Source:** comes from the entry that established the current severity
   (the highest-severity entry)
5. **Resolution updates** are new appended lines with the same dedup key
   and updated status/resolution fields — not in-place modifications.
   The original entry remains in the file.

**Canonical implementation:** The reader contract is implemented as a
shared `read_findings(path)` function in a common Python module (alongside
`work_health.py` and `hygiene_scan.py`). `work_health.py` calls it
directly. LLM-driven readers (forcing function, loose ends sweep) follow
the same algorithm from the spec's description above. The shared function
is the reference implementation — if behavior diverges, the function wins.

### Default severity

Findings without a `severity` field default to `warning`. All writers
should adopt the extended format from the start (implementation order
has Component 3 first), but the default provides robustness if a writer
is missed. "Dismiss all NOTEs" in the forcing function correctly
excludes defaulted-to-warning findings — unknown severity gets human
attention, not silent dismissal.

### Writer locking protocol

All writers acquire an advisory lock (`fcntl.flock`) on `findings.jsonl`
before appending. The lock protocol is:

1. Acquire `flock(LOCK_EX)` on `findings.jsonl`
2. Append finding line(s)
3. Release lock

Lock hold time for appenders is O(line) — a single write syscall,
microseconds. This is the structural advantage of JSONL over JSON:
JSON read-modify-write holds the lock for O(file) (read entire file →
parse → modify → serialize → write entire file). JSONL holds the lock
only for the append duration. Both formats require locking for
compaction safety, but contention under JSONL is negligible because
appenders hold the lock for microseconds, not milliseconds.

During normal operation (no compaction running), appender-vs-appender
contention is effectively zero — the flock succeeds instantly.

### Compaction

JSONL files grow monotonically. At work-end, after all findings are
resolved, compact: archive resolved/dismissed findings older than 30
days to `$WORKSPACE/.audit/findings-archive.jsonl`. This keeps the
active file small while preserving audit trail.

**Atomicity:** Compaction is a read-rewrite that breaks the append-only
model. It acquires the same flock that appenders use:

1. Acquire `flock(LOCK_EX)` on `findings.jsonl`
2. Read all entries, separate into "keep" and "archive"
3. Write "keep" entries to `findings.jsonl.tmp`
4. `os.rename('findings.jsonl.tmp', 'findings.jsonl')` (atomic on POSIX)
5. Append "archive" entries to `findings-archive.jsonl`
6. Release lock

Concurrent appenders block briefly during compaction (milliseconds).
Compaction runs at most once per work-end — the lock cost is negligible.

## Component 4 — Forcing Function

Runs at work-end only (D4). Presents all accumulated findings from
`findings.jsonl` and requires resolution for each.

### Implementation model

The forcing function is a work-end SKILL.md workflow step, not a
standalone script. The LLM reads `findings.jsonl`, formats the
presentation, interprets user responses (Fix/File/Dismiss), and
updates `findings.jsonl` after each resolution.

**Checkpoint behavior:** Each resolution is persisted to `findings.jsonl`
immediately (as an appended line with updated status). If the session
aborts mid-forcing-function, already-resolved findings remain resolved.
A restart reads `findings.jsonl`, applies the reader contract, and
presents only findings whose current status is still `open`. The forcing
function resumes from where it left off — no progress is lost.

Scriptable operations (reading findings, formatting display, updating
status) are simple enough for inline LLM execution — no separate
helper script is needed. The interactive loop (presenting choices,
executing fixes, creating issues) is inherently LLM-driven.

### Presentation

```
Open findings — 9 items require resolution before branch close

AUDIT (branch-audit):
  1. [conformance/WARNING] Requirement 3 (notifications) not implemented
  2. [robustness/NOTE] No error handling for network timeout in sync.py

REVIEW (code-review):
  3. [WARNING] Mutable default argument in user_service.py:42

LOOSE-END:
  4. [WARNING] Plan item "add integration tests" deferred
  5. [NOTE] TODO on line 88 of handler.py: "come back to edge case"

HYGIENE:
  6. [WARNING] Blog entry on closed branch issue-200 never promoted

Prior sessions (accumulated):
  7. [WARNING] Deferred review finding from session 2026-08-16
  8. [NOTE] Skipped plan item from session 2026-08-15
  9. [NOTE] TODO referencing issue-123 in utils.py:14
```

### Resolution options per finding

| Option | What happens |
|--------|-------------|
| **Fix** | Fix the issue now. Finding status → `resolved`, resolution includes commit SHA |
| **File** | Create a GitHub issue. Finding status → `filed`, resolution includes issue number |
| **Dismiss** | Not a real problem. Finding status → `dismissed`, resolution includes reason |

**Severity constraints on resolution:**

| Severity | Fix | File | Dismiss |
|----------|-----|------|---------|
| CRITICAL | Yes | Yes  | No      |
| WARNING  | Yes | Yes  | Yes     |
| NOTE     | Yes | Yes  | Yes     |

CRITICAL findings ("will cause wrong behavior, data loss, or security
vulnerability") must be fixed or filed — they cannot be dismissed with
a reason string.

No finding survives branch close with status `open`. The forcing function
is a hard gate — work-end cannot proceed to Execute until all findings
are resolved.

### Triage filtering

"Accept all" and batch operations apply only to **surviving** findings —
those not already rejected by verification during the review process.
If a reviewer raised a finding and the implementor proved it invalid
(e.g., claimed infrastructure doesn't exist but it does), that finding
is not presented for triage. The forcing function presents only findings
whose status is `open` after the review's own adversarial process has
run. This applies equally to branch-audit, code-review, and loose ends
sweep findings.

### Re-review after fixes

When the user chooses "Fix" and creates new commits, the forcing function
detects new commits since the review started and re-runs code-review on
those commits only. New findings from the re-review are added to the
forcing function queue. This loop continues until no new commits are
needed. Branch-audit does not re-run — fixes are scoped responses to
specific findings, not structural changes.

### Batch operations

For efficiency when many findings exist:
- "Fix all" — not available (each fix is different)
- "File all remaining as single issue" — creates one GitHub issue
  listing all remaining findings as a checklist
- "File each remaining" — creates one GitHub issue per finding
- "Dismiss all NOTEs" — dismisses all NOTE-severity findings with a
  blanket reason (user provides)

## Lifecycle Integration

### Work-end flow (D5)

```
Current:  Context → Sweep → Execute (review in 3.1) → Verify → Close
Proposed: Context → Review → Sweep → Execute → Verify → Close
```

**Step 2 — Review (new, before Sweep):**

```
2.1  code-review         per-line checklist on branch diff
2.2  branch-audit        four dimensions on branch diff
2.3  loose ends sweep    session + prior findings scan
2.4  forcing function    present all findings, require resolution
```

All four sub-steps are hard gates. Step 2 does not complete until
the forcing function has resolved all findings.

**Step 2.1 security-audit suppression:** When work-end invokes code-review
at Step 2.1, include this instruction: "Do NOT offer security-audit
escalation — branch-audit Step 2.2 Robustness dimension handles security
escalation." This prevents duplicate escalation offers. During per-commit
development review (outside work-end), code-review continues to offer
security-audit escalation as today.

**Duration estimate:** For a non-trivial branch, expect Step 2 to take
10–30 minutes depending on branch size and accumulated findings.
code-review: 2–5 min, branch-audit: 5–10 min, loose ends sweep: 1–2
min, forcing function: 2–15 min (scales with open findings). This time
is not new — it moves review earlier in the pipeline, catching bugs
before the Sweep invests in knowledge capture.

Both code-review and branch-audit run unconditionally — there is no
choice between them. code-review catches per-line issues (mutable
defaults, unawaited coroutines). branch-audit catches holistic issues
(missing requirements, structural gaps). The current work-end Step 3.1
conditional ("for structural diffs: use `design-review --mode
final-review` instead") is removed — branch-audit replaces that routing.

**Loose ends sweep temporal filtering:** Step 2.3 reads `findings.jsonl`
for prior-session findings only — it filters by timestamp, reading only
findings older than the current work-end cycle start. This prevents
double-counting findings just written by Steps 2.1 and 2.2.

**Trade-off acknowledged:** Review runs without forage/protocol sweep
context. For per-line code-review this is negligible. For branch-audit's
holistic dimensions, a gotcha surfaced by forage could explain unusual
code. Accepted: the cost of reviewing without sweep context is lower
than the cost of sweeping before reviewing.

**Post-rebase re-review:** If rebase (Execute Step 3.2) is non-fast-forward
(i.e., conflicts were resolved), re-run code-review on the conflict
resolution diff only. Branch-audit re-run is not required — code-review's
per-line checklist is sufficient for conflict resolution changes.

If the re-review produces findings, they are handled as a mini-gate at
Step 3.2 — resolved inline before proceeding to Step 3.3 (Squash):

1. Persist findings to `findings.jsonl` (same writer protocol as Step 2.1)
2. Present findings with the same Fix/File/Dismiss options as the forcing
   function, with the same severity constraints (CRITICALs cannot be
   dismissed)
3. All findings must be resolved before proceeding to Step 3.3
4. If "Fix" creates new commits, re-run code-review on those fixup commits
   only. Repeat until no new findings. The branch is already rebased —
   fixup commits sit on top; no re-rebase is needed.

This extends the "no finding survives branch close with status open"
guarantee to post-rebase changes. The scope is small (conflict resolution
diff only) so the mini-gate is fast.

**Step 3 — Execute (after reorganization):**

Execute retains its current content minus code review (moved to Step 2):

```
3.1  Promote artifacts
3.2  Phase A: Rebase
3.3  Phase B: Squash
3.4  Phase C: Land
```

### Handover flow

Add loose ends sweep to the wrap checklist (Step 0), defaulting ON.
The full checklist after this change:

```
[x] 1  Loose ends sweep   capture deferred/skipped/missing items       (NEW)
[x] 2  Knowledge capture  (forage then protocol — sequential)
[x] 3  ADR               record architectural decisions                (NEW)
[x] 4  Doc sync           (update-claude-md then implementation-doc-sync)
[?] 5  journal-entry      document design changes not yet in JOURNAL.md ← ON if mid-epic
[?] 6  epic hygiene       check epic branch state and staleness         ← ON if workspace configured
[?] 7  arc42 stale scan   check ARC42STORIES.MD for stale statuses      ← ON if ARC42STORIES.MD exists
[x] 8  write-content      capture branch narrative as diary entry
[x] 9  notes              anything to note for later?
```

Loose ends sweep runs first (while session context is full). Captures
and persists to `findings.jsonl`. No forcing function at handover —
capture only.

Items 5–7 retain their existing conditional defaults and behavior
from handover/SKILL.md. Epic hygiene and loose ends sweep are different
concerns sharing the same persistence mechanism (§2 Relationship to
epic hygiene).

### Session entry

Enhanced `check_prior_findings()` in `work_health.py` (exists today,
reads `findings.json`) updated to read `findings.jsonl` and surface
open findings with severity and category:

```
CHECK=prior_findings STATUS=warn DETAIL=3 open finding(s):
  [audit/conformance/WARNING] Requirement 3 not implemented (branch-audit)
  [loose-end/WARNING] Plan item "add integration tests" deferred (loose-ends-sweep)
  [hygiene/WARNING] Blog on closed branch never promoted (hygiene-scan)
```

Findings display: `[category/dimension/severity] detail (source)`.
Dimension omitted when null (hygiene, loose-end categories). Findings
missing `severity` display as `[WARNING]` (default severity rule, §3).

## Skill Cleanup

### Remove requesting-code-review (D2)

- Delete `requesting-code-review/` directory
- Update cross-references in: `code-review/SKILL.md`,
  `receiving-code-review/SKILL.md`, `subagent-driven-development/SKILL.md`,
  `CLAUDE.md`, `README.md`
- `receiving-code-review` stays — remove the `requesting-code-review`
  reference from its Skill Chaining; add `design-review` as the
  dispatching counterpart (design-review dispatches external review
  sessions whose feedback receiving-code-review handles)

### Retire verification-before-completion (D3)

- Delete `verification-before-completion/` directory
- Create `docs/protocols/evidence-before-claims.md` preserving the
  principle: "Run the command. Read the output. THEN claim the result."
- Update cross-references in all 25 referencing files to point to the
  protocol
- `git-commit` and `executing-plans` reference the protocol directly
- The forcing function (Component 4) is additive — it handles finding
  resolution at work-end but does NOT replace the per-boundary evidence
  gate

### Update design-review

- Update `review-tiers.md` post-implementation lifecycle point: change
  from *(future)* to active, referencing branch-audit as the executor
- Conformance already exists in `review-tiers.md` as a dimension scoped
  to post-implementation. The change is activating the lifecycle point,
  not adding the dimension.
- No changes to execution model, adversarial machinery, or degree system

### Retire `--mode final-review`

Branch-audit replaces `design-review --mode final-review` for pre-merge
holistic review. Update all references:

- **work-end/SKILL.md** Step 3.1: remove the conditional routing to
  `--mode final-review` for structural diffs — branch-audit runs
  unconditionally at Step 2.2 for all branches
- **code-review/SKILL.md** Skill Chaining: update "use final-review for
  pre-merge production readiness checks" to reference branch-audit
- **design-review/SKILL.md**: remove `--mode final-review` references

## Implementation Order

1. **Findings persistence** (Component 3) — extend `findings.jsonl` format.
   Everything else writes to it.
2. **Loose ends sweep** (Component 2) — can ship independently. Writes to
   `findings.jsonl`, runs at handover.
3. **Branch audit** (Component 1) — new skill with four dimensions.
4. **Forcing function** (Component 4) — reads `findings.jsonl`, presents
   findings, requires resolution.
5. **Lifecycle integration** (Component 5) — reorder work-end, add sweep
   to handover.
6. **Skill cleanup** (Component 6) — remove deprecated skills, create
   protocol, update references.

Steps 1-2 can ship first and provide value (findings persist, surfaced
at session entry) before the full system lands.

## Success Criteria

- No findings survive branch close with status `open`
- Findings from session N are visible at session N+1 entry
- Code review runs before sweep in work-end
- Branch audit covers four dimensions on the full branch diff
- Loose ends sweep runs at every handover and work-end
- `requesting-code-review` and `verification-before-completion` removed
- VBC principle preserved as protocol, referenced by git-commit and
  executing-plans
- design-review dimensions aligned with branch-audit vocabulary

## References

- [decisions.md](decisions.md) — 10 design decisions with rationale
- work-end/SKILL.md — current work-end flow
- code-review/SKILL.md — per-line checklist
- design-review/SKILL.md — adversarial spec review
- design-review/review-tiers.md — lifecycle points and dimensions
- work-end/hygiene_scan.py — hygiene checks (persist_findings() at line 246 writes findings.json today; to be migrated to findings.jsonl)
- project/work_health.py — session entry health checks (check_prior_findings() at line 427 reads findings.json today; to be migrated to findings.jsonl)
- Blog: 2026-08-17-mdp01 "The Feedback Loop That Wasn't"
- Blog: 2026-08-17-mdp03 "Four Fixes, One Already Done"
- handover/SKILL.md — epic hygiene checks
- verification-before-completion/SKILL.md — evidence-before-claims principle
- requesting-code-review/SKILL.md — deprecated skill to remove
