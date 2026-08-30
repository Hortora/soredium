#!/usr/bin/env python3
"""
Lifecycle state machine for work branches.

Single source of truth for state transitions. Entry points fire events;
the transition table determines effects. No entry point decides what to do —
the state machine decides.

Three-phase protocol:
  1. transition()         — validate, return TransitionResult (no write)
  2. caller executes effects, then commit_transition() — verify + atomic write
  3. caller executes post_commit_effects (branch switches, cleanup)

Spec: issue-171-lifecycle-state-machine
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import subprocess as _sp
import sys
from pathlib import Path
from typing import Optional

VALID_STATES = frozenset({
    'idle', 'scaffolded', 'active', 'transitioning', 'paused', 'drained',
    'closing:review', 'closing:verified', 'closing:promoted',
    'closing:pushed', 'closing:merged', 'closing:stamped',
})

TRANSIENT_STATES = frozenset({'scaffolded', 'transitioning'})

CLOSING_STATES = frozenset({
    'closing:review', 'closing:verified', 'closing:promoted',
    'closing:pushed', 'closing:merged', 'closing:stamped',
})

RESTING_STATES = VALID_STATES - TRANSIENT_STATES


@dataclass
class TransitionResult:
    from_state: str
    new_state: str
    event: str
    effects: list[str] = field(default_factory=list)
    post_commit_effects: list[str] = field(default_factory=list)


class InvalidTransition(Exception):
    def __init__(self, from_state: str, event: str, message: str):
        self.from_state = from_state
        self.event = event
        super().__init__(message)


class InvalidState(Exception):
    def __init__(self, state: str, violations: list[str]):
        self.state = state
        self.violations = violations
        super().__init__(f"State '{state}' invariant violations: {violations}")


class ConcurrentModification(Exception):
    def __init__(self, expected: str, actual: str):
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"State changed by another session: expected '{expected}', found '{actual}'"
        )


class CorruptedState(Exception):
    def __init__(self, meta_path: Path, raw_value: str):
        self.meta_path = meta_path
        self.raw_value = raw_value
        super().__init__(f"Unknown state '{raw_value}' in {meta_path}")


class StateError(Exception):
    pass


class MissingEvidence(Exception):
    def __init__(self, event: str, required_keys: list[str]):
        self.event = event
        self.required_keys = required_keys
        super().__init__(
            f"Gated transition '{event}' requires evidence with keys: "
            f"{', '.join(required_keys)}"
        )


class InvalidEvidence(Exception):
    def __init__(self, event: str, violations: list[str]):
        self.event = event
        self.violations = violations
        super().__init__(
            f"Evidence for '{event}' failed validation: "
            f"{'; '.join(violations)}"
        )


# --- Transition table ---

# (from_state, event): (new_state, effects, post_commit_effects)
TRANSITION_TABLE: dict[tuple[str, str], tuple[str, list[str], list[str]]] = {
    # Core lifecycle
    ('idle', 'work'):                  ('scaffolded',       ['create_branch', 'write_plan', 'build_plan'],                             []),
    ('idle', 'slot_create'):           ('scaffolded',       ['create_slot', 'write_plan', 'build_plan'],                               []),
    ('scaffolded', 'auto_setup'):      ('active',           ['garden_search', 'load_specs', 'check_protocols', 'check_intellij'],      []),
    ('active', 'work_next'):           ('transitioning',    ['advance_issue', 'tick_github'],                                          []),
    ('transitioning', 'auto_refresh'): ('active',           ['garden_search', 'load_specs', 'check_protocols'],                        []),
    ('active', 'work_continue'):       ('active',           [],                                                                        []),
    ('active', 'work_pause'):          ('paused',           ['wip_commit'],                                                            ['switch_to_main', 'push_stack']),
    ('paused', 'work_resume'):         ('active',           ['pop_stack', 'reset_wip', 'context_resume'],                              []),
    # Closing sequence
    ('active', 'work_end'):                  ('closing:review',    ['pre_close_sweep'],                                                []),
    ('closing:review', 'review_pass'):       ('closing:verified',  ['record_review'],                                                  []),
    ('closing:verified', 'promote_pass'):    ('closing:promoted',  ['write_promotion_stamp'],                                          []),
    ('closing:promoted', 'push_pass'):       ('closing:pushed',    [],                                                                 []),
    ('closing:pushed', 'merge_pass'):        ('closing:merged',    ['verify_content_landed'],                                          []),
    ('closing:merged', 'stamp_pass'):        ('closing:stamped',   ['write_stamp'],                                                    []),
    ('closing:stamped', 'cleanup_pass'):     ('idle',              ['write_plan_closed'],                                               ['return_to_main', 'write_handoff']),
    ('closing:stamped', 'cleanup_main'):    ('drained',           ['write_plan_drained'],                                              ['write_handoff']),
    ('drained', 'work_find'):               ('transitioning',     ['queue_populated'],                                                  []),
    # Abort (pre-artifact only)
    ('closing:review', 'abort_close'):       ('active',            ['clear_closing_markers'],                                           []),
    ('closing:verified', 'abort_close'):     ('active',            ['clear_closing_markers'],                                           []),
}

INVALID_MESSAGES: dict[tuple[str, str], str] = {
    ('idle', 'work_next'):      "Cannot advance — no active branch. Start work first.",
    ('idle', 'work_pause'):     "Cannot pause — no active branch.",
    ('idle', 'work_end'):       "Cannot close — no active branch. You're on main.",
    ('idle', 'work_resume'):    "Cannot resume — pause stack is empty.",
    ('idle', 'work_continue'):  "Cannot continue — no active branch. Use `work` to start new work.",
    ('scaffolded', 'work_next'): "Branch not yet active — context setup must complete first.",
    ('scaffolded', 'work_end'):  "Cannot close — branch hasn't been activated yet.",
    ('scaffolded', 'work_pause'): "Cannot pause — branch hasn't been activated yet.",
    ('scaffolded', 'work_continue'): "Cannot continue — branch not yet active. Context setup must complete first.",
    ('active', 'work'):         "Already on an active branch. Use `work continue`, `work end`, `work pause`, or `work next`.",
    ('active', 'work_resume'):  "Branch is active, not paused. Nothing to resume.",
    ('transitioning', 'work_end'):   "Issue transition in progress — context refresh must complete first.",
    ('transitioning', 'work_pause'): "Issue transition in progress — wait for context refresh.",
    ('transitioning', 'work_continue'): "Cannot continue — issue transition in progress. Wait for context refresh.",
    ('paused', 'work_end'):     "Cannot close a paused branch. Resume it first, then close.",
    ('paused', 'work_next'):    "Cannot advance — branch is paused. Resume first.",
    ('paused', 'work_pause'):   "Branch is already paused.",
    ('paused', 'work_continue'): "Branch is paused. Use `work resume` to restore it from the pause stack first.",
    ('closing:promoted', 'abort_close'): "Cannot abort — artifacts already workspace-promoted and project-promoted. Continue forward.",
    ('closing:pushed', 'abort_close'):   "Cannot abort — artifacts already workspace-promoted and project-promoted. Branch pushed — continue forward.",
    ('closing:merged', 'abort_close'):   "Cannot abort — content already merged to main. Continue forward.",
    ('closing:stamped', 'abort_close'):  "Cannot abort — branch already stamped. Only cleanup remains.",
    ('drained', 'work_end'):       "Already drained. Use `work find` to discover new work.",
    ('drained', 'work_pause'):     "Nothing active to pause.",
    ('drained', 'work_resume'):    "Nothing to resume. Use `work find` to discover new work.",
    ('drained', 'work_next'):      "Queue is empty. Use `work find` to discover new work.",
    ('drained', 'work_continue'):  "Queue is drained. Use `work find` to discover new work.",
    ('drained', 'work'):           "Queue is drained. Use `work find` to discover new work, or `work start #N` for a specific issue.",
}


# --- Public API ---


def read_state(plan_path: Path) -> Optional[str]:
    """Read lifecycle state from .plan's ## State section (or legacy .meta).
    Returns None if file doesn't exist.
    Raises CorruptedState if state: field has unrecognised value."""
    if not plan_path.exists():
        return None
    in_state_section = False
    has_sections = False
    for line in plan_path.read_text().splitlines():
        if line.strip() == '## State':
            in_state_section = True
            has_sections = True
            continue
        if line.startswith('## '):
            in_state_section = False
            continue
        if in_state_section and line.startswith('state:'):
            raw = line.split(':', 1)[1].strip()
            if raw in VALID_STATES:
                return raw
            raise CorruptedState(plan_path, raw)
    if has_sections:
        return 'active'
    for line in plan_path.read_text().splitlines():
        if line.startswith('state:'):
            raw = line.split(':', 1)[1].strip()
            if raw in VALID_STATES:
                return raw
            raise CorruptedState(plan_path, raw)
    return 'active'


def write_state(plan_path: Path, state: str) -> None:
    """Write lifecycle state to .plan's ## State section atomically."""
    content = plan_path.read_text()
    lines = content.splitlines()

    in_state_section = False
    has_sections = any(l.strip() == '## State' for l in lines)
    state_line_idx = None

    if has_sections:
        for i, line in enumerate(lines):
            if line.strip() == '## State':
                in_state_section = True
                continue
            if line.startswith('## '):
                in_state_section = False
                continue
            if in_state_section and line.startswith('state:'):
                state_line_idx = i
                break
    else:
        for i, line in enumerate(lines):
            if line.startswith('state:'):
                state_line_idx = i
                break

    if state_line_idx is not None:
        lines[state_line_idx] = f'state: {state}'
    else:
        inserted = False
        for i, line in enumerate(lines):
            if line.startswith('branch:'):
                lines.insert(i + 1, f'state: {state}')
                inserted = True
                break
        if not inserted:
            lines.append(f'state: {state}')

    tmp_path = plan_path.parent / '.plan.tmp'
    tmp_path.write_text('\n'.join(lines) + '\n')
    tmp_path.replace(plan_path)


