# Soredium TUI — Design Spec

**Issue:** #222 — REPL shell for mechanical lifecycle operations
**Branch:** issue-222-repl-shell
**Date:** 2026-08-11
**Scope:** Python Textual app (this issue); Java/Tamboui port is follow-on

## Overview

A Textual-based terminal application that exposes the soredium work/slot
lifecycle as a guided, panel-based interface. Runs without an LLM for all
mechanical operations (start, next, end, pause, resume, brief, what-next).
Optionally hands off to a pluggable LLM CLI for reasoning work (sweeps,
reviews, narrative, implementation).

The Python app is a stepping stone — the long-term target is a Quarkus
native CLI built on Tamboui. Both runtimes share the same architecture:
event-driven command layer, panel-based TUI, pluggable session provider.

## Architecture

Three layers. The command layer is the portable core — everything above
and below it changes between Python and Java. The Session SPI is a
TUI-owned adapter, not a separate architectural layer.

```
┌─────────────────────────────────┐
│  TUI (Textual / Tamboui)        │  tui/python/  tui/java/ (follow-on)
│  Panels, action list, events    │
│  SessionProvider (adapter)      │  Suspend / Automated / Embedded
├─────────────────────────────────┤
│  Command Layer (event-driven)   │  Portable orchestration
│  start(), next(), end(), etc.   │  Lifecycle state machine executor
├─────────────────────────────────┤
│  Script Layer (existing)        │  project/, work-start/, work-end/,
│  Refactored for library import  │  work-slot/, work-pause/, etc.
└─────────────────────────────────┘
```

**TUI** — Textual widget tree (Python) or Tamboui toolkit (Java).
Subscribes to events from the command layer. Renders panels. Handles
keyboard/mouse input. Never calls scripts directly. Owns the
SessionProvider adapter for LLM CLI handoff — suspends, launches the
configured CLI, resumes, then asks the command layer to refresh state.

**Command Layer** — orchestrates script calls by executing lifecycle
transitions, emits typed events. Language-agnostic concepts
(BranchCreated, PlanAdvanced, WorkEnded). This is what gets ported to
Java. The command layer is the effect executor for the lifecycle state
machine (see § Lifecycle Integration below).

**Script Layer** — existing Python scripts refactored with library APIs.
CLI entry points preserved for backward compatibility with Claude Code
skills. Java port reimplements this layer natively.

### Lifecycle Integration

The command layer is the effect executor for `lifecycle.py`'s state
machine. The lifecycle TRANSITION_TABLE is the single source of truth
for valid transitions and their effects. Every state-changing command
follows the three-phase commit protocol:

1. `lifecycle.transition(meta_path, event)` — validate, return `TransitionResult`
2. Execute effects listed in `TransitionResult.effects` by calling script library functions
3. `lifecycle.commit_transition(meta_path, result)` — verify state unchanged, write atomically
4. Execute `TransitionResult.post_commit_effects` (branch switches, stack operations)

The command layer maps every abstract effect name from the transition
table to a concrete action. This table is exhaustive — every effect
in `TRANSITION_TABLE` appears here. Effects marked "no-op (LLM-only)"
are context-loading or narrative operations that require an LLM
session; the command layer fires the transition to advance state but
skips execution of these effects.

| Effect | Phase | Script call |
|--------|-------|------------|
| `create_branch` | effect | `branch_create.create_branches()` |
| `create_slot` | effect | `slot_manager.create_slot()` |
| `write_meta` | effect | `scaffold.scaffold()` |
| `build_plan` | effect | `plan_manager.create_main_plan()` |
| `garden_search` | effect | no-op (LLM-only) |
| `load_specs` | effect | no-op (LLM-only) |
| `check_protocols` | effect | no-op (LLM-only) |
| `check_intellij` | effect | no-op (LLM-only) |
| `advance_issue` | effect | `plan_manager.advance()` |
| `update_meta` | effect | `scaffold.update_meta()` |
| `tick_github` | effect | `plan_manager.tick_github()` |
| `wip_commit` | effect | `pause_exec.commit_wip()` |
| `pop_stack` | effect | `stack.pop_entry()` |
| `reset_wip` | effect | `resume_exec.reset_wip()` |
| `context_resume` | effect | no-op (LLM-only) |
| `pre_close_sweep` | effect | no-op (LLM-only) |
| `record_review` | effect | no-op (LLM-only) |
| `write_promotion_stamp` | effect | `close_artifacts.close()` |
| `verify_content_landed` | effect | `verify_promotion.verify()` |
| `write_stamp` | effect | `land_branch.stamp()` |
| `write_plan_closed` | effect | `plan_manager.close()` |
| `clear_closing_markers` | effect | `close_artifacts.clear_markers()` |
| `switch_to_main` | post_commit | `git checkout main` (direct) |
| `push_stack` | post_commit | `pause_exec.push_and_stack()` |
| `return_to_main` | post_commit | `branch_cleanup.cleanup()` |
| `write_handoff` | post_commit | no-op (LLM-only) |

**Multi-step commands.** The `end` command fires sequential lifecycle
transitions through the closing substates: `work_end` →
`review_pass` → `promote_pass` → `push_pass` → `merge_pass` →
`stamp_pass` → `cleanup_pass`. Each transition follows the three-phase
protocol. `StepProgress` events are emitted between transitions.

**Closing operation mapping.** The `end` command performs git operations
between lifecycle transitions. The lifecycle state names track logical
phases, not git operations — `push_pass` fires after the local
ff-only merge (branch content "pushed" to local main), and
`merge_pass` fires after the remote push (content "merged" into
remote main):

