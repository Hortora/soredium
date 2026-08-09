# Decision Review + Ordered Dimensions + Unified Design Pipeline

**Issue:** Hortora/soredium#198
**Date:** 2026-08-09
**Status:** Draft

## Problem

The brainstorming-to-spec pipeline has three gaps:

1. **Decisions evaporate.** Brainstorming produces a spec, but the individual
   decisions that shaped it — what alternatives were considered, why one was
   chosen, what trade-offs were accepted — dissolve into conversation history.
   There is nothing structured to validate, and no record for future sessions
   to reference.

2. **Dimensional reviews miss cascading insights.** Post-spec review runs
   coherence, structure, and robustness in parallel. Each dimension is blind
   to the others' findings. A structural issue ("this module boundary is
   unclear") could inform the coherence reviewer ("check requirements on both
   sides of that boundary") and the robustness reviewer ("probe failure modes
   at that boundary") — but in parallel mode, it doesn't.

3. **Approach exploration is shallow by default.** When the user is uncertain
   about which approach to take, the current flow offers 2-3 options with a
   recommendation. There is no systematic mechanism for steelman/devil's
   advocate analysis, internet research for prior art, first-principles
   reasoning, or multi-agent debate. The user must request these ad hoc.

4. **Platform coherence depends on manual prompts.** Ensuring new work doesn't
   duplicate existing capabilities or violate architectural boundaries requires
   the user to paste project-specific documentation paths into every session.
   This should be discoverable and systematic.

## Design

### Pipeline State Model

The design pipeline is a state machine with observable transitions. Each state
is written to `$WORKSPACE/specs/<branch>/pipeline.state` so external tools
(including drafthouse) can render pipeline progress.

```
CONTEXT_GATHERING
  → CLARIFYING_QUESTIONS
    → APPROACH_EXPLORATION
      → DECISION_CAPTURE        ← loops back to APPROACH_EXPLORATION for sub-decisions
        → DECISION_REVIEW
          → DECISION_REVISION   ← optional, loops back to APPROACH_EXPLORATION if decisions changed
            → SPEC_WRITING
              → SPEC_SELF_REVIEW
                → POST_SPEC_REVIEW
                  → PLANNING
```

#### State file format

```
format_version: 1
state: APPROACH_EXPLORATION
entered: 2026-08-09T14:23:00
decision_count: 3
dimensions_completed: 0
dimensions_total: 0
ordered: false
dimensions_done:
current_dimension:
workspace_structure:
workspace_coherence:
workspace_robustness:
workspace_crosscutting:
workspace_decision:
```

- `format_version` — schema version for forward compatibility. Readers
  that encounter an unknown version halt with an explicit error rather
  than silently misparsing.
- `dimensions_done` — comma-separated list of completed dimension names
  (e.g. `structure,coherence`). Empty when no dimensions have run.
- `current_dimension` — the dimension currently in progress (ordered
  mode only). Empty when no dimension is active.
- `workspace_<dimension>` — absolute path to the review workspace for
  each dimension (e.g. `workspace_structure: /Users/.../title-structure-20260809-123456`).
  Written by review.py at workspace creation (before running rounds),
  so crash recovery can locate both in-progress and completed workspaces.
  `workspace_decision` stores the decision-review workspace path.

Overwritten at every state transition. Git history preserves the full
trail for auditing.

#### State descriptions

| State | What is happening | Artifacts produced |
|-------|-------------------|--------------------|
| `CONTEXT_GATHERING` | Loading SOURCES.md, platform docs, garden, protocols | None |
| `CLARIFYING_QUESTIONS` | Understanding constraints and requirements (not decisions) | None |
| `APPROACH_EXPLORATION` | Presenting options, exploring at depth (quick/deep/debate) | `explorations/D<N>-*.md` (deep/debate only) |
| `DECISION_CAPTURE` | Writing a decided choice to decisions.md | `decisions.md` entry appended |
| `DECISION_REVIEW` | Independent adversarial validation of all decisions | Review workspace, tracker.md |
| `DECISION_REVISION` | Updating decisions that changed during review | `decisions.md` entries marked revised |
| `SPEC_WRITING` | Writing the spec from validated decisions | `*-design.md` |
| `SPEC_SELF_REVIEW` | Checking spec against SOURCES.md and decisions.md for coherence | Inline fixes to spec |
| `POST_SPEC_REVIEW` | Dimensional review (ordered or parallel) | Review workspaces, trackers |
| `PLANNING` | Invoking writing-plans | Implementation plan |

### Component 1: Decision Capture

#### What counts as a decision

A decision is any moment during brainstorming where 2+ options are presented
and the user selects one. This includes:

- The top-level approach selection (the main "propose 2-3 approaches" step)
- Sub-decisions during the design phase ("should component X use pattern A or B?")

Things that are NOT decisions:
- Constraints ("Who is the primary user?" → "Internal developers")
- Requirements ("Do you need real-time updates?" → "Yes")
- Clarifications that narrow scope without choosing between alternatives

#### Decision file format

Written incrementally to `$WORKSPACE/specs/<branch>/decisions.md` as each
decision is made. If the session dies mid-brainstorm, captured decisions survive.

```markdown
# Decisions — <branch-name>

## D1: <short title>

**Choice:** <what was selected>
**Alternatives:**
- <option B> — <one-line trade-off>
- <option C> — <one-line trade-off>
**Rationale:** <why this choice>
**Trade-offs:** <what we're giving up>
**Exploration:** <quick | deep-analysis | multi-agent-debate>
**Status:** <captured | validated | revised>
```