def write_branch(plan_path: Path, branch: str) -> None:
    """Write branch field to .plan's ## State section atomically."""
    content = plan_path.read_text()
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.startswith('branch:'):
            lines[i] = f'branch: {branch}'
            break
    tmp = plan_path.parent / '.plan.tmp'
    tmp.write_text(chr(10).join(lines) + chr(10))
    tmp.replace(plan_path)


_DEPRECATED_EVENTS = {
    'work_epic': ('work', "work_epic is deprecated — epic detection is now automatic. Use 'work' instead."),
    'slot_epic': ('slot_create', "slot_epic is deprecated — epic detection is now automatic. Use 'slot_create' instead."),
}


def transition(
    plan_path: Path,
    event: str,
    project: Optional[Path] = None,
    workspace: Optional[Path] = None,
) -> TransitionResult:
    """Phase 1: Validate transition and return result. Does NOT write state."""
    raw_state = read_state(plan_path)
    current_state = raw_state or 'idle'

    if event in _DEPRECATED_EVENTS:
        new_event, warning = _DEPRECATED_EVENTS[event]
        print(f"WARN=deprecated_event old={event} new={new_event} detail={warning}")
        event = new_event

    key = (current_state, event)
    if key not in TRANSITION_TABLE:
        msg = INVALID_MESSAGES.get(
            key, f"No transition from '{current_state}' on '{event}'"
        )
        raise InvalidTransition(current_state, event, msg)

    new_state, effects, post_commit = TRANSITION_TABLE[key]

    if project is not None and workspace is not None:
        violations = validate_state(new_state, project, workspace)
        if violations:
            raise InvalidState(new_state, violations)

    return TransitionResult(
        from_state=current_state,
        new_state=new_state,
        event=event,
        effects=list(effects),
        post_commit_effects=list(post_commit),
    )