| Lifecycle transition | Command-layer operation | Script call |
|---------------------|------------------------|-------------|
| `work_end` → `closing:review` | _(no-op: pre_close_sweep)_ | — |
| `review_pass` → `closing:verified` | _(no-op: record_review)_ | — |
| `promote_pass` → `closing:promoted` | Promote artifacts | `close_artifacts.close()` |
| _(between transitions)_ | Rebase onto base branch | `work_end_execute.rebase()` |
| _(between transitions)_ | FF-only merge branch into local main | `work_end_execute.merge_to_main()` |
| `push_pass` → `closing:pushed` | _(state marker — no effects)_ | — |
| _(between transitions)_ | Push main to remote (3 retries) | `work_end_execute.push_to_remote()` |
| `merge_pass` → `closing:merged` | Verify content on remote | `verify_promotion.verify()` |
| `stamp_pass` → `closing:stamped` | Stamp branch | `land_branch.stamp()` |
| _(between transitions)_ | Handle workspace branch | `work_end_execute.handle_workspace()` |
| `cleanup_pass` → `idle` | Close plan, return to main | `plan_manager.close()`, `branch_cleanup.cleanup()` |

The lifecycle state is the single source of truth for crash recovery
during closing. If the TUI crashes mid-sequence, restart reads the
lifecycle state and resumes from the corresponding transition.
`.execute-progress` is used internally by `push_to_remote()` for
retry tracking only — it does not duplicate the lifecycle's
high-level progress.

**Transient states.** `scaffolded` and `transitioning` are auto-fired
by the command layer — the user never sees these states. When `start`
reaches `scaffolded`, the command layer immediately fires `auto_setup`
to reach `active`. When `next` reaches `transitioning`, the command
layer immediately fires `auto_refresh`. Both auto-transitions emit
`StepProgress` events for their effects.

### Action Derivation

The command layer owns the mapping from lifecycle state to available
actions. After every state change, it computes `available_actions` and
`suggested_action` based on the lifecycle TRANSITION_TABLE and includes
them in the `StateChanged` event. The TUI renders whatever the command
layer provides — it has no independent derivation logic.

| State | Available actions | Suggested |
|-------|-------------------|-----------|
| `idle` (no stack) | start, quick-fix, what-next, status | start |
| `idle` (stack > 0) | start, quick-fix, resume, what-next, status | resume |
| `active` (has queue) | continue, brief, next, pause, end, session, status | next |
| `active` (no queue) | continue, brief, pause, end, session, status | end |
| `paused` | resume, start, what-next, status | resume |
| `closing:review` | abort, status | abort |
| `closing:verified` | abort, status | abort |
| `closing:promoted` | status | _(auto-continues)_ |
| `closing:pushed` | status | _(auto-continues)_ |
| `closing:merged` | status | _(auto-continues)_ |
| `closing:stamped` | status | _(auto-continues)_ |

`scaffolded` and `transitioning` are never surfaced — the command
layer auto-fires through them before emitting `StateChanged`.
`abort` maps to the lifecycle's `abort_close` transition, available
only in `closing:review` and `closing:verified` (before artifacts
are promoted).

## Directory Structure

```
soredium/
  commands/                  # Portable command layer — TUI and CLI both import this
    __init__.py              # Command registry + refresh()
    events.py                # All typed event dataclasses
    start.py                 # start #N [#M ...]
    next.py                  # advance plan
    end.py                   # mechanical close
    pause.py                 # WIP commit + stack push
    resume.py                # stack pop + rebase
    continue_.py             # keep working on current branch
    brief.py                 # context summary
    quick_fix.py             # ephemeral branch landing
    what_next.py             # enrichment recommendations
    status.py                # full context dump
  tui/
    python/
      __main__.py            # Entry point: python -m tui.python (TUI mode)
      app.py                 # Textual App subclass
      ui/
        home.py              # Home View — repo/slot list with session status
        header.py            # Branch, state, queue position (Project View)
        action_panel.py      # Context-sensitive action list (Project View)
        content.py           # Scrollable output area (Project View)
        footer.py            # Keybinding hints (both views)
        modals.py            # Input overlays (issue numbers, messages)
      session/
        __init__.py          # SessionProvider protocol
        suspend.py           # Suspend TUI, run CLI inline
        tmux.py              # Default: tmux-managed background sessions
      styles/
        app.tcss             # Textual CSS
    java/                    # Follow-on issue (empty for now)
  cli/
    __main__.py              # Entry point: python -m cli (stateless CLI mode)
  project/                   # Existing — refactored for import
  work-start/                # Existing — refactored for import
  work-end/                  # Existing — refactored for import
  work-slot/                 # Existing — refactored for import
  work-pause/                # Existing — refactored for import
  work-resume/               # Existing — refactored for import
  quick-fix/                 # Existing — refactored for import
  scripts/                   # Existing — enrichment.py etc.
```

The command layer is physically separate from the TUI — both `tui/python/`
and `cli/` import from `commands/`. The Java port reimplements `commands/`
natively; neither Python package ships to Java.

## Event Model

Commands emit typed dataclass events. The TUI subscribes and updates
panels. Events are the contract between command and UI layers.