Each decision is numbered sequentially (D1, D2, ...). The `Exploration` field
records the depth of analysis performed during brainstorming. The `Status`
field tracks the decision through the pipeline:

| Status | Meaning |
|--------|---------|
| `captured` | Written during brainstorming, not yet validated |
| `validated` | Survived decision-review unchanged |
| `revised` | Changed during decision-review (original preserved in git history) |

#### Decision dependencies

When a later decision depends on an earlier one, note it:

```markdown
## D5: Cache invalidation strategy

**Depends on:** D2 (event sourcing)
...
```

Decision-review uses these dependencies to identify cascade effects — if D2
is revised, D5 must be re-evaluated.

#### Revision cycle bounds

The DECISION_REVISION → APPROACH_EXPLORATION → DECISION_CAPTURE →
DECISION_REVIEW cycle is bounded:

- **Max 2 revision cycles.** If decisions have been revised twice through
  the full cycle, brainstorming escalates to the user rather than
  entering a third cycle. Repeated revision suggests a fundamental
  tension between decisions that needs human judgment.
- **Direct dependents only, batched per cycle.** At the end of each
  revision cycle, collect all revised decisions. For each, identify
  direct dependents (`Depends on:` pointing to a revised decision).
  Re-evaluate each dependent exactly once per cycle, regardless of
  how many of its dependencies were revised. This ensures D5 (which
  depends on both D2 and D3) sees both revisions if both occurred
  in the same cycle. Transitive dependents (D8 depending on D5
  depending on D2) are caught in the next revision cycle.
- **Null cycles don't count.** A revision cycle entered via the
  git-diff fallback (or any other trigger) that results in no
  substantive changes — no dependents need re-evaluation, or all
  re-evaluated dependents confirm unchanged — does not count toward
  the max-2 limit. This prevents cosmetic edits (typo fixes in
  rationale, formatting changes) from consuming revision budget.
  Only cycles where at least one decision's choice, alternatives,
  or dependencies actually changed count.
- **Escalation distinguishes chain propagation from circular tension.**
  When max cycles is reached with unprocessed dependents remaining,
  the escalation message indicates whether the continued revision is
  from chain propagation (D1 → D3 → D5 → D8, a linear chain longer
  than 2 cycles) or circular tension (D2 → D5 → D2, a cycle in the
  dependency graph). Chain propagation can be resolved by the user
  approving another cycle. Circular tension requires human judgment
  to break the loop.

### Component 2: Approach Exploration (Enhanced)

When brainstorming presents 2-3 approaches, the user can explore at three
intensity levels before deciding.

#### Level 1: Quick pick

The user selects immediately. Decision captured with `Exploration: quick`.

#### Level 2: Deep analysis

Claude performs structured analysis of each approach:

1. **Steelman** each option — the strongest possible case
2. **Devil's advocate** each option — why it might fail, what it can't handle
3. **Internet search** — prior art, current best practices, industry patterns
4. **First-principles analysis** — improve on the proposals, potentially
   surface new options not originally presented

Presents a strengthened recommendation with full reasoning. Decision captured
with `Exploration: deep-analysis`.

#### Level 3: Multi-agent debate

For high-stakes decisions where independent perspective matters:

1. Spawn N parallel agents — one per approach. Each agent's brief:
   "Make the strongest case for approach X. Explain why it is better than
   approaches Y and Z. Address weaknesses honestly but argue for your
   position. Search the internet for supporting evidence and prior art."

2. Collect all position papers.

3. Spawn a mediator agent: "Read these N position papers. Determine which
   approach wins on merit. Identify genuine strengths from the losing
   approaches that should be incorporated. Propose a hybrid if neither
   advocate's pure position is optimal."

4. Present the mediator's synthesis to the user.

5. User decides — or requests another round of debate on specific points.

**Subsequent debate rounds:** If the user requests another round:

- The user specifies which points to debate further (free text input)
- Previous position papers are preserved and referenced by the new agents
- Only the mediator is re-spawned, with updated instructions incorporating
  the first round's synthesis and the user's specific points for deeper
  exploration. Advocate agents are NOT re-spawned — their positions are
  settled; the value is in the mediator re-evaluating with focused scope.
- Max 3 debate rounds total — diminishing returns beyond this. If the user
  is still undecided after 3 rounds, the mediator's final synthesis stands
  and the user makes a judgment call.

Decision captured with `Exploration: multi-agent-debate`.

**Failure handling:**

- **Advocate failure:** If an advocate agent fails, the debate proceeds
  with remaining advocates provided at least 2 positions are represented.
  If only 1 advocate succeeds, fall back to deep analysis (Level 2)
  rather than running the mediator with a single position.
- **Mediator failure:** Present raw position papers to the user with a
  note that mediator synthesis failed. The user can decide directly
  from the position papers or request a mediator retry.

#### Triggering exploration depth

Brainstorming does not wait for the user to ask. When presenting approaches:

- If the decision has low architectural impact (config, naming, wiring):
  present options and expect a quick pick
- If the decision has moderate impact (new module, API surface): present
  options with a recommendation and offer deep analysis
- If the decision has high impact (novel architecture, cross-repo boundary,
  data model): present options and proactively recommend deep analysis or
  debate