_LIFECYCLE_TO_WORKLOG: dict[str, str | None] = {
    'scaffolded': 'active',
    'active': 'active',
    'transitioning': 'active',
    'paused': 'paused',
    'idle': 'ended',
    'drained': 'idle',
}


def _read_branch(plan_path: Path) -> Optional[str]:
    """Read branch name from .plan's ## State section (or legacy .meta)."""
    if not plan_path.exists():
        return None
    in_state_section = False
    has_sections = False
    for line in plan_path.read_text().splitlines():
        if line.strip() == '## State':
            in_state_section = True
            has_sections = True
            continue
        if line.startswith('## '):
            in_state_section = False
            continue
        if in_state_section and line.startswith('branch:'):
            return line.split(':', 1)[1].strip()
    if has_sections:
        return None
    for line in plan_path.read_text().splitlines():
        if line.startswith('branch:'):
            return line.split(':', 1)[1].strip()
    return None


def _emit_to_worklog(
    plan_path: Path,
    result: TransitionResult,
    repo_path: str,
    metadata: Optional[dict],
) -> None:
    """Best-effort worklog emission. Never blocks."""
    try:
        import os
        scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import worklog

        db_path = os.environ.get("WORKLOG_DB")
        conn = worklog.connect(db_path) if db_path else worklog.connect()

        branch = _read_branch(plan_path)
        if not branch:
            conn.close()
            return

        wid = worklog.find_work_item(conn, branch, repo_path)

        wl_state = _LIFECYCLE_TO_WORKLOG.get(result.new_state)
        if wl_state and wid:
            worklog.update_work_item_state(conn, wid, wl_state)

        event_meta: dict = {
            'from_state': result.from_state,
            'to_state': result.new_state,
        }
        if metadata:
            event_meta.update(metadata)

        worklog.log_transition(
            conn, result.event,
            work_item_id=wid,
            repo_path=repo_path,
            metadata=event_meta,
        )
        conn.close()
    except Exception as e:
        print(f"WARN=worklog_error detail={e}")