```python
from dataclasses import dataclass

# State management
@dataclass
class StateChanged:
    old_state: str
    new_state: str
    available_actions: list[str]
    suggested_action: str | None

# Command results
@dataclass
class HealthCheck:
    check: str                   # "meta_consistency", "pause_stack", etc.
    status: str                  # "ok", "warn", "error", "fix"
    detail: str | None           # Human-readable detail when status != ok

@dataclass
class BriefReady:
    issue: int | None
    branch: str
    state: str
    queue_position: str | None   # "1/3"
    health: list[HealthCheck]
    is_epic: bool
    epic_batch: str | None       # "2 of 4"
    epic_active_issue: int | None

@dataclass
class BranchCreated:
    branch: str
    issues: list[int]
    plan_path: str | None

@dataclass
class PlanAdvanced:
    completed_issue: int
    next_issue: int | None
    next_title: str | None
    position: str               # "2/3"
    queue_complete: bool

@dataclass
class WorkEnded:
    branch: str
    issues_closed: list[int]

@dataclass
class WipCommitted:
    repo: str
    message: str

@dataclass
class Paused:
    branch: str
    stack_depth: int

@dataclass
class Resumed:
    branch: str
    rebased: bool

@dataclass
class QuickFixLanded:
    branch: str
    message: str

@dataclass
class Recommendation:
    issue: int
    title: str
    strategic_role: str | None   # "quick-win", "load-bearing", etc.
    readiness: str | None        # "ready", "needs-design", etc.
    reason: str | None

@dataclass
class WhatNextReady:
    recommendations: list[Recommendation]

@dataclass
class StatusReady:
    branch: str
    state: str
    on_main: bool
    in_slot: bool
    has_plan: bool
    plan_position: str | None    # "2/3"
    stack_depth: int
    owner_repo: str | None
    base_branch: str

@dataclass
class ContinueReady:
    issue: int | None
    branch: str
    state: str
    handoff_summary: str | None  # Last Session narrative, if HANDOFF.md present
    done_detected: bool          # True if active plan issue is complete
    suggest_next: bool           # True if queue has remaining items
    suggest_end: bool            # True if queue is exhausted

@dataclass
class CommandFailed:
    command: str                 # "end", "start", "resume", etc.
    step: str | None             # For multi-step commands: which step failed
    error: str                   # Machine-readable error code
    detail: str                  # Human-readable message
    recoverable: bool            # True if retry or abort is possible

# Multi-step progress
@dataclass
class StepProgress:
    command: str                # "end", "start"
    step: str                   # "promoted", "rebased", "pushed", "stamped"
    detail: str | None


```

Every state-changing command emits `StateChanged` as its final event.
`StateChanged.available_actions` drives the action panel.
`StateChanged.suggested_action` highlights the recommended next step.

Informational commands (`brief`, `continue`, `what-next`, `status`) do
NOT emit `StateChanged` — they read state without changing it. The
`continue` command fires `work_continue` as a precondition check
(validates the branch is `active`) but does not call
`commit_transition` — the lifecycle state is unchanged.

Multi-step commands (end, start) emit `StepProgress` events as each
step completes — the content panel updates in real time.

When any command fails, the command layer emits `CommandFailed`.
For multi-step commands, `CommandFailed.step` identifies where the
failure occurred. The TUI uses `recoverable` to decide whether to
offer retry/abort or just display the error.

## Navigation Model

The TUI has two views: **Home View** (workspace manager) and
**Project View** (lifecycle operations). The Home View is the entry
point — run `soredium`, see all repos and slots, pick where to work.

### Home View

```
┌─ soredium ────────────────────────────────────────┐
│ Repos & Slots                                      │
│                                                    │
│ > casehub/engine        [main] idle            ○   │
│   casehub/platform      [issue-180] active     ●   │
│   hortora/soredium      slot/7  [issue-222]    ●   │
│   hortora/soredium      slot/3  [issue-198]    ◐   │
│   hortora/engine        [main] idle            ○   │
│                                                    │
├────────────────────────────────────────────────────┤
│ ↑↓ select  Enter open  s new session  q quit       │
│ ● running  ◐ paused  ○ idle                        │
└────────────────────────────────────────────────────┘
```

Each row shows: repo name, slot (if any), branch, lifecycle state,
and tmux session status indicator. Arrow keys to navigate, Enter to
open the Project View for that repo/slot. Escape from Project View
returns to Home View.

**Discovery.** The Home View discovers repos and slots by scanning
configured paths. Default: `~/claude/` (recursive scan for directories
containing `.git` and `CLAUDE.md`). Override via config:

```toml
# ~/.soredium/config.toml
[workspace]
scan_paths = ["~/claude/", "~/projects/"]
```

Slot directories are detected via `.slot` marker files (same detection
as `topology.py`). Each discovered repo/slot gets a context resolution
via `ctx.resolve()` to populate branch, state, and plan info.

**Context switching.** When the user enters a repo/slot, the TUI sets
the active context (project path, workspace path) and switches to the
Project View. All command layer calls use the active context. When the
user returns to Home View, the active context is cleared and the
repo/slot list is refreshed.

### Tmux Session Management

The Home View shows tmux session status for each repo/slot. Sessions
are created when the user selects `session` from the Project View —
the TUI creates a named tmux session instead of (or in addition to)
the suspend/resume flow.

**Session lifecycle:**

1. **Create** — user selects `session` in Project View. The
   `TmuxProvider` creates a named session:
   `tmux new-session -d -s soredium-<repo>-<slot> <cli_command>`
   with cwd set to the project path.
2. **Attach** — from Home View, Enter on a row with ● attaches to
   the tmux session. TUI suspends, tmux takes over.
