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
from pathlib import Path
from typing import Optional

VALID_STATES = frozenset({
    'idle', 'scaffolded', 'active', 'transitioning', 'paused',
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


# --- Transition table ---

# (from_state, event): (new_state, effects, post_commit_effects)
TRANSITION_TABLE: dict[tuple[str, str], tuple[str, list[str], list[str]]] = {
    # Core lifecycle
    ('idle', 'work'):                  ('scaffolded',       ['create_branch', 'write_meta', 'build_plan'],                             []),
    ('idle', 'slot_create'):           ('scaffolded',       ['create_slot', 'write_meta', 'build_plan'],                               []),
    ('scaffolded', 'auto_setup'):      ('active',           ['garden_search', 'load_specs', 'check_protocols', 'check_intellij'],      []),
    ('active', 'work_next'):           ('transitioning',    ['advance_issue', 'update_meta', 'tick_github'],                           []),
    ('transitioning', 'auto_refresh'): ('active',           ['garden_search', 'load_specs', 'check_protocols'],                        []),
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
    # Abort (pre-artifact only)
    ('closing:review', 'abort_close'):       ('active',            ['clear_closing_markers'],                                           []),
    ('closing:verified', 'abort_close'):     ('active',            ['clear_closing_markers'],                                           []),
}

INVALID_MESSAGES: dict[tuple[str, str], str] = {
    ('idle', 'work_next'):      "Cannot advance — no active branch. Start work first.",
    ('idle', 'work_pause'):     "Cannot pause — no active branch.",
    ('idle', 'work_end'):       "Cannot close — no active branch. You're on main.",
    ('idle', 'work_resume'):    "Cannot resume — pause stack is empty.",
    ('scaffolded', 'work_next'): "Branch not yet active — context setup must complete first.",
    ('scaffolded', 'work_end'):  "Cannot close — branch hasn't been activated yet.",
    ('scaffolded', 'work_pause'): "Cannot pause — branch hasn't been activated yet.",
    ('active', 'work'):         "Already on an active branch. Use `work end`, `work pause`, or `work next`.",
    ('active', 'work_resume'):  "Branch is active, not paused. Nothing to resume.",
    ('transitioning', 'work_end'):   "Issue transition in progress — context refresh must complete first.",
    ('transitioning', 'work_pause'): "Issue transition in progress — wait for context refresh.",
    ('paused', 'work_end'):     "Cannot close a paused branch. Resume it first, then close.",
    ('paused', 'work_next'):    "Cannot advance — branch is paused. Resume first.",
    ('paused', 'work_pause'):   "Branch is already paused.",
    ('closing:promoted', 'abort_close'): "Cannot abort — artifacts already workspace-promoted and project-promoted. Continue forward.",
    ('closing:pushed', 'abort_close'):   "Cannot abort — artifacts already workspace-promoted and project-promoted. Branch pushed — continue forward.",
    ('closing:merged', 'abort_close'):   "Cannot abort — content already merged to main. Continue forward.",
    ('closing:stamped', 'abort_close'):  "Cannot abort — branch already stamped. Only cleanup remains.",
}


# --- Public API ---


def read_state(meta_path: Path) -> Optional[str]:
    """Read lifecycle state from .meta. Returns None if no .meta exists.
    Raises CorruptedState if state: field has unrecognised value."""
    if not meta_path.exists():
        return None
    content = meta_path.read_text()
    for line in content.splitlines():
        if line.startswith('state:'):
            raw = line.split(':', 1)[1].strip()
            if raw in VALID_STATES:
                return raw
            raise CorruptedState(meta_path, raw)
    return 'active'


def write_state(meta_path: Path, state: str) -> None:
    """Write lifecycle state to existing .meta atomically."""
    content = meta_path.read_text()
    lines = content.splitlines()

    state_line_idx = None
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

    tmp_path = meta_path.parent / '.meta.tmp'
    tmp_path.write_text('\n'.join(lines) + '\n')
    tmp_path.replace(meta_path)


def transition(
    meta_path: Path,
    event: str,
    project: Optional[Path] = None,
    workspace: Optional[Path] = None,
) -> TransitionResult:
    """Phase 1: Validate transition and return result. Does NOT write state."""
    raw_state = read_state(meta_path)
    current_state = raw_state or 'idle'

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


def commit_transition(meta_path: Path, result: TransitionResult) -> None:
    """Phase 2: Verify state unchanged, write atomically, emit worklog."""
    if result.from_state == 'idle':
        if not meta_path.exists():
            raise StateError(
                f".meta not created by write_meta effect at {meta_path}"
            )
        current = read_state(meta_path)
        if current != result.new_state:
            raise StateError(
                f"Expected '{result.new_state}' after scaffold, got '{current}'"
            )
    else:
        current = read_state(meta_path)
        if current != result.from_state:
            raise ConcurrentModification(
                expected=result.from_state, actual=current or 'None'
            )
        if result.new_state != 'idle':
            write_state(meta_path, result.new_state)


_DEFAULT_EXCLUDES = [
    '.idea/', 'target/', 'build/', 'node_modules/',
    '__pycache__/', '*.iml', '.worktrees/', 'slots/',
    '.pytest_cache/', '*.pyc', 'design/',
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
        meta_path = (
            workspace if project.resolve() != workspace.resolve() else project
        ) / "design" / ".meta"
        if meta_path.exists():
            meta_branch = ""
            for line in meta_path.read_text().splitlines():
                if line.startswith("branch:"):
                    meta_branch = line.split(":", 1)[1].strip()
                    break
            if meta_branch:
                current = _sp.run(
                    ["git", "-C", str(project), "branch", "--show-current"],
                    capture_output=True, text=True,
                ).stdout.strip()
                if current and current != meta_branch:
                    violations.append(
                        f"Branch mismatch: .meta says '{meta_branch}', "
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
        return filepath.startswith(pattern) or f'/{pattern}' in filepath
    if pattern.startswith('*.'):
        return filepath.endswith(pattern[1:])
    return pattern in filepath


def is_transient(state: str) -> bool:
    return state in TRANSIENT_STATES


def is_closing(state: str) -> bool:
    return state in CLOSING_STATES


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