# --- Evidence gating ---

EVIDENCE_GATES: dict[str, list[str]] = {
    'review_pass':   ['review_result'],
    'promote_pass':  ['promoted_files', 'target_repos'],
    'push_pass':     ['pushed_repos', 'pushed_shas'],
    'merge_pass':    ['landed_shas', 'verified_on_main'],
    'stamp_pass':    ['stamp_shas'],
    'cleanup_pass':  ['repos_on_main', 'work_items_ended'],
    'cleanup_main':  ['work_items_ended'],
}


def _validate_evidence(event: str, evidence: dict) -> list[str]:
    """Validate evidence for a gated transition. Returns violations."""
    violations: list[str] = []
    required = EVIDENCE_GATES.get(event, [])
    for key in required:
        if key not in evidence:
            violations.append(f"missing key: {key}")

    if event == 'merge_pass' and 'verified_on_main' in evidence:
        vom = evidence['verified_on_main']
        if isinstance(vom, dict):
            for repo, on_main in vom.items():
                if not on_main:
                    violations.append(f"{repo} not verified on main")

    if event in ('cleanup_pass', 'cleanup_main'):
        if evidence.get('work_items_ended') is not True:
            violations.append("work_items_ended must be true")
    if event == 'cleanup_pass' and 'repos_on_main' in evidence:
        rom = evidence['repos_on_main']
        if isinstance(rom, dict):
            for repo, on_main in rom.items():
                if not on_main:
                    violations.append(f"{repo} not on main")

    return violations


def _read_evidence_era(plan_path: Path) -> bool:
    """Check if the current closing sequence was started under the evidence era."""
    if not plan_path.exists():
        return False
    in_state = False
    for line in plan_path.read_text().splitlines():
        if line.strip() == '## State':
            in_state = True
            continue
        if line.startswith('## '):
            in_state = False
            continue
        if in_state and line.strip() == 'evidence-era: true':
            return True
    return False


def _write_evidence_era(plan_path: Path) -> None:
    """Mark the current closing sequence as evidence-era."""
    if not plan_path.exists():
        return
    content = plan_path.read_text()
    if 'evidence-era: true' in content:
        return
    lines = content.splitlines()
    in_state = False
    insert_idx = None
    for i, line in enumerate(lines):
        if line.strip() == '## State':
            in_state = True
            continue
        if line.startswith('## '):
            if in_state:
                insert_idx = i
                break
            in_state = False
            continue
        if in_state and line.startswith('state:'):
            insert_idx = i + 1
    if insert_idx is not None:
        lines.insert(insert_idx, 'evidence-era: true')
        tmp_path = plan_path.parent / '.plan.tmp'
        tmp_path.write_text('\n'.join(lines) + '\n')
        tmp_path.replace(plan_path)