3. **Detach** — user presses `Ctrl-b d` (tmux default). TUI resumes,
   refreshes state for that repo/slot.
4. **Kill** — from Home View, `k` on a row with ● kills the tmux
   session after confirmation.
5. **Status** — the Home View polls `tmux has-session -t <name>` on
   refresh to detect session state.

**TmuxProvider** — a SessionProvider implementation alongside
SuspendingProvider:

```python
class TmuxProvider:
    """Manage LLM CLI sessions via tmux."""

    def __init__(self, cli_command: str = "claude"):
        self.cli_command = cli_command
        self._session_name: str | None = None

    def session_name(self, context: IssueContext) -> str:
        repo = context.project_path.split("/")[-1]
        return f"soredium-{repo}-{context.issue or 'main'}"

    async def start(self, context: IssueContext) -> None:
        self._session_name = self.session_name(context)
        subprocess.run([
            "tmux", "new-session", "-d",
            "-s", self._session_name,
            "-c", context.project_path,
            self.cli_command,
        ])

    def is_active(self) -> bool:
        if not self._session_name:
            return False
        result = subprocess.run(
            ["tmux", "has-session", "-t", self._session_name],
            capture_output=True,
        )
        return result.returncode == 0

    async def stop(self) -> None:
        if self._session_name:
            subprocess.run(["tmux", "kill-session", "-t", self._session_name])
            self._session_name = None
```

**Attach from Home View** — when the user selects a row with an active
tmux session, the TUI suspends and attaches:
```python
async def attach_session(self, session_name: str):
    with self.suspend():
        subprocess.run(["tmux", "attach-session", "-t", session_name])
    # On return: refresh all repo/slot states
    await self.refresh_home()
```

**Session provider selection.** The config determines which provider
is used:

```toml
# ~/.soredium/config.toml
[session]
provider = "tmux"       # "tmux" (default) or "suspend"
cli = "claude"
```

`tmux` provider creates persistent background sessions visible from
the Home View. `suspend` provider (the original design) suspends the
TUI inline — no Home View session tracking.

### Home View Events

```python
@dataclass
class RepoSlotInfo:
    repo: str                    # "casehub/engine"
    slot: str | None             # "slot/7" or None
    branch: str                  # "issue-222-repl-shell"
    state: str                   # "active", "idle", "paused", etc.
    issue: int | None
    plan_position: str | None    # "1/3"
    tmux_session: str | None     # tmux session name if active
    project_path: str
    workspace_path: str | None

@dataclass
class HomeReady:
    repos: list[RepoSlotInfo]

@dataclass
class ContextSwitched:
    repo: str
    slot: str | None
    project_path: str
    workspace_path: str | None
```

`HomeReady` is emitted on startup and after returning from Project
View. `ContextSwitched` is emitted when the user enters a repo/slot.

## UI Layout — Project View

Four persistent zones:

```
┌─ Header ──────────────────────────────────────────┐
│ soredium   [issue-42] active   Queue: 1/3         │
├────────────┬──────────────────────────────────────-┤
│ Actions    │ Content                               │
│            │                                       │
│ > brief    │ (output from selected/last action)    │
│   next     │                                       │
│   pause    │                                       │
│   end      │                                       │
│   session  │                                       │
│   status   │                                       │
│            │                                       │
├────────────┴──────────────────────────────────────-┤
│ ↑↓ select  Enter run  ? help  q quit              │
└───────────────────────────────────────────────────-┘
```

**Header** — always visible. Branch, lifecycle state, plan position.
Updates reactively on `StateChanged`.

**Action Panel** (left) — valid actions for the current state.
Arrow keys to navigate, Enter to run. Mouse click also works.
Derived from lifecycle state machine transitions + static commands.
Suggested next action is highlighted.

**Content** (right, scrollable) — output from the last action.
Brief shows issue/branch/health. End shows step-by-step progress.
What-next shows ranked recommendations.

**Footer** — keybinding hints. Context-sensitive.

### Command Execution Guard

While a command is running, the action panel is disabled — items are
visually dimmed and key/mouse input is rejected. The content panel
shows a progress indicator (spinner + step-by-step output for
multi-step commands). The footer switches to "Running...".
Commands are non-cancellable — operations are fast (git operations
complete in seconds) and partial cancellation would leave state
inconsistent. For the closing sequence, abort is available BEFORE
running `end` (via the `abort` action in `closing:review` and
`closing:verified`), but once `end` starts it runs to completion
or failure. When the command completes or fails, the action panel
re-enables with the updated state. This prevents double-execution:
pressing Enter twice on `end` cannot spawn concurrent close sequences.

### Bootstrap Sequence

On startup, the TUI runs a deterministic initialisation before accepting
user input:

1. Resolve topology — call `topology.resolve()` for project/workspace paths
2. Detect work state — call `work_state.detect(topo)` for routing, plan, stack
3. Read lifecycle state — call `lifecycle.read_state(meta_path)` (None → idle)
4. Check recovery markers — scan for `.pausing`, `.resuming`, `.execute-progress`
5. Derive initial available actions:
   - If recovery markers present: override actions with recovery options
     (`.pausing` → "Continue pause"; `.resuming` → "Continue resume";
     `.execute-progress` → "Continue closing")
   - Otherwise: derive from lifecycle state (same logic as `StateChanged`)
6. Populate header (branch, state, queue position) from the detection results
7. Populate action panel from available actions; highlight suggested action
8. Content panel starts empty — displays a welcome line with branch/state summary

