# ctx.py Topology Rewrite — Design Spec

**Issue:** Hortora/soredium#220
**Branch:** issue-220-ctx-rewrite (not yet created)
**Date:** 2026-08-11

## Problem

ctx.py was designed for two-repo mode (project + workspace, each a git root) but has been patched for three layouts (single-repo, dual-repo, multi-repo slot) with ad-hoc fallback chains. Each new field that needs path resolution adds its own fallback logic. work_router.py duplicates detection logic with a different fallback chain, causing inconsistencies (#1 critical finding). 15 audit findings — the fragility is architectural, not per-bug.

## Design

Three modules, one job each. No code duplication. One CLI entry point.

### Module 1 — `project/topology.py`

Path resolution only. Given a CWD, returns where everything is.

```python
@dataclass
class Topology:
    layout: Literal["single", "dual", "slot"]
    project: Path           # git root of current project repo
    workspace: Path         # effective workspace path (may be subdir in slots)
    workspace_root: Path    # git root of workspace repo (== workspace in non-slot dual mode)
    slot_dir: Path | None   # slot root (slots/N/) — None outside slots
    primary_repo: str | None  # from .slot Repos section — None outside slots
    in_worktree: bool
    main_worktree_root: Path | None

def resolve(cwd: str | None = None) -> Topology
```

Detection order — single code path, no fallback chains:

1. Git root via `git rev-parse --show-toplevel`
2. Worktree detection via `git worktree list --porcelain`
3. Symlink resolution: `proj/` or `wksp/` from symlink root (main worktree root if in worktree, else git root)
4. Layout determination:
   - Neither symlink exists → `single` (workspace = project)
   - Symlink target IS a git root → `dual` (workspace = workspace_root = target)
   - Symlink target is INSIDE a git repo → `dual` (workspace = subdir, workspace_root = enclosing git root)
5. Slot detection: structural check on project path (parent has `.slot` file, not substring matching). If slot: parse `.slot` for primary_repo, set slot_dir = project.parent

`_resolve_symlink_target` moves here from ctx.py. It is the only function that resolves symlinks — no other module does this.

### Module 2 — `project/ctx.py` (field collector)

Imports `topology.resolve()` and `work_state.detect()`. Collects all KEY=VALUE fields. No path resolution — every path comes from the Topology object.

```python
def resolve(cwd=None) -> dict[str, str]:
    topo = topology.resolve(cwd)
    state = work_state.detect(topo)
    # ... field collection using topo and state ...
    return combined_dict
```

Key rules:

- **CLAUDE.md** — ALL fields from `topo.project / "CLAUDE.md"`. No split between project and CWD. Fixes finding #2.
- **OWNER_REPO** — from `topo.project / "CLAUDE.md"` always. In slots this is the current repo's owner, not the primary's. Finding #3 noted this as a warning but the fix is a separate concern (needs `.slot` issue-repo, not just CLAUDE.md).
- **.meta, .plan, .epic** — all use a shared search helper `_find_design_file(name, topo)` (see below). No per-field fallback chains.
- **File existence checks** (PLATFORM.md, protocols/, SOURCES.md, blog-routing.yaml) — check `topo.project`, `topo.workspace`, `topo.workspace_root`. No vestigial `workspace/workspace/` paths.
- **Git failures** — `run()` returns `""` on failure. Any field derived from a git command that returns `""` is flagged (e.g., empty branch → BRANCH_MISMATCH should not fire).

#### Shared search helper

```python
def _find_design_file(name: str, topo: Topology) -> Path | None:
    """Search all relevant locations for a design file (.meta, .plan, .epic).
    
    Order: workspace subdir, workspace git root, slot root,
    primary repo workspace (via .slot), primary workspace git root.
    """
    candidates = [topo.workspace, topo.workspace_root]
    if topo.slot_dir:
        candidates.append(topo.slot_dir)
    
    for base in candidates:
        if base is None:
            continue
        for sub in [base / "design" / name, base / name]:
            if sub.exists():
                return sub
    
    # Slot primary repo workspace fallback
    if topo.slot_dir and topo.primary_repo:
        primary_wksp = topo.slot_dir / topo.primary_repo / "wksp"
        if primary_wksp.is_symlink():
            target = primary_wksp.resolve()
            for path in [target / "design" / name, target / name]:
                if path.exists():
                    return path
            root = _git_root(target)
            if root and str(root) != str(target):
                for path in [Path(root) / "design" / name, Path(root) / name]:
                    if path.exists():
                        return path
    return None
```

One function replaces ALL fallback chains. `.meta`, `.plan`, `.epic` all call it. Adding a new design file is one line, not a new fallback chain.

### Module 3 — `project/work_state.py` (replaces work/work_router.py)

Imports `topology.Topology`. Detects lifecycle state, routing decision, plan/epic context. No path resolution — uses what topology provides.

```python
@dataclass
class WorkState:
    route: str              # start, resume_stack, resume_branch, workspace_dirty
    on_main: bool
    in_slot: bool
    has_plan: bool
    plan_path: str
    plan_active_issue: str
    plan_position: str
    plan_batch: str
    stack_depth: int
    has_handoff: bool
    handoff_path: str
    meta_state: str
    meta_is_transient: bool

def detect(topo: Topology) -> WorkState
```

Plan detection uses `_find_design_file(".plan", topo)` — shared with ctx.py. No separate plan detection logic. This is the fix for finding #1 (critical).

### Lifecycle import fix

topology.py and work_state.py both need `lifecycle.py`. The import uses explicit path insertion (same pattern as work-slot imports) so callers don't need to manage sys.path. Fixes finding #7.

### .meta parsing consistency

Both ctx.py and lifecycle.py parse `.meta`. The rewrite uses a single `_parse_meta(path)` function in ctx.py that handles both `: ` and `:` separators. lifecycle.py's `read_state()` is called once, not double-read. Fixes findings #4, #10, #13.

## Files changed

| File | Change |
|------|--------|
| `project/topology.py` | **New** — Topology dataclass, resolve(), _resolve_symlink_target() |
| `project/ctx.py` | **Rewrite** — field collector, imports topology + work_state, _find_design_file() |
| `project/work_state.py` | **New** — WorkState dataclass, detect(), replaces work_router |
| `work/work_router.py` | **Delete** — replaced by work_state.py |
| `work/brief.py` | **Simplify** — import ctx.resolve() or work_state.detect() instead of composing two sources |
| `tests/test_topology.py` | **New** — path resolution tests (all layouts) |
| `tests/test_ctx.py` | **Rewrite** — field collection tests, reuse test_topology fixtures |
| `tests/test_work_state.py` | **New** — lifecycle/plan state tests |
| `tests/test_work_router.py` | **Delete** — replaced by test_work_state.py |

## What doesn't change

- CLI interface: `python3 ctx.py` → KEY=VALUE (same keys, same format)
- All SKILL.md files — they call ctx.py the same way
- lifecycle.py — untouched
- plan_manager.py — untouched (detect() is called by work_state, not duplicated)
- slot_manager.py — untouched

## Audit findings addressed

| # | Finding | Fixed by |
|---|---------|----------|
| 1 | work_router.py duplicates plan detection | work_state.py uses _find_design_file via ctx |
| 2 | Split CLAUDE.md parsing | All fields from topo.project |
| 4 | HAS_META/META_STATE inconsistency | Single _parse_meta function |
| 5 | blog-routing.yaml misses workspace root | File checks use topo.workspace_root |
| 6 | Git failures → misleading BRANCH_MISMATCH | Empty branch from git failure detected |
| 7 | lifecycle import no self-path-insertion | Explicit path insertion in topology.py |
| 8 | Epic detection lacks primary-repo fallback | Uses _find_design_file (symmetric with plan) |
| 9 | Manual .slot parsing | Use parse_slot_md from slot_manager |
| 10 | Double .meta read | Single _parse_meta call |
| 11 | CWD CLAUDE.md uses raw CWD not git root | All from topo.project |
| 12 | Vestigial workspace/workspace/ paths | Removed |
| 13 | .meta `: ` vs `:` inconsistency | _parse_meta handles both |
| 14 | No IN_SLOT field | topo.layout == "slot" exposed as IN_SLOT |
| 15 | is_slot_path substring matching | Structural .slot file check |

Finding #3 (OWNER_REPO reflects current repo not primary in multi-repo slots) is noted but not fixed in this rewrite — it requires reading the primary repo's CLAUDE.md which introduces a cross-repo read. Filed separately if needed.

## Test plan

Tests per protocol `externalised-scripts-require-tests`:

### test_topology.py
1. Single-repo: no symlinks → layout=single, workspace=project
2. Dual-repo with wksp: wksp → git root → layout=dual
3. Dual-repo with proj: proj → git root → layout=dual
4. Slot with subdir wksp: wksp → subdir → layout=dual, workspace_root != workspace
5. Slot detection: .slot in parent → slot_dir set, primary_repo parsed
6. Worktree resolution: wksp in main worktree found from worktree
7. Broken symlink walks up to git root
8. Dangling symlink outside any git repo → None
9. Symlink to path outside git repo → single-repo fallback

### test_work_state.py
10. On main, no stack → route=start
11. On main, stack entries → route=resume_stack
12. On feature branch → route=resume_branch
13. Workspace dirty (different branch) → route=workspace_dirty
14. Plan found via _find_design_file → has_plan=True
15. Plan at slot root found → has_plan=True
16. Plan at primary workspace found → has_plan=True
17. No plan anywhere → has_plan=False

### test_ctx.py (field collection)
18. OWNER_REPO from project CLAUDE.md (not CWD)
19. All CLAUDE.md fields from same file
20. .meta found at workspace root when workspace is subdir
21. .meta found at primary workspace in slot
22. File existence checks use workspace_root
23. Empty git branch → BRANCH_MISMATCH not triggered
24. IN_SLOT=yes when in slot layout