def commit_transition(
    plan_path: Path,
    result: TransitionResult,
    repo_path: Optional[str] = None,
    metadata: Optional[dict] = None,
    evidence: Optional[dict] = None,
) -> None:
    """Phase 2: Verify state unchanged, write atomically, emit worklog.

    For gated transitions (closing sequence), evidence is required when
    the closing sequence was started under the evidence era. Old closing
    sequences are allowed through with a warning.
    """
    if result.event == 'work_end':
        _write_evidence_era(plan_path)

    if result.event in EVIDENCE_GATES:
        era = _read_evidence_era(plan_path)
        if evidence is None and era:
            raise MissingEvidence(result.event, EVIDENCE_GATES[result.event])
        if evidence is None and not era:
            print(f"WARN=legacy_closing no_evidence event={result.event}")
        if evidence is not None:
            violations = _validate_evidence(result.event, evidence)
            if violations:
                raise InvalidEvidence(result.event, violations)

    if result.from_state == 'idle':
        if not plan_path.exists():
            raise StateError(
                f".plan not created by write_plan effect at {plan_path}"
            )
        current = read_state(plan_path)
        if current != result.new_state:
            raise StateError(
                f"Expected '{result.new_state}' after scaffold, got '{current}'"
            )
    else:
        current = read_state(plan_path)
        if current != result.from_state:
            raise ConcurrentModification(
                expected=result.from_state, actual=current or 'None'
            )
        if result.new_state != 'idle':
            write_state(plan_path, result.new_state)

    if result.new_state == 'drained' and plan_path.exists():
        write_branch(plan_path, 'main')

    emit_metadata = dict(metadata) if metadata else {}
    if evidence is not None:
        emit_metadata['evidence'] = evidence

    if repo_path:
        _emit_to_worklog(plan_path, result, repo_path, emit_metadata or None)

    if result.new_state == 'idle' and result.from_state != 'idle':
        plan_path.unlink(missing_ok=True)


_DEFAULT_EXCLUDES = [
    '.idea/', 'target/', 'build/', 'node_modules/',
    '__pycache__/', '*.iml', '.worktrees/', 'slots/',
    '.pytest_cache/', '*.pyc', 'design/', '.claude/',
]


def validate_state(
    state: str,
    project: Path,
    workspace: Path,
    exclude_patterns: Optional[list[str]] = None,
) -> list[str]:
    """Check hygiene invariants. Returns list of violations (empty = clean)."""
    import subprocess as _sp

    violations: list[str] = []
    excludes = exclude_patterns or _DEFAULT_EXCLUDES

    if state not in ('paused', 'idle'):
        _check_untracked(project, excludes, violations, "project")
        if project.resolve() != workspace.resolve():
            _check_untracked(workspace, excludes, violations, "workspace")

    if state not in ('idle', 'paused'):
        plan_base = workspace if project.resolve() != workspace.resolve() else project
        plan_path = plan_base / ".plan"
        if not plan_path.exists():
            plan_path = plan_base / "design" / ".plan"
        if plan_path.exists():
            meta_branch = _read_branch(plan_path)
            if meta_branch:
                current = _sp.run(
                    ["git", "-C", str(project), "branch", "--show-current"],
                    capture_output=True, text=True,
                ).stdout.strip()
                if current and current != meta_branch:
                    violations.append(
                        f"Branch mismatch: .plan says '{meta_branch}', "
                        f"git says '{current}'"
                    )

    if state == 'closing:review':
        for repo, label in [(project, "project"), (workspace, "workspace")]:
            if repo.resolve() == workspace.resolve() and label == "workspace":
                continue
            status = _sp.run(
                ["git", "-C", str(repo), "status", "--porcelain"],
                capture_output=True, text=True,
            ).stdout.strip()
            if status:
                violations.append(f"Uncommitted changes in {label}")

    return violations