The bootstrap emits a synthetic `StateChanged` event internally (not from
a command) to drive the initial UI render. No command runs automatically —
the user chooses their first action from the panel.

### Action Panel Rendering

The action panel renders from `StateChanged.available_actions` — the
authoritative mapping is in § Architecture > Action Derivation.

The `end` command runs the full closing sequence automatically —
individual `closing:*` sub-states are not user-driven. The action
panel shows the current close step as a progress indicator.

Transient states (`scaffolded`, `transitioning`) auto-resolve via
lifecycle events (`auto_setup`, `auto_refresh`). The TUI shows a
progress indicator during these states.

### Input Modals

Actions that need input use modal overlays:
- `start` — issue number input (accepts `#42 #43 #44` or `42 43 44`)
- `quick-fix` — commit message input
- `resume` — branch picker (if multiple paused branches)

## Session SPI

Pluggable interface for LLM CLI handoff. The TUI doesn't know or care
which LLM or CLI is behind the SPI.

```python
from typing import Protocol
from dataclasses import dataclass

@dataclass
class IssueContext:
    issue: int
    title: str
    branch: str
    plan_position: str | None
    project_path: str
    workspace_path: str | None

class SessionProvider(Protocol):
    async def start(self, context: IssueContext) -> None: ...
    def is_active(self) -> bool: ...
    async def stop(self) -> None: ...
```

### Default Implementation: Suspend

```python
class SuspendingProvider:
    """Suspend TUI, launch configured CLI, resume on exit."""

    def __init__(self, cli_command: str = "claude"):
        self.cli_command = cli_command
        self._active = False

    async def start(self, context: IssueContext) -> None:
        self._active = True
        # TUI calls app.suspend() before this
        # Launch CLI with issue context via asyncio subprocess
        process = await asyncio.create_subprocess_exec(
            self.cli_command,
            "--system-prompt", f"Working on #{context.issue}: {context.title}",
            cwd=context.project_path,
        )
        await process.wait()
        self._active = False

    def is_active(self) -> bool:
        return self._active

    async def stop(self) -> None:
        self._active = False
```

After `start()` returns, the TUI calls the command layer's `refresh()`
to re-detect state and emit a fresh `StateChanged`. The CLI session may
have advanced the plan, closed the branch, or changed lifecycle state.
Re-detection sequence: re-read `.meta`, call `work_state.detect()`,
derive new available actions. The resulting `StateChanged` reflects
the post-session state. The command layer has no knowledge of session
providers — it just re-detects state on request.

Future implementations:
- **AutomatedProvider** — drives a third-party CLI via I/O (reading
  output, submitting prompts programmatically)
- **EmbeddedProvider** — native conversation panel inside the TUI

Configuration via environment or config file (precedence: env > config
file > default):
```
SOREDIUM_SESSION_CLI=claude          # default
SOREDIUM_SESSION_CLI=aider
SOREDIUM_SESSION_CLI=gemini
```

## Script Refactoring Pattern

Each script gets a library function alongside its CLI entry point.
The library function returns a typed result. The CLI entry point
calls the library function and prints KEY=value output.

```python
# Pattern for all refactored scripts

@dataclass
class ScaffoldResult:
    meta_path: str
    journal_path: str
    plan_path: str | None

def scaffold(workspace: Path, issue: int, branch: str,
             covers: list[int], **opts) -> ScaffoldResult:
    """Library API — called by command layer and CLI."""
    ...
    return ScaffoldResult(...)

def main() -> int:
    """CLI entry point — called by skills via python3 scaffold.py."""
    workspace = Path(sys.argv[1]).resolve()
    params = parse_args(sys.argv[2:])
    result = scaffold(workspace, **params)
    print(f"META_PATH={result.meta_path}")
    print(f"JOURNAL_PATH={result.journal_path}")
    ...
```

For scripts that need interactive decisions, use the `decide_fn`
callback pattern (garden entry GE-20260421-690e47):

```python
def land_branch(project: Path, branch: str,
                decide_fn: Callable[[str], bool] = None,
                **opts) -> LandResult:
    """Library API. decide_fn handles confirmations."""
    ...
    if needs_confirmation and decide_fn:
        if not decide_fn(f"Force push to {branch}?"):
            return LandResult(aborted=True)
    ...
```

**`decide_fn` bridging.** This is a deliberate callback-in-event-model
hybrid. Scripts call `decide_fn` synchronously; the TUI and CLI
provide different implementations:

- **TUI mode:** Commands run in Textual `Worker` threads. The
  command layer provides a `decide_fn` that calls
  `asyncio.run_coroutine_threadsafe()` to show a modal dialog on
  the Textual event loop, then blocks the worker thread until the
  user responds. The script is unaware of the async bridge.
- **CLI mode (interactive):** `decide_fn` prints the prompt to
  stderr and reads y/n from stdin.
- **CLI mode (non-interactive / `--yes`):** `decide_fn` is `None`.
  Scripts treat `None` as auto-approve (proceed without
  confirmation). The `--no-confirm` flag explicitly sets this.

**`decide_fn` rejection.** When `decide_fn` returns `False`, the
script returns an aborted result (e.g., `LandResult(aborted=True)`).
The command layer emits `CommandFailed` with `error="user_declined"`
and `recoverable=True`. Committed lifecycle transitions are NOT rolled
back — `decide_fn` runs during effect execution, so the lifecycle
state accurately reflects progress so far. The user can retry (the
closing sequence resumes from the current sub-state) or abort if in
`closing:review` / `closing:verified`. This is distinct from Esc
cancellation (blocked during execution) — `decide_fn` is a planned
decision point, not an escape hatch.