The user can always escalate ("let's debate this") or de-escalate ("just
go with A") regardless of the recommendation.

### Component 3: Decision Review

A new review type in the existing design-review framework. Runs after all
decisions are captured but before the spec is written.

#### Review mode definition

Decision review is a **lifecycle mode** (like `pre-review`, `code-review`,
`final-review`) — not a dimensional type (like `coherence`, `structure`).
It has its own dispatch branch in `build_reviewer_prompt()` and
`build_implementor_prompt()`, with dedicated `_DECISION_REVIEW_*` prompt
builders. It does NOT route through `_build_typed_reviewer_prompt()`.

| Property | Value |
|----------|-------|
| Mode | `decision` (added to `REVIEW_MODES`) |
| Type | `decision` (added to `REVIEW_TYPES` for `--type` CLI) |
| `MODE_TO_TYPE` | `"decision": ("decision", "standard")` |
| `TYPE_TO_MODE` | `"decision": "decision"` |
| `MODE_DEFAULTS` | No entry — `DEGREE_PRESETS` always applies via `TYPE_DEFAULTS` resolution |
| `TYPE_DEFAULTS` | `"decision": "standard"` |
| Lifecycle point | Pre-spec (after brainstorming, before spec writing) |
| Input artifact | `decisions.md` |
| Dispatch | `build_reviewer_prompt()` → `_build_decision_review_reviewer_prompt()` |
| CLAUDE.md | `_MODE_GENERATORS["decision"]` in setup.py |

#### Degree defaults

Decision review uses the same `DEGREE_PRESETS` as all review types:

| Degree | Rounds | When to use |
|--------|--------|-------------|
| Light | 1 | 3-4 straightforward decisions, most with deep exploration |
| Standard | 2-3 | 5-8 decisions, mixed exploration depths |
| Adversarial | 4-6 | High-stakes decisions, novel architecture, quick-pick decisions |
| Deep | 6-10 | Many decisions, novel architecture, most with quick-pick exploration |

#### Reviewer brief (`_DECISION_REVIEW_APPROACH_REVIEWER`)

The reviewer reads `decisions.md` and the project's `SOURCES.md`. For each
decision:

1. **Challenge the rationale** — is the reasoning sound? Are there logical
   gaps or unstated assumptions?
2. **Propose unconsidered alternatives** — search the codebase, architecture
   docs, and internet for approaches the brainstorm didn't surface
3. **Check platform coherence** — does this decision duplicate an existing
   capability? Violate boundary rules? Create dependency issues? Check
   against SOURCES.md documentation
4. **Surface implicit decisions** — read the overall design direction and
   identify choices that were made without explicit debate but have
   architectural consequences
5. **Assess trade-off weighting** — are the acknowledged trade-offs correctly
   prioritised for this project's maturity stage?
6. **Check decision dependencies** — if D5 depends on D2, does D2's rationale
   actually support D5's assumption?

Calibration by exploration depth: decisions marked `Exploration: quick` receive
maximum scrutiny. Decisions marked `Exploration: multi-agent-debate` receive
light verification (the debate already stress-tested them). The reviewer
should spend their budget where the brainstorming process was thinnest.

#### Reviewer starting points (`_DECISION_REVIEW_STARTING_POINTS`)

```
Starting points (not restrictions — go beyond these):
- For each decision: what is the strongest argument AGAINST this choice?
- Are there simpler alternatives that achieve the same goal?
- Does this decision align with platform trajectory (check SOURCES.md)?
- Does this duplicate existing capability (check capability docs)?
- Does this violate boundary rules (check boundary docs)?
- What implicit decisions are embedded in the overall design direction
  that were never explicitly debated?
- For decisions marked Exploration: quick — these received the least
  scrutiny during brainstorming. Apply maximum adversarial pressure.
- Do decision dependencies hold? If D5 assumes D2, does D2 actually
  support that assumption?
```

#### Implementor brief (`_DECISION_REVIEW_APPROACH_IMPLEMENTOR`)

The implementor (decision author) defends each decision or pivots:

- Where the reviewer's challenge is unfounded: defend with evidence —
  cite SOURCES.md, platform docs, the steelman analysis, or debate
  synthesis that already addressed the concern
- Where the reviewer surfaces a genuinely better alternative: update
  the decision in `decisions.md`, mark status as `revised`, and note
  what changed
- Where the reviewer surfaces an implicit decision: make it explicit —
  add a new entry to `decisions.md` with the alternatives now that the
  choice is visible

#### Implementor constraints

```
Stand ground on well-explored decisions. A decision that survived
steelman/devil's advocate or multi-agent debate has already been
pressure-tested — the reviewer must present NEW evidence or a NEW
alternative to justify revision, not merely restate concerns that
were already addressed during exploration.

For quick-pick decisions, be more open to revision — these received
minimal scrutiny and the reviewer's fresh perspective is valuable.
```

#### Integration with brainstorming

After all decisions are captured and the user approves the overall design
direction, brainstorming transitions to `DECISION_REVIEW` state and presents:

```python
AskUserQuestion(questions=[{
    "question": "N decisions captured (M quick, K deep, J debate). Review depth?",
    "header": "Decision review",
    "options": [
        {"label": "<Recommended> (Recommended)", "description": "<reasoning based on exploration depths>"},
        {"label": "Skip", "description": "Proceed to spec writing"},
        {"label": "Light", "description": "~2 min — single pass"},
        {"label": "Standard", "description": "~5 min — 2-3 rounds"},
        {"label": "Adversarial", "description": "~12 min — 4-6 rounds"},
        {"label": "Deep", "description": "~25 min — 6-10 rounds + ultrathink"},
    ],
    "multiSelect": false,
}])
```

The recommendation engine counts exploration depths: many quick picks →
recommend Standard or Adversarial. All deep/debate → recommend Light or Skip.

After decision-review completes:
- If any decisions were revised: brainstorming re-enters `APPROACH_EXPLORATION`
  for dependent decisions (those with `Depends on:` pointing to revised entries)
- If no revisions: brainstorming transitions to `SPEC_WRITING`

#### Workspace and tracker

Decision-review uses the standard review workspace under `~/reviews/`:

```
~/reviews/<project>/decision-<timestamp>/
  context.md
  tracker.md
  .spec-path          ← points to decisions.md (not a spec, but same mechanism)
  .source-dirs
  .mode               ← "decision"
  .depth
  responses/
  agents/
    reviewer/CLAUDE.md
    implementor/CLAUDE.md
  decisions/
  handovers/
```

The tracker uses standard `R{n}-{nn}` issue IDs. Each decision review
runs in its own workspace with its own tracker, so the decision context
is implicit in the workspace. The reviewer references specific decisions
by ID (D1, D3, etc.) in issue body text, not in the issue ID itself.
This avoids parser and tracker changes — `extract_new_issues()`,
`extract_issue_responses()`, and `_ISSUE_ID_RE` all work unmodified.

#### Evidence verification

Decision review extends the evidence verification pipeline to handle
decision-section references:

- `_extract_section_number()` is extended to match `D<N>` format in
  addition to `§N.N` (e.g., `EVIDENCE: D3 | commit:abc123`)
- `_find_section_range()` is extended to find `## D<N>: <title>`
  headings in decisions.md
- `annotate_spec_headings()` is guarded to skip when mode is `decision`
  — decisions.md uses its own heading convention (`## D1:`, `## D2:`)
  that must not be overwritten with `S<N>:` prefixes

### Component 4: Ordered Dimensional Reviews

An opt-in mode for post-spec review where dimensions run sequentially with
cascading findings.

#### Ordering

```
structure → coherence → robustness → cross-cutting
```

1. **Structure first** — establishes boundaries, decomposition,
   responsibilities. Everything else depends on knowing where the
   boundaries are.
2. **Coherence second** — checks completeness and consistency within those
   boundaries. Structure findings inform what "complete" means.
3. **Robustness third** — probes failure modes at boundaries and edges.
   Both structure and coherence findings inform where to probe.
4. **Cross-cutting last** — as today, reads all dimension trackers and
   finds problems between them.

#### Mapping from issue #198

Issue #198 proposed 6 dimensions: `Structure → Correctness → Robustness
→ Completeness → Readability → Cross-cutting`. This spec uses the 4
existing dimensional review types from the framework:

| Issue #198 dimension | Implementation | Rationale |
|---------------------|----------------|-----------|
| Structure | `structure` | Direct mapping |
| Correctness | Dropped | Overlaps with `robustness` — both probe for errors and failure modes. Robustness subsumes correctness concerns |
| Robustness | `robustness` | Direct mapping |
| Completeness | `coherence` | `coherence` already covers completeness, consistency, gaps, and ambiguity |
| Readability | Dropped | Low-value as standalone dimension — readability concerns are implicitly checked by all reviewers when they read the spec |
| Cross-cutting | `crosscutting` | Direct mapping |

#### Implementation: SKILL.md orchestration

review.py stays single-dimension. The change is entirely in SKILL.md Step 4.

**Parallel mode (default):** Launch 3 `review.py` instances with
`run_in_background: true`. Unchanged from current behavior.

**Ordered mode (opt-in):**

1. Launch structure review:
   ```bash
   python3 ~/.claude/skills/design-review/review.py \
     --spec {spec_path} --title {title}-structure \
     --type structure --degree {degree} \
     --stage {stage} --source-dirs {dirs}
   ```
   Run with `run_in_background: true`. Wait for completion notification.

2. When structure completes, SKILL.md reads `workspace_structure` from
   pipeline.state (written by review.py at setup) and launches coherence
   with the explicit structure tracker path:
   ```bash
   python3 ~/.claude/skills/design-review/review.py \
     --spec {spec_path} --title {title}-coherence \
     --type coherence --degree {degree} \
     --stage {stage} --source-dirs {dirs} \
     --arch-files {structure_ws}/tracker.md
   ```

3. When coherence completes, launch robustness with both explicit paths:
   ```bash
   python3 ~/.claude/skills/design-review/review.py \
     --spec {spec_path} --title {title}-robustness \
     --type robustness --degree {degree} \
     --stage {stage} --source-dirs {dirs} \
     --arch-files {structure_ws}/tracker.md \
                  {coherence_ws}/tracker.md
   ```

4. When robustness completes, launch cross-cutting with all three
   explicit tracker paths.

review.py writes each `workspace_<type>` field to pipeline.state at
workspace creation — before running any rounds. This ensures crash
recovery can locate in-progress workspaces and subsequent dimensions
reference the correct workspace even when multiple workspaces exist
for the same dimension (e.g. from a failed prior attempt). No glob
patterns are used for arch-files in ordered mode.

#### Cascading context in prompts

When `--arch-files` contains trackers from prior dimensions,
`_generate_context_md()` in setup.py parses those trackers at workspace
creation time and generates a cascading context section in context.md:

```
Prior dimension findings (read the full trackers for detail):

Structure review found:
- STR-R1-01: Module boundary between scanner and lifecycle unclear [VERIFIED]
- STR-R1-03: Circular dependency between X and Y [ADDRESSED]

Consider these findings when evaluating {current dimension}. Where a
structural issue creates a {current dimension} gap, cite the structural
finding by ID (e.g. STR-R1-01).
```

**Prefixing convention:** issue IDs in the cascading context prompt are
prefixed with a dimension abbreviation for cross-referencing:

| Dimension | Prefix |
|-----------|--------|
| Structure | `STR-` |
| Coherence | `COH-` |
| Robustness | `ROB-` |

This is **display-only** — applied when `_generate_context_md()`
injects findings from prior dimension trackers into context.md.
Each dimension's own tracker continues to use standard `R{n}-{nn}` IDs.
The implementor responds using standard IDs from their own dimension's
tracker, not the prefixed form. No parser or tracker changes required.

The dimension identity is read from the `.mode` file in each
arch-file's workspace directory (written by `setup.py` during workspace
creation), not inferred from filename patterns.

#### Orchestration contract

**SKILL.md drives sequencing.** In ordered mode, SKILL.md launches each
dimension with `run_in_background: true`, receives the completion
notification, then launches the next dimension with cumulative
`--arch-files`. This is the same sequential launch pattern shown in
the implementation section above.

**The watchdog monitors health only.** It does NOT drive sequencing or
launch subsequent dimensions. In parallel mode, the watchdog cron
monitors all active dimensions for stalls, failures, and progress.
Checkpoint 1 fires once across all dimensions (when all have completed
round 1). Checkpoint 2 (pre-cross-cutting gate) fires only after all
dimensions complete.

In ordered mode, the watchdog monitors a single active dimension at a
time. Checkpoint 1 (round 1 early-HIL gate) does not apply — each
dimension runs to completion under its degree preset, and SKILL.md
presents the full results between dimensions, giving the user the
opportunity to stop the ordered pipeline before the next dimension
launches. The watchdog's role in ordered mode is limited to health
monitoring: detecting stalls (no progress.log update for 10+ minutes),
failures, and timeouts. Checkpoint 2 fires after all dimensions
complete, same as parallel mode.

The watchdog prompt is parameterized by mode (parallel vs ordered) and
active dimension, adjusting which progress logs to monitor and which
checkpoint logic to apply.

#### Recommendation engine

| Signal | Recommendation |
|--------|---------------|
| Clear boundaries, small scope, config-only | Parallel (or Skip) |
| New module boundaries, cross-module concerns | Ordered |
| Novel architecture, unclear decomposition | Ordered |
| High complexity + high stakes | Ordered + Adversarial degree |

#### Degree prompt change

When the recommendation engine detects cross-module complexity, the
existing degree prompt (in brainstorming SKILL.md) is replaced with an
augmented version that includes ordering variants:

```python
AskUserQuestion(questions=[{
    "question": "Post-spec review depth?",
    "header": "Review",
    "options": [
        {"label": "Standard, ordered (Recommended)", "description": "Sequential dimensions with cascading findings — ~10 min"},
        {"label": "Standard, parallel", "description": "All dimensions simultaneous — ~5 min"},
        {"label": "Review it yourself", "description": "Self-review — read and suggest changes before proceeding"},
        {"label": "Skip", "description": "No review"},
        {"label": "Light, parallel", "description": "~2 min — single pass per dimension"},
        {"label": "Adversarial, ordered", "description": "Sequential with adversarial depth — ~25 min"},
        {"label": "Adversarial, parallel", "description": "~12 min — 4-6 rounds per dimension"},
        {"label": "Deep, ordered", "description": "Sequential with ultrathink — ~50 min"},
        {"label": "Deep, parallel", "description": "~25 min — 8-10 rounds + ultrathink"},
    ],
    "multiSelect": false,
}])
```

When ordering is **not** recommended (clear boundaries, small scope),
the existing degree prompt from brainstorming SKILL.md is used unchanged
— it already includes all degrees from Light through Deep plus "Review
it yourself" and Skip. No ordering variants are shown.

#### Wall-clock cost

Ordered takes ~2-3x longer than parallel (sequential vs simultaneous). The
recommendation engine surfaces this trade-off explicitly. For most specs,
parallel remains the right choice. Ordered is for specs where dimensional
interactions are the primary risk.

### Component 5: SOURCES.md

A per-project documentation map that makes platform coherence discoverable.

#### Creation

SOURCES.md is manually authored per project. It is created once when a
project establishes its documentation structure, then maintained as
documentation paths change. No tool auto-generates it — the author knows
which documentation is architecturally authoritative.

#### Location and inclusion

- File: `SOURCES.md` in the project root
- CLAUDE.md includes it via `@SOURCES.md` (the standard include directive).
  This ensures the content stays current without manual copy-paste.
- Brainstorming and spec writing **reference** SOURCES.md by path at key
  moments as a coherence reminder

#### Absence behavior

When SOURCES.md does not exist:

- CLAUDE.md's `@SOURCES.md` include is silently omitted (no error — the
  `@` directive tolerates missing files). Verify this behavior during
  implementation step 1; if it does not hold, guard the include with a
  conditional check
- `ctx.py` sets `HAS_SOURCES = false`, `SOURCES_PATH = ""`
- Brainstorming skips the SOURCES.md coherence reminder
- Design-review falls back to `_ARCH_DOCS` constraint for documentation
  paths (the current behavior — no regression)

#### Relationship to `_ARCH_DOCS`

`_ARCH_DOCS` in setup.py hardcodes platform-level documentation paths.
SOURCES.md is the per-project replacement. During transition:

- Projects with SOURCES.md: reviewers use SOURCES.md (via CLAUDE.md
  inlining) for project-specific docs, and `_ARCH_DOCS` for
  platform-level docs. No duplication — `_ARCH_DOCS` points to
  platform docs (PLATFORM.md, protocols), SOURCES.md points to
  project docs (architecture, specs, ADRs).
- Projects without SOURCES.md: `_ARCH_DOCS` provides the current
  fallback behavior unchanged.

Eventually `_ARCH_DOCS` can be removed when all projects have SOURCES.md,
but that migration is out of scope for this spec.

#### Format

```markdown
# Documentation Sources

| Type | Path | Notes |
|------|------|-------|
| Architecture | docs/ARCHITECTURE.md | Module hierarchy, tier structure |
| Platform rules | docs/platform/ | boundary-rules, capability-ownership, overlap-risks |
| Protocols | docs/protocols/INDEX.md | Standing conventions |
| Specs | docs/specs/ | Design specifications |
| ADRs | docs/adr/ | Architecture decision records |
| API docs | docs/api/ | Public API reference |
| Consumer docs | docs/ | User-facing documentation |
| Contributor docs | docs/dev/ | Internal development guide |
| Repo guides | docs/repos/ | Per-repo design docs |
| Blog | <path-to-blog-entries> | Published diary entries |
| Garden | ~/.hortora/garden/ | Knowledge garden |
```

Not every project has every type — rows are omitted when not applicable.
The `Notes` column adds context that helps skills decide which docs to
read for a given task.

#### Integration points

| Skill | How SOURCES.md is used |
|-------|------------------------|
| **brainstorming** | In context via CLAUDE.md inlining (no explicit load needed). Referenced by name before proposing approaches ("does this already exist?") and during spec self-review as a coherence reminder. |
| **decision-review** | In context via CLAUDE.md inlining. Reviewer references it to check platform coherence per decision. |
| **design-review** | In context via CLAUDE.md inlining. Reviewer references it alongside existing `_ARCH_DOCS` constraint. |
| **work-start** | `ctx.py` detects SOURCES.md presence (`HAS_SOURCES`, `SOURCES_PATH`). Surfaces it in the work-start summary. Useful for tools that operate outside the conversation context. |

#### ctx.py integration

`ctx.py` gains a `HAS_SOURCES` flag and a `SOURCES_PATH` value. Skills that
need documentation paths read SOURCES.md directly rather than hardcoding
project-specific paths.

### Pipeline State Transitions

Every state transition writes to `pipeline.state`. External tools (drafthouse)
poll or watch this file to render pipeline progress.

#### Transition rules

| From | To | Trigger |
|------|----|---------|
| `CONTEXT_GATHERING` | `CLARIFYING_QUESTIONS` | Context loaded |
| `CLARIFYING_QUESTIONS` | `APPROACH_EXPLORATION` | All constraints understood |
| `APPROACH_EXPLORATION` | `DECISION_CAPTURE` | User selects an option |
| `DECISION_CAPTURE` | `APPROACH_EXPLORATION` | More sub-decisions needed |
| `DECISION_CAPTURE` | `DECISION_REVIEW` | All decisions captured, user approves overall design direction (this is the holistic design approval gate — not just "are all decisions recorded?" but "is this the right direction?") |
| `DECISION_REVIEW` | `DECISION_REVISION` | Review completes with revisions |
| `DECISION_REVIEW` | `SPEC_WRITING` | Review completes, no revisions (or Skip) |
| `DECISION_REVISION` | `APPROACH_EXPLORATION` | Revised decision has dependents |
| `DECISION_REVISION` | `SPEC_WRITING` | No cascading revisions needed |
| `SPEC_WRITING` | `SPEC_SELF_REVIEW` | Spec written and committed |
| `SPEC_SELF_REVIEW` | `POST_SPEC_REVIEW` | Self-review complete, review depth selected |
| `SPEC_SELF_REVIEW` | `PLANNING` | Review skipped |
| `POST_SPEC_REVIEW` | `PLANNING` | Review complete |

#### SPEC_SELF_REVIEW: trade-off verification

In addition to checking the spec against SOURCES.md, the self-review
step verifies that decision trade-offs are reflected in the spec:

- For each decision in decisions.md with a non-empty `**Trade-offs:**`
  field, verify the spec documents the accepted limitation. The check
  is semantic (does the spec acknowledge this trade-off somewhere?),
  not syntactic (it doesn't need to use the same words).
- For each decision with `Exploration: multi-agent-debate`, verify
  the spec references the strongest counter-argument from the losing
  positions. The reader should understand why the chosen approach won.

This ensures post-spec reviewers can evaluate the spec as a standalone
artifact without needing decisions.md — the trade-offs are embedded in
the spec itself. Post-spec reviewers intentionally do NOT receive
decisions.md; the spec must stand on its own merit.

#### State file writes

Each actor writes the states it owns. The file is overwritten at each
transition with the current state block.

| Actor | States it writes |
|-------|-----------------|
| brainstorming | `CONTEXT_GATHERING` through `DECISION_CAPTURE`. Writes `DECISION_REVIEW` on launch. Writes `SPEC_WRITING` through `SPEC_SELF_REVIEW`. Writes `POST_SPEC_REVIEW` on launch. |
| review.py (all modes) | `workspace_<type>` at workspace creation (before running rounds). Conditional on pipeline.state existing — standalone reviews skip this write. |
| review.py (decision) | `DECISION_REVISION` or `SPEC_WRITING` on decision-review completion |
| brainstorming (skip) | `SPEC_WRITING` when user selects Skip for decision review |
| brainstorming (post-spec) | `PLANNING` after all dimensional reviews complete (including optional cross-cutting) |

#### Decision-review state criteria

review.py determines which state to write based on the tracker:

- **`DECISION_REVISION`** — if any tracker issue reached `VERIFIED` status
  (meaning the implementor accepted a critique via FIXED and the reviewer
  confirmed the change). VERIFIED implies decisions.md was modified.
- **`SPEC_WRITING`** — if all issues resolved through `ACCEPTED` or
  `DEFERRED`, with no `VERIFIED` issues. No decisions were changed.
  `DEFERRED` items (escalated via DECISION_NEEDED) are handled during
  the review — the user has already seen and responded to each
  escalation. Proceeding to SPEC_WRITING is appropriate because the
  user made a conscious choice on each deferred concern.

This is a simple check: `any(issue.status == VERIFIED for issue in tracker)`.
No body-text parsing or semantic interpretation required.

**Fallback for incomplete reviews:** If the review ends before reaching
VERIFIED status (timeout, crash after implementor ran), review.py also
checks whether decisions.md was modified relative to its state at review
entry (via `git diff` against the commit present when `DECISION_REVIEW`
was entered). If decisions.md was modified, write `DECISION_REVISION`
even if no tracker issues reached VERIFIED — the modifications are
real and dependents need re-evaluation.

review.py already emits `REVIEW DONE` to progress.log; adding a
`pipeline.state` write at completion is a one-line addition. When
brainstorming's session resumes (via watchdog notification or user return),
it reads `pipeline.state` to determine the current state rather than
relying on conversation continuity.

#### Path resolution for review.py writes

review.py derives the pipeline state path from its `.spec-path` file:
`Path(spec_path).parent / "pipeline.state"`. This works because
`.spec-path` points into the brainstorming workspace
(`$WORKSPACE/specs/<branch>/decisions.md` or `*-design.md`), and
`pipeline.state` lives in the same directory.

#### Scoping: pipeline-invoked vs standalone

Pipeline state writes are conditional. review.py writes to
`pipeline.state` only when the file already exists at the derived path.
Standalone reviews (`/design-review --type robustness` invoked directly)
have no brainstorming workspace and no `pipeline.state` file — the write
is silently skipped. This requires no flag or mode check — file existence
is the gate.

#### Crash recovery

If review.py crashes before writing to pipeline.state, the state file
is stuck at the launching actor's last write. Recovery on resume:

- Brainstorming reads pipeline.state. For `DECISION_REVIEW`, it reads
  `workspace_decision` to locate the review workspace. For
  `POST_SPEC_REVIEW` in ordered mode, it reads `workspace_<dimension>`
  fields for all completed dimensions and `current_dimension` for the
  active one.
- If the workspace path is set and its `progress.log` contains
  `REVIEW DONE`, the review completed but state wasn't written —
  brainstorming reads the workspace tracker to determine the correct
  transition
- If the workspace path is set without `REVIEW DONE`, the review is in
  progress or crashed — brainstorming resumes it with `--workspace`
- If the workspace path is empty, the review was never launched —
  brainstorming launches it fresh

For ordered mode, the `workspace_<dimension>` fields provide the
explicit paths needed for `--arch-files` on subsequent dimensions,
eliminating the need for glob-based workspace discovery. review.py
writes its `workspace_<type>` field to pipeline.state during
workspace creation — before running any rounds. When brainstorming
resumes and needs to launch the next dimension, it reads these
fields directly from pipeline.state.

In parallel mode, three review.py instances may write workspace
paths concurrently. A last-writer-wins race is possible but benign:
workspace paths are best-effort for crash recovery of in-progress
reviews, and brainstorming corrects all values from completion
notifications before constructing --arch-files for cross-cutting.

This requires no locking or writer identification. The state machine
has deterministic ownership: each state value identifies its writer.
Recovery uses pipeline.state workspace paths and progress.log as
ground truth, not pattern-based discovery.

Key counters update as the pipeline progresses:

- `decision_count` — increments with each captured decision
- `dimensions_completed` — increments as each dimension review finishes
- `dimensions_total` — set when post-spec review starts (3 for ordered, 3 for parallel)
- `ordered` — `true` if ordered mode selected

### Changes Per File

| File | Changes |
|------|---------|
| `brainstorming/SKILL.md` | New approach exploration phase (3 depth tiers). Decision capture loop with decisions.md writes. Pipeline state management. Decision-review invocation before spec writing. SOURCES.md loading in context gathering. Multi-agent debate orchestration. |
| `design-review/SKILL.md` | Ordered dimension mode in Step 4. Watchdog adaptation for ordered mode. Updated degree prompt with ordering option. |
| `design-review/prompts.py` | New `_DECISION_REVIEW_*` prompt builders. |
| `design-review/setup.py` | New `_DECISION_REVIEW_*` constraint elements. `_MODE_GENERATORS["decision"]` for reviewer/implementor CLAUDE.mds. Cascading context injection in `_generate_context_md()` — when arch-files include prior dimension trackers, parses issue summaries and generates prefixed cascading context in context.md. Mode guard on `annotate_spec_headings()` to skip for decision mode. |
| `design-review/review.py` | `"decision"` added to `REVIEW_MODES` and `REVIEW_TYPES`. `TYPE_DEFAULTS["decision"] = "standard"`. `TYPE_TO_MODE["decision"] = "decision"`. `MODE_TO_TYPE["decision"] = ("decision", "standard")`. Dispatch branch in `build_reviewer_prompt()` / `build_implementor_prompt()`. Pipeline state writes at decision-review completion (`DECISION_REVISION` or `SPEC_WRITING`), with git-diff fallback for incomplete reviews. |
| `design-review/tracker.py` | `_extract_section_number()` extended for `D<N>` decision references. `_find_section_range()` extended for `## D<N>:` headings. |
| `design-review/review-tiers.md` | Update Post-brainstorming row from future to implemented: `Post-brainstorming \| After approach selected, before spec \| Decision \| Approach fitness, prior art, platform conformance`. Add Decision dimension definition. |
| **New:** `SOURCES.md` | Per-project documentation map (created per project, not in soredium). |
| `project/ctx.py` | `HAS_SOURCES` and `SOURCES_PATH` detection. |

### Implementation Order

1. **SOURCES.md + ctx.py** — prerequisite for brainstorming and decision-review
   to discover documentation. Independent of other components.

2. **Decision capture in brainstorming** — add decisions.md writing during
   approach exploration. Add pipeline state management. Independent of
   decision-review (decisions can be captured without validation).

3. **Approach exploration enhancement** — add deep analysis and multi-agent
   debate tiers to brainstorming. Depends on (2) for decision capture format.

4. **Decision review type** — add to prompts.py, setup.py, review.py.
   Depends on (2) for decisions.md format.

5. **Decision review integration** — wire decision-review invocation into
   brainstorming SKILL.md. Depends on (2) and (4).

6. **Ordered dimensions** — add ordered mode to design-review SKILL.md.
   Independent of (1)-(5). Can be implemented in parallel.

### Structured Data Throughout

**Principle:** CLI is the primary interface. Every artifact has a
human-readable form (markdown) for CLI users. Where structured data
aids tooling, a machine-readable companion is written alongside.
Tools consume the structured data; humans read the markdown.

#### Structured artifacts

| Artifact | Human-readable | Machine-readable | Written by |
|----------|---------------|-------------------|------------|
| Pipeline progress | pipeline.state (key-value) | Same file — already structured | brainstorming, review.py |
| Decisions | decisions.md (markdown) | Same file — Claude parses markdown natively | brainstorming |
| Exploration results | Conversation (CLI) | `specs/<branch>/explorations/D<N>-exploration.md` | brainstorming |
| Decision-review events | progress.log (text) | `EVENT: {json}` lines in progress.log (existing pattern) | review.py |
| Dimension review events | progress.log (text) | `EVENT: {json}` lines (existing pattern) | review.py |
| Tracker state | tracker.md (markdown) | `tracker.jsonl` (existing review.py pattern) | review.py |

#### Exploration artifacts

When deep analysis or multi-agent debate runs, results are written to
`$WORKSPACE/specs/<branch>/explorations/`:

```
explorations/
  D1-exploration.md        ← steelman/DA/first-principles analysis
  D3-debate/
    advocate-A.md              ← position paper for approach A
    advocate-B.md              ← position paper for approach B
    advocate-C.md              ← position paper for approach C
    mediator-synthesis-1.md    ← round 1 mediator synthesis
    mediator-synthesis-2.md    ← round 2 (if requested, focused on user's points)
    mediator-synthesis-3.md    ← round 3 (max, final synthesis)
```

These are reference material — the CLI user sees a summary in
conversation; the full analysis is preserved for decision-review's
reviewer to read and for drafthouse to render.

When a decision is revised and re-explored, the revision's exploration
uses a versioned directory: `D3-debate-r1/`, `D3-debate-r2/`, etc.
This preserves the full audit trail — the decision-review reviewer can
compare pre- and post-revision explorations.

#### Pipeline events

review.py already emits `EVENT: {json}` lines to `progress.log` (the
existing pattern). Pipeline events use the same mechanism — no separate
event file. When drafthouse ships (casehubio/drafthouse#72), it can
parse `progress.log` events or introduce a structured companion file
informed by the actual consumer's needs.

### Not in Scope

- Drafthouse visual pipeline UI (casehubio/drafthouse#72 — reads pipeline.state)
- Changes to writing-plans or downstream implementation skills
- Changes to work-start or work-end
- Automatic exploration depth selection (user always chooses)
- New dimensions beyond the existing coherence/structure/robustness
- Changes to the reviewer/implementor adversarial loop mechanics in review.py
- **POST_SPEC_REVIEW → decision revision path.** If a post-spec reviewer
  discovers a fundamental flaw in an underlying decision, the pipeline
  can only proceed to PLANNING. The user can manually restart the
  pipeline from APPROACH_EXPLORATION if needed. Adding a backward
  transition would significantly complicate the state machine for a
  scenario that decision review is specifically designed to prevent.