def _check_untracked(
    repo: Path, excludes: list[str], violations: list[str], label: str,
) -> None:
    import subprocess as _sp

    result = _sp.run(
        ["git", "-C", str(repo), "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True,
    )
    for f in result.stdout.strip().splitlines():
        if f and not any(_matches_exclude(f, pat) for pat in excludes):
            violations.append(f"Untracked file in {label}: {f}")


def _matches_exclude(filepath: str, pattern: str) -> bool:
    if pattern.endswith('/'):
        bare = pattern.rstrip('/')
        return filepath.startswith(pattern) or filepath == bare or f'/{pattern}' in filepath
    if pattern.startswith('*.'):
        return filepath.endswith(pattern[1:])
    return pattern in filepath


def is_transient(state: str) -> bool:
    return state in TRANSIENT_STATES


def is_closing(state: str) -> bool:
    return state in CLOSING_STATES


class ClosureState(Enum):
    CLOSED = "closed"
    MERGED_UNSTAMPED = "merged_unstamped"
    STAMPED_UNMERGED = "stamped_unmerged"
    OPEN = "open"
    DELETED = "deleted"


_CLOSURE_PRIORITY = [
    ClosureState.CLOSED,
    ClosureState.MERGED_UNSTAMPED,
    ClosureState.OPEN,
    ClosureState.STAMPED_UNMERGED,
    ClosureState.DELETED,
]


def is_closed(
    project: str,
    branch: str,
    workspace: str | None = None,
    base_branch: str = "main",
) -> ClosureState:
    """Single predicate answering 'is this branch done?'

    All checks are local git, sub-second. Returns the worst state
    across project and workspace (if provided).
    """

    def _check_repo(repo_path: str, branch_name: str) -> ClosureState:
        exists = _sp.run(
            ["git", "-C", repo_path, "branch", "--list", branch_name],
            capture_output=True, text=True, timeout=10,
        )
        if not exists.stdout.strip():
            return ClosureState.DELETED

        ahead = _sp.run(
            ["git", "-C", repo_path, "log", "--oneline",
             f"{base_branch}..{branch_name}"],
            capture_output=True, text=True, timeout=10,
        )
        non_stamp_commits = []
        if ahead.stdout.strip():
            for line in ahead.stdout.strip().splitlines():
                parts = line.split(" ", 1)
                if len(parts) > 1 and parts[1].startswith("chore: branch closed"):
                    continue
                non_stamp_commits.append(line)

        last_commit = _sp.run(
            ["git", "-C", repo_path, "log", "-1", "--format=%s", branch_name],
            capture_output=True, text=True, timeout=10,
        )
        is_stamped = last_commit.stdout.strip().startswith("chore: branch closed")

        merged = len(non_stamp_commits) == 0
        if merged and is_stamped:
            return ClosureState.CLOSED
        if merged and not is_stamped:
            return ClosureState.MERGED_UNSTAMPED
        if not merged and is_stamped:
            return ClosureState.STAMPED_UNMERGED
        return ClosureState.OPEN

    project_state = _check_repo(project, branch)

    if workspace is None:
        return project_state

    workspace_state = _check_repo(workspace, branch)

    if workspace_state == ClosureState.DELETED:
        return project_state

    return max(project_state, workspace_state,
               key=lambda s: _CLOSURE_PRIORITY.index(s))


def can_transition(from_state: str, event: str) -> bool:
    return (from_state, event) in TRANSITION_TABLE


def migrate_legacy_paused(meta_path: Path) -> bool:
    """Migrate legacy paused branch .meta: write state: paused if field missing.
    Called by work_resume flow after checkout, before transition().
    Returns True if migration was performed."""
    if not meta_path.exists():
        return False
    content = meta_path.read_text()
    has_state_field = any(
        line.startswith('state:') for line in content.splitlines()
    )
    if has_state_field:
        return False
    write_state(meta_path, 'paused')
    return True



def _parse_cli_args(argv: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for arg in argv:
        if "=" in arg:
            k, _, v = arg.partition("=")
            result[k] = v
    return result


def main() -> int:
    if len(sys.argv) < 2:
        print("ERROR=MISSING_SUBCOMMAND")
        print("Usage: lifecycle.py <transition|commit-transition|read-state> ...")
        return 1

    cmd = sys.argv[1]

    if cmd == "show-transitions":
        if len(sys.argv) < 3:
            print("ERROR=MISSING_ARGS")
            return 1
        plan_path = Path(sys.argv[2])
        state = read_state(plan_path) or "idle"
        valid = sorted(ev for (st, ev) in TRANSITION_TABLE if st == state)
        print(f"STATE={state}")
        print(f"VALID_EVENTS={",".join(valid)}")
        return 0

    if cmd == "read-state":
        if len(sys.argv) < 3:
            print("ERROR=MISSING_ARGS")
            return 1
        plan_path = Path(sys.argv[2])
        state = read_state(plan_path) or "idle"
        print(f"STATE={state}")
        return 0

    if cmd == "transition":
        if len(sys.argv) < 4:
            print("ERROR=MISSING_ARGS")
            print("Usage: lifecycle.py transition <plan_path> <event> [project=<p>] [workspace=<w>]")
            return 1
        plan_path = Path(sys.argv[2])
        event = sys.argv[3]
        opts = _parse_cli_args(sys.argv[4:])
        project = Path(opts["project"]) if "project" in opts else None
        workspace = Path(opts["workspace"]) if "workspace" in opts else None
        try:
            result = transition(plan_path, event, project=project, workspace=workspace)
        except InvalidTransition as e:
            print(f"ERROR=INVALID_TRANSITION")
            print(f"FROM_STATE={e.from_state}")
            print(f"EVENT={e.event}")
            print(f"DETAIL={e}")
            return 1
        except InvalidState as e:
            print(f"ERROR=INVALID_STATE")
            print(f"STATE={e.state}")
            print(f"VIOLATIONS={";".join(e.violations)}")
            return 1
        print(f"FROM_STATE={result.from_state}")
        print(f"NEW_STATE={result.new_state}")
        print(f"EVENT={result.event}")
        print(f"EFFECTS={",".join(result.effects)}")
        print(f"POST_COMMIT_EFFECTS={",".join(result.post_commit_effects)}")
        return 0

    if cmd == "commit-transition":
        if len(sys.argv) < 3:
            print("ERROR=MISSING_ARGS")
            return 1
        plan_path = Path(sys.argv[2])
        opts = _parse_cli_args(sys.argv[3:])
        from_state = opts.get("from_state", "")
        new_state = opts.get("new_state", "")
        event = opts.get("event", "")
        repo_path = opts.get("repo_path")
        evidence_json = opts.get("evidence")
        if not from_state or not new_state or not event:
            print("ERROR=MISSING_ARGS")
            print("Required: from_state=, new_state=, event=")
            return 1
        result = TransitionResult(
            from_state=from_state,
            new_state=new_state,
            event=event,
        )
        import json as _json
        evidence = _json.loads(evidence_json) if evidence_json else None
        try:
            commit_transition(plan_path, result, repo_path=repo_path,
                              evidence=evidence)
        except ConcurrentModification as e:
            print(f"ERROR=CONCURRENT_MODIFICATION")
            print(f"EXPECTED={e.expected}")
            print(f"ACTUAL={e.actual}")
            return 1
        except StateError as e:
            print(f"ERROR=STATE_ERROR")
            print(f"DETAIL={e}")
            return 1
        except MissingEvidence as e:
            print(f"ERROR=MISSING_EVIDENCE")
            print(f"EVENT={e.event}")
            print(f"REQUIRED_KEYS={','.join(e.required_keys)}")
            return 1
        except InvalidEvidence as e:
            print(f"ERROR=INVALID_EVIDENCE")
            print(f"EVENT={e.event}")
            print(f"VIOLATIONS={';'.join(e.violations)}")
            return 1
        print("COMMITTED=yes")
        print(f"STATE={new_state}")
        return 0

    print(f"ERROR=UNKNOWN_COMMAND")
    print(f"DETAIL={cmd}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