### Scripts to Refactor

| Script | Current API | Library API needed |
|--------|------------|-------------------|
| `project/ctx.py` | `resolve()` returns dict | Already importable — no change |
| `project/lifecycle.py` | `transition()` returns `TransitionResult` | Already importable — no change |
| `project/work_state.py` | `detect()` | Already importable — no change |
| `project/work_health.py` | `run_checks()` | Already importable — no change |
| `project/topology.py` | `resolve()` returns `Topology` | Already importable — no change |
| `project/stack.py` | `cmd_*()` via sys.argv, prints KEY=value | Expose `read_entries(path) -> list[StackEntry]`, `push_entry(path, entry) -> int`, `pop_entry(path, branch) -> tuple[bool, int]` — pure data functions without stdout |
| `work-start/scaffold.py` | `main()` via sys.argv | `scaffold(workspace, issue, branch, covers) -> ScaffoldResult` |
| `work-start/branch_create.py` | `main()` via sys.argv | `create(project, workspace, branch, issues) -> CreateResult` |
| `work-end/work_end_execute.py` | `cmd_promote()`, `cmd_rebase()`, `cmd_land()` via subcommands | Decompose `cmd_land`: `rebase(project, branch, base) -> RebaseResult`, `merge_to_main(project, branch, base) -> MergeResult`, `push_to_remote(project, base, max_retries=3) -> PushResult`, `handle_workspace(workspace, branch, base) -> WorkspaceResult`. Promotion handled by `close_artifacts.close()` (listed separately). |
| `work-end/close_artifacts.py` | subprocess call | `close(workspace, project, branch) -> CloseResult` |
| `work-end/land_branch.py` | `main()` via sys.argv | `rebase(project, branch, base) -> RebaseResult`, `push(project, branch) -> PushResult`, `stamp(project, branch, sha) -> StampResult` |
| `work-end/branch_cleanup.py` | `main()` via sys.argv | `cleanup(project, workspace, branch) -> CleanupResult` |
| `work-end/verify_promotion.py` | script call | `verify(workspace, project, branch) -> VerifyResult` |
| `work-pause/pause_exec.py` | `commit_wip()`, `push_and_stack()` | Already has callable functions — add typed results |
| `work-resume/resume_exec.py` | `checkout_branches()`, `rebase()` | Already has callable functions — add typed results |
| `work-slot/plan_manager.py` | parse/advance/detect | Already importable — add typed `AdvanceResult` (exists) |
| `work-slot/slot_manager.py` | `main()` via sys.argv (68KB) | Extract key functions with typed results |
| `quick-fix/quick_fix.py` | `run()` function | Already importable — add typed result |
| `scripts/enrichment.py` | argparse `main()` | `what_next(repo) -> list[Recommendation]` |

## Commands → Script Calls → Events

| Command | Script calls | Events emitted |
|---------|-------------|----------------|
| `brief` | `ctx.resolve()`, `work_health.run_checks()` | `BriefReady` |
| `continue` | `ctx.resolve()`, `work_health.run_checks()`, HANDOFF.md parse, `plan_manager.detect()` | `ContinueReady` |
| `start #N [#M]` | `branch_create.create_branches()`, `scaffold.scaffold()`, `plan_manager.create_main_plan()` | `StepProgress` × N, `BranchCreated`, `StateChanged` |
| `next` | `plan_manager.advance()`, `lifecycle.transition()` | `PlanAdvanced`, `StateChanged` |
| `end` | Sequential lifecycle transitions with: `close_artifacts.close()`, `work_end_execute.rebase()`, `work_end_execute.merge_to_main()`, `work_end_execute.push_to_remote()`, `land_branch.stamp()`, `work_end_execute.handle_workspace()`, `branch_cleanup.cleanup()` — see §Lifecycle Integration closing operation mapping | `StepProgress` × N, `WorkEnded`, `StateChanged` |
| `pause` | `pause_exec.write_intent()`, `pause_exec.commit_wip()`, `pause_exec.push_and_stack()`, `pause_exec.clear_intent()` | `WipCommitted`, `Paused`, `StateChanged` |
| `resume` | `resume_exec.write_intent()`, `stack.read_entries()`, `resume_exec.checkout_branches()`, `resume_exec.rebase()`, `resume_exec.reset_wip()`, `stack.pop_entry()`, `resume_exec.clear_intent()` | `Resumed`, `StateChanged` |
| `quick-fix` | `quick_fix.run()` | `QuickFixLanded`, `StateChanged` |
| `what-next` | `enrichment.what_next()` | `WhatNextReady` |
| `status` | `ctx.resolve()` | `StatusReady` |
| `abort` | `close_artifacts.clear_markers()` | `StateChanged` |
| `session` _(TUI action)_ | TUI suspends → `SessionProvider.start()` → TUI resumes → command layer `refresh()` | `StateChanged` |

Any command may emit `CommandFailed` instead of its success events if
an error occurs. For multi-step commands (`end`, `start`), partial
`StepProgress` events may precede the `CommandFailed`.

### Worklog Integration

The command layer centralizes worklog emission. When the command layer
calls `lifecycle.commit_transition()`, the lifecycle's built-in
`_emit_to_worklog()` fires automatically (it's part of the commit
protocol). Script library functions (the refactored APIs) do NOT emit
worklog events — only their CLI entry points do, for backward
compatibility with Claude Code skills. This avoids double-emission
when the command layer calls library functions that the lifecycle
also records.

