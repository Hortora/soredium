## D1: JudgmentRequest assembly

**Choice:** run_loop assembles JudgmentRequest from StepDef metadata + action_context_fn output
**Alternatives:**
- action_context_fn builds full JudgmentRequest — redundant, each step repeats metadata
- Hybrid StepDef + override — most flexible but most complex
**Rationale:** Clean separation of concerns. Step metadata (handler, schema, skippable, timeout) belongs on StepDef definition. Context (diff range, branch, covers) belongs in action_context_fn. run_loop merges both.
**Trade-offs:** action_context_fn can't override metadata fields (no per-invocation handler switching)
**Sources:** orchestrator_engine.py:run_loop, shared_steps.py:StepDef
**Exploration:** quick
**Status:** captured

## D2: Handler field optionality

**Choice:** handler: str | None — optional
**Alternatives:**
- Create handler files for all 39 steps — uniform but 19 new files that just say "invoke skill X"
- Skill name instead of path — conflates two concepts
**Rationale:** Only 20 of 39 judgment steps have handler .md files. The rest (forage, protocol, trajectory) use loaded skill knowledge. Making handler optional preserves existing behavior without creating stub files.
**Trade-offs:** Steps without handlers are less discoverable — behavior lives in skill knowledge, not in a file
**Sources:** work/handlers/ (11 files), work-end/handlers/ (9 files), survey showing 19 steps without handlers
**Exploration:** quick
**Status:** captured

## D3: Response schema coverage

**Choice:** Default schema for most steps, custom schemas for specific steps
**Alternatives:**
- Mandatory per-step schemas — forces explicit thought but 31 schemas upfront
- Optional schema field (None = no validation) — steps opt in individually
**Rationale:** DEFAULT_JUDGMENT_SCHEMA accepts {step, outcome, produced, evidence?}. Steps needing specific validation (squash, forcing_function) get custom schemas. Incremental — add schemas as needed.
**Trade-offs:** Default schema only validates structure, not content. Custom schemas require effort per step.
**Sources:** 8 verify_fn implementations, 31 steps without verify_fn
**Exploration:** quick
**Status:** captured

## D4: Protocol evolution

**Choice:** Additive args — keep step_done=X produced=N, add outcome= and evidence=
**Alternatives:**
- JSON response arg — cleaner but requires SKILL.md changes immediately
- Version flag — explicit but adds another arg to track
**Rationale:** Zero breaking changes. Orchestrator constructs JudgmentResponse internally, defaulting outcome='completed' when absent. skip_step=X unifies into step_done=X outcome=skipped.
**Trade-offs:** CLI arg parsing is less rigorous than JSON parsing. Evidence dict as a CLI arg needs JSON encoding.
**Sources:** work_end_orchestrator.py:run_orchestrator (current arg parsing)
**Exploration:** quick
**Status:** captured

## D5: Migration scope

**Choice:** Full 4a-4f in one branch
**Alternatives:**
- 4a-4c only — infrastructure lands, per-step conversion deferred
- 4a-4d — also update SKILL.md dispatch tables
**Rationale:** One branch means no dual-protocol maintenance period. All 39 steps converted, old protocol removed, clean cut.
**Trade-offs:** Large branch, harder to review. 39 step conversions in one commit series.
**Sources:** Issue #451 migration steps table
**Exploration:** quick
**Status:** captured
