## D1: Three-module decomposition

**Choice:** Split ctx.py into three modules: `topology.py` (path resolution), `ctx.py` (field collection), `work_state.py` (replaces work_router.py).
**Alternatives:**
- Topology layer only — smallest change but leaves duplication between ctx and work_router
- Consolidate ctx + work_router — merges into one file, fixes duplication but creates a monolith
**Rationale:** Separate modules with one job each are easier to trace and fix. Each module has clear inputs and outputs. Stops the whack-a-mole.
**Trade-offs:** Three files instead of one. Worth it for traceability.
**Exploration:** quick
**Status:** captured

## D2: Single CLI entry point, no code duplication

**Choice:** ctx.py remains the only CLI entry point (`python3 ctx.py` → KEY=VALUE). Internally imports topology and work_state. Python consumers import any module directly. No duplication of path resolution logic.
**Alternatives:**
- Each module gets its own CLI — more entry points, harder to trace
**Rationale:** Minimise entry points and paths through. Skills don't change. Tracing starts at ctx.py and follows imports.
**Trade-offs:** None meaningful.
**Exploration:** quick
**Status:** captured

## D3: Flat dataclass with layout discriminator

**Choice:** Topology is a single flat `@dataclass` with a `layout: Literal["single", "dual", "slot"]` discriminator. Optional fields (`slot_dir`, `primary_repo`) are `None` when not applicable.
**Alternatives:**
- Discriminated union (`SingleRepo | DualRepo | SlotRepo`) — type-safe but requires isinstance checks, harder to serialize to KEY=VALUE
**Rationale:** The three layouts differ in which fields are populated, not in behavior. Flat struct is easy to trace, serialize, and doesn't need isinstance chains.
**Trade-offs:** No compile-time enforcement of "don't access slot_dir on dual-repo" — runtime None instead.
**Exploration:** quick
**Status:** captured