`_emit_to_worklog()` is best-effort — failures are logged as warnings
but do not block lifecycle transitions. The `what-next` command depends
on worklog data indirectly: its primary inputs are the GitHub issue
cache (refreshed via `gh issue list`) and enrichment metadata
(strategic_role, readiness, decay). Worklog data feeds trajectory notes
and work-item state tracking, which affect recommendation scoring but
are not the sole input. A missed worklog emission degrades score quality
for affected issues but does not produce incorrect recommendations.

## Error Recovery

Two recovery mechanisms operate at different scopes, one for
multi-transition sequences and one for intra-transition sub-steps:

1. **Lifecycle sub-states** (closing) — the closing sequence uses
   sub-states (`closing:review` through `closing:stamped`) as
   durable progress markers. Each `end` step fires a lifecycle
   transition before performing its operation. If the process
   crashes, the lifecycle state records the last committed
   transition; restart resumes from there.

2. **Intent files** (pause, resume) — `pause` and `resume` each
   execute multiple sub-operations within a single lifecycle
   transition. Intent files (`.pausing`, `.resuming`) track
   sub-step progress. If the process crashes mid-pause, the
   intent file records which sub-steps completed.

These mechanisms are complementary, not competing. Lifecycle sub-states
track progress ACROSS transitions (closing has 7). Intent files track
progress WITHIN a single transition (pause has 4 sub-steps within
`active → paused`). They never overlap in scope.

**Precedence on startup:** intent file presence takes priority over
lifecycle state for action derivation. If `.pausing` exists, the
action panel shows "Continue pause" regardless of whether the lifecycle
reads `active` (crash before commit) or `paused` (crash after commit
but before post-commit effects completed).

### Progress Tracking (end)

The lifecycle state machine is the single source of truth for closing
progress. Each step of the `end` command fires a lifecycle transition
before performing the operation. If the TUI crashes mid-sequence, the
lifecycle state records which transition was last committed. On
restart, the `end` command reads the lifecycle state and resumes from
the corresponding transition — completed steps are skipped.

`.execute-progress` is NOT used for high-level closing progress.
It is retained internally by `push_to_remote()` only — to track
push retry attempts within that single operation. This avoids dual
progress tracking between lifecycle state and progress files.

### Intent Files (pause, resume)

`pause_exec.py` writes `.pausing` and `resume_exec.py` writes
`.resuming` before starting their sequences. Each step is marked
done as it completes. On TUI restart, the presence of an intent
file signals an interrupted operation.

Startup checks:
1. `.execute-progress` exists → offer "Continue closing" in action panel
2. `.pausing` exists → offer "Continue pause" (resume from last step)
3. `.resuming` exists → offer "Continue resume" (resume from last step)

### Resume Ordering

The `resume` command reads the stack entry without removing it (peek),
then checks out the branches, rebases, resets WIP, and only pops the
stack entry after all operations succeed. If checkout fails (branch
deleted), the stack entry is preserved — the user sees the error and
can choose to remove the entry manually or investigate.

### Failure Display

When a step fails, the content panel shows:
- Which steps completed (green checkmarks)
- The failed step name and error message (red)
- Available recovery actions derived from the lifecycle:
  - `closing:review` or `closing:verified` → retry or abort (back to `active`)
  - `closing:promoted` onward → retry only (abort not available)

## What the TUI Skips (LLM-only)

| Operation | Why it needs an LLM |
|-----------|---------------------|
| Forage SWEEP | Scans conversation memory for non-obvious knowledge |
| Protocol SWEEP | Identifies conventions from session reasoning |
| Write-content | Narrative synthesis (diary, blog) |
| Brainstorming | Design exploration before implementation |
| Design review | Adversarial spec analysis |
| Code review (semantic) | Understanding intent, catching logic errors |
| Squash analysis | Classifying commits by semantic concern |
| HANDOFF.md writing | Summarizing session context and reasoning |

The TUI's `end` runs the mechanical close only: promote, rebase,
push, stamp, close issues. Commits stay as-is unless the user
pre-squashes. These LLM operations can be invoked via the session
SPI when the user selects `session`.

## Slot-Specific Workflows

The lifecycle state machine supports slot creation via
`('idle', 'slot_create')`. Slot-specific features (epic management,
batch cycling) operate within the same lifecycle states but add
context:

- The TUI's `start` command detects slot context via `topology.resolve()`.
  In a slot workspace, `start` fires `slot_create` instead of `work`;
  the lifecycle transition table handles the distinction.
