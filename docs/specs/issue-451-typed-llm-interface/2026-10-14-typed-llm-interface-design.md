# Phase 4: Typed LLM Interface — JudgmentRequest/Response Protocol

**Issue:** #451
**Branch:** issue-451-typed-llm-interface
**Parent spec:** specs/issue-443-robust-pipeline-architecture/2026-10-12-robust-pipeline-architecture-design.md § Phase 4
**Scope:** Full migration (4a-4f) in one branch

## Problem

The orchestrator engine (`run_loop`) drives 39 judgment steps across 3 orchestrators (work-end: 23, wrap: 5, work.py: 11). The LLM interface is stringly-typed:

- `_yield_judgment` returns ad-hoc `dict[str, str]` with `ACTION=step_name` and `COMPLETE_WITH=step_done={step} produced=N`
- `step_done=X produced=N` response has no structured outcome (completed vs skipped vs blocked)
- 31 of 39 steps have no `verify_fn` — responses are accepted without validation
- `step_type` is a plain string checked via `==`, allowing typos at definition time
- `skip_step=X` is a separate mechanism from `step_done=X`, with its own validation path

## Design

Formalize the existing Python-drives-LLM pattern with typed dataclasses, enums, and schema validation. The communication channel stays the same (KEY=VALUE on stdout, command-line args on re-entry). The typing is on the Python side.

### New Types (project/judgment.py)

```python
from dataclasses import dataclass
from enum import Enum


class StepType(Enum):
    MECHANICAL = "mechanical"
    JUDGMENT = "judgment"
    LIFECYCLE = "lifecycle"


class Outcome(Enum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class JudgmentRequest:
    step: str                        # step name
    handler: str | None              # path to handler .md, or None
    context: dict                    # from action_context_fn
    response_schema: dict            # JSON schema for validation
    skippable: bool                  # can the LLM skip this step?
    timeout_hint: str                # "quick" | "standard" | "extended"


@dataclass(frozen=True)
class JudgmentResponse:
    step: str                        # echoes request.step
    outcome: Outcome                 # completed | skipped | blocked
    produced: int                    # artifacts produced
    evidence: dict                   # step-specific output
    block_reason: str | None         # if blocked, why


DEFAULT_JUDGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "step": {"type": "string"},
        "outcome": {"type": "string", "enum": ["completed", "skipped", "blocked"]},
        "produced": {"type": "integer", "minimum": 0},
        "evidence": {"type": "object"},
        "block_reason": {"type": ["string", "null"]},
    },
    "required": ["step", "outcome", "produced"],
}
```

### StepDef Changes (project/shared_steps.py)

```python
@dataclass
class StepDef:
    name: str
    phase: str
    step_type: StepType              # was: str
    script_fn: Callable | None = None
    skip_fn: Callable | None = None
    action_context_fn: Callable | None = None
    verify_fn: Callable | None = None
    outcome_fn: Callable | None = None
    idempotent: bool = True
    handler: str | None = None       # NEW — path to handler .md
    response_schema: dict | None = None  # NEW — None = DEFAULT_JUDGMENT_SCHEMA
    skippable: bool = True           # NEW — can LLM skip?
    timeout_hint: str = "standard"   # NEW — quick | standard | extended
    from_state: str | None = None
    to_state: str | None = None
    event: str | None = None
    modes: frozenset[PipelineMode] = field(default_factory=lambda: ALL_MODES)
    dispositions: frozenset[RepoDisposition] = field(default_factory=lambda: ALL_DISPOSITIONS)
    disposition_repo_types: frozenset[RepoType] = field(default_factory=lambda: ALL_REPO_TYPES)
    requires: tuple[str, ...] = ()
    staleness_relevant: bool = True
```

### Request Assembly (orchestrator_engine.py run_loop)

`run_loop` assembles `JudgmentRequest` from StepDef metadata + `action_context_fn` output. The `action_context_fn` continues to return `dict` (context only). `run_loop` merges:

```python
context = step.action_context_fn(ctx) if step.action_context_fn else {}
request = JudgmentRequest(
    step=step.name,
    handler=step.handler,
    context=context,
    response_schema=step.response_schema or DEFAULT_JUDGMENT_SCHEMA,
    skippable=step.skippable,
    timeout_hint=step.timeout_hint,
)
```

### Request Serialization

`_yield_judgment` takes a `JudgmentRequest` and serializes to KEY=VALUE stdout:

```
ACTION=code_review
HANDLER=handlers/review.md
CONTEXT={"DIFF_RANGE": "main..issue-451-typed-llm-interface"}
SCHEMA={"type": "object", ...}
SKIPPABLE=yes
TIMEOUT_HINT=standard
COMPLETE_WITH=step_done=code_review outcome=completed produced=N
```

`HANDLER` is omitted when None. `SCHEMA` is JSON-encoded. The existing `COMPLETE_WITH` hint updates to include `outcome=`.

### Response Parsing

When `step_done=X` arrives in `run_orchestrator` or `work.py`:

1. Parse `outcome=` (default: `"completed"` for backward compat during the conversion)
2. Parse `produced=` (default: `0`)
3. Parse `evidence=` (default: `"{}"`, JSON-decoded)
4. Parse `block_reason=` (default: `None`)
5. Construct `JudgmentResponse`
6. Validate against the step's `response_schema` (from StepDef)
7. Schema violation → return `{"ACTION": "error", "ERROR": "schema_violation", "STEP": step, "DETAIL": ...}`
8. Valid → proceed to `apply_step_done`

### skip_step Unification

`skip_step=X` is replaced by `step_done=X outcome=skipped`. The existing `validate_skip` logic (last_yielded check, attempt counter reset) moves into the response parsing path. The `skip_step` arg is removed from all orchestrators.

### user_input Steps

Steps in `CLOSE_USER_INPUT_STEPS` (arc42_scan, session_rename, garden_feedback, notes) currently use `_yield_user_input` with a separate code path. These unify:

- `_yield_user_input` merges into `_yield_judgment` — the request includes a `user_input=True` context flag
- The LLM reads this flag and uses user_input handling (prompt the user directly)
- Response parsing is the same as judgment steps

### SKILL.md Changes

Work-end, wrap, and work SKILL.md dispatch tables update:

1. The orchestrator output now includes `HANDLER=` — the LLM reads the handler path from the request instead of looking it up in a hardcoded table
2. Steps without a handler (`HANDLER` absent) use loaded skill knowledge
3. The dispatch table becomes a fallback reference
4. Response protocol section updates to document `outcome=`, `evidence=`, `block_reason=`

### Step Conversion (All 39)

Every judgment step across all 3 orchestrators converts:

| Change | Count | What |
|--------|-------|------|
| `step_type` string → `StepType` enum | All steps (mechanical, judgment, lifecycle) | Catches typos at definition |
| `handler=` added | 20 judgment steps | Points to existing handler .md |
| `response_schema=` added | 8 judgment steps | Custom schemas for squash, forcing_function, etc. |
| `skippable=` set | As needed | Some steps (code_review) may be non-skippable |
| `timeout_hint=` set | As needed | Extended for review steps, quick for sweep config |

### Custom Schemas

Steps with existing `verify_fn` get specific schemas:

- **code_review, branch_audit_***: `produced` required (integer >= 0)
- **forcing_function**: `evidence.open_findings` required (integer, must be 0)
- **squash**: `evidence.verified` required (boolean, must be true)
- **loose_ends**: `produced` required (integer >= 0)

Other steps use `DEFAULT_JUDGMENT_SCHEMA`.

## Migration Strategy

Full conversion in one branch. No dual-protocol maintenance period.

**Order:**
1. Create `project/judgment.py` with StepType, Outcome, JudgmentRequest, JudgmentResponse, DEFAULT_JUDGMENT_SCHEMA
2. Update `StepDef` — add new fields, change `step_type` to `StepType`
3. Update `run_loop` — assemble JudgmentRequest, update _yield_judgment signature
4. Update response parsing — construct JudgmentResponse from args, validate against schema
5. Unify skip_step into outcome=skipped
6. Convert all step definitions (step_type enum, handler, schema, skippable, timeout_hint)
7. Update SKILL.md dispatch tables
8. Remove old `skip_step` arg handling, old `_yield_user_input` separate path

## Risks

**Evidence encoding:** `evidence=` as a JSON-encoded CLI arg may hit shell escaping issues with complex dicts. Mitigation: the orchestrator writes evidence to the progress file (`{step}_evidence={json}`) and reads it back on re-entry, same pattern as `_landed_sha:` keys. The CLI arg is best-effort for simple cases.

## What Does NOT Change

- Handler `.md` files — content stays the same
- `action_context_fn` return type — still returns `dict`
- Mechanical step execution — pure Python, untouched
- Lifecycle step handling — transitions, untouched
- Progress file format — same KEY=VALUE
- The orchestrator call loop in SKILL.md — still calls the Python script in a loop

## Testing Strategy

| Test | What |
|------|------|
| Round-trip | JudgmentRequest → serialize → parse → same values |
| Schema validation | DEFAULT_JUDGMENT_SCHEMA accepts valid, rejects malformed |
| Custom schema | squash schema requires verified=true |
| StepType coverage | Parameterized: every StepDef uses valid StepType enum |
| Outcome parsing | completed/skipped/blocked all parse correctly |
| Backward compat | step_done=X produced=N without outcome= defaults to completed |
| skip_step unification | step_done=X outcome=skipped replaces skip_step=X, same last_yielded check |
| Invalid rejection | Malformed evidence, unknown outcome, wrong step name → specific errors |
| Block handling | outcome=blocked with block_reason= returns error to orchestrator |

## References

- specs/issue-443-robust-pipeline-architecture/2026-10-12-robust-pipeline-architecture-design.md § Phase 4
- project/orchestrator_engine.py — run_loop, _yield_judgment, _yield_user_input, apply_step_done
- project/shared_steps.py — StepDef, yield_judgment, yield_user_input
- work-end/work_end_orchestrator.py — STEPS list, run_orchestrator
- handover/wrap_orchestrator.py — wrap steps
- project/work.py — work pipeline steps
- docs/protocols/skill-md-minimal-orchestrator-loop.md — handler extraction protocol
- Issue #451, parent issue #443