- The header shows slot context when `in_slot` is true: queue position
  includes batch info from `work_state.detect()` (e.g., "Queue: 1/3
  Batch: 2 of 4").
- Epic/plan detection in `work_state.py` already resolves
  `epic_batch`, `epic_active_issue`, `plan_batch` — the TUI header
  and `BriefReady` event surface these fields.
- `slot_manager.py` orchestration (68KB) requires library API
  extraction as noted in the refactoring table. The TUI command layer
  calls the extracted functions; detailed slot management TUI (batch
  cycling, epic dashboard) is a follow-on issue.

## Stateless CLI Mode

The same command layer supports stateless invocation for scripting
and automation:

```bash
soredium start 42 43 44
soredium next
soredium brief
soredium end
soredium what-next
```

Entry point: `python -m cli start 42` runs the command, prints
JSON events to stdout, exits. The TUI entry point (`python -m tui.python`)
is always interactive.

The `soredium` command is installed via `pyproject.toml`:
```toml
[project.scripts]
soredium = "cli.__main__:main"
soredium-tui = "tui.python.__main__:main"
```

### JSON Event Format

Each event is a JSON object on a single line (JSON Lines), with a `type`
field matching the dataclass name:

```json
{"type": "StepProgress", "command": "end", "step": "promoted", "detail": null}
{"type": "StepProgress", "command": "end", "step": "rebased", "detail": null}
{"type": "WorkEnded", "branch": "issue-42", "issues_closed": [42]}
{"type": "StateChanged", "old_state": "closing:stamped", "new_state": "idle", "available_actions": ["start", "what-next", "status"], "suggested_action": "start"}
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Command completed successfully |
| 1 | Command failed (a `CommandFailed` event is also emitted to stdout) |
| 2 | Invalid arguments or unknown command |

### Confirmations

In interactive CLI mode (TTY attached), `decide_fn` prompts on stderr
and reads from stdin. With `--yes` or no TTY, `decide_fn` is `None`
(scripts auto-proceed). Error events are always emitted to stdout
as JSON — stderr is reserved for prompts and diagnostics.

## Concurrency

The CLI mode enables concurrent access to shared state files (TUI
running while a CLI invocation modifies the same `.pause-stack` or
`.meta`). All read-modify-write operations on these files use
`fcntl.flock()` advisory locking:

```python
import fcntl
from contextlib import contextmanager

@contextmanager
def file_lock(path: Path):
    lock_path = path.parent / f".{path.name}.lock"
    with open(lock_path, 'w') as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
```

Protected operations:
- `stack.push_entry()` / `stack.pop_entry()` — lock `.pause-stack`
- `lifecycle.commit_transition()` — lock `.meta`

Lock granularity is per-file — stack and lifecycle operations do not
block each other. The `ConcurrentModification` exception in
`lifecycle.commit_transition()` remains as a secondary check: if two
processes acquire the lock sequentially, the second detects that the
state changed and raises rather than silently overwriting.

**Intent file guards.** Before executing a state-changing command, the
command layer checks for active intent files. If `.pausing` exists,
`resume` is rejected ("Pause in progress"). If `.resuming` exists,
`pause` is rejected. If `.execute-progress` exists, only `status` and
closing continuation are allowed. This prevents a concurrent CLI
invocation from starting a conflicting operation while the TUI or
another CLI is mid-operation. Intent files are removed on successful
completion; their presence always signals an in-progress or crashed
operation.

## Testing Strategy

- **Command layer** — unit tests with mocked script functions.
  Each command gets a test that verifies correct script calls
  and event emission.
- **Script refactoring** — existing tests continue to pass (CLI
  entry points unchanged). New tests for library API functions.
- **Events** — serialisation/deserialisation roundtrip tests.
- **UI** — Textual's built-in test framework (`async with app.run_test()`).
  Verify action panel contents for each state. Verify content panel
  updates on events.
- **Session SPI** — `decide_fn` pattern: tests inject a mock provider.
- **Integration** — end-to-end test: start → next → end cycle via
  command layer against a test git repo.

## Dependencies

**Python (tui/python/):**
- `textual` — TUI framework
- No other new dependencies. All script imports are from the existing
  soredium codebase.

**Runtime (optional):**
- `tmux` — required for multi-session management (Home View session
  indicators, background CLI sessions). If absent, falls back to
  `SuspendingProvider` and Home View shows no session status.
- `worklog` SQLite database — required by `what-next` for enrichment
  recommendations. Created by `worklog.connect()`. If absent or empty,
  `what-next` displays "No enrichment data available" and returns an
  empty `WhatNextReady`. The TUI does not fail; it degrades gracefully.
- `gh` CLI — used by `what-next` for GitHub issue cache refresh.
  If unavailable, cached data is used (may be stale or empty).

**Future Java (tui/java/):**
- `tamboui` — TUI framework
- `casehub platform agent-api` — LLM session SPI
- `picocli` — CLI mode
- Quarkus for CDI, native compilation

## Configuration

Precedence: environment variable > config file > default.

```
# Environment variables
SOREDIUM_SESSION_CLI=claude       # CLI to launch for LLM sessions
SOREDIUM_PROJECT=<path>           # Override project path detection
SOREDIUM_WORKSPACE=<path>         # Override workspace path detection

# Or config file: ~/.soredium/config.toml
[workspace]
scan_paths = ["~/claude/"]       # Directories to scan for repos/slots

[session]
provider = "tmux"                # "tmux" (default) or "suspend"
cli = "claude"

[paths]
project = "/path/to/project"     # Optional override (single-project mode)
workspace = "/path/to/workspace" # Optional override
```

Defaults: `provider = "tmux"`, `cli = "claude"`, `scan_paths = ["~/claude/"]`,
paths auto-detected via `topology.resolve()`.

## Decisions Reference

See [decisions.md](decisions.md) for the full decision log (D1–D12).

Key decisions:
- **D1:** Textual from the start (maps to Tamboui)
- **D2:** `tui/python/` and `tui/java/` location
- **D3:** Refactor scripts for library APIs
- **D4:** Event-driven command layer
- **D5:** LLM via casehub AgentProvider SPI (Java); Python equivalent
- **D7:** Action panel with keyboard navigation (guided UX)
- **D8:** Persistent panels over scrolling
- **D9:** Pluggable SessionProvider SPI (CLI-agnostic)
- **D10:** Suspend/resume as default, automated/embedded as future
- **D11:** Home screen as multi-repo/slot workspace manager
- **D12:** Multi-session management via tmux
