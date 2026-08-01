# Trellis — Epic Delivery Engine for Spec-Driven Parallel Development

**Issue:** Hortora/soredium#117
**Date:** 2026-07-30
**Status:** Draft

---

## 1. Problem

Managing parallel development across a multi-repo organisation (casehub: 20+ repos)
is currently manual. The developer juggles iTerm2 windows, mentally tracks which
slots are active, manually sequences work across epics, and makes all coordination
decisions themselves. There is no global view, no critical path analysis, no
recommendations, and no automation.

The work lifecycle skills (work-start, work-end, work-pause, work-resume, work-slot,
work-epic) provide the operations but no visibility or intelligence layer on top.

## 2. Solution

**Trellis** — a local Electron app backed by a Quarkus sidecar that serves as
an epic delivery engine. It understands the full dependency graph across repos
and epics, computes critical paths, recommends what to work on next, and
progressively automates coordination via an LLM agent. Distribution model:
download and double-click — Electron launches the Quarkus jar on a dynamic port
(proven pattern from sparge). A hybrid approach (native launcher + default
browser instead of Electron) is a future option if the full Electron shell
proves unnecessary.

Named after the garden framework that supports and organises parallel growth.

### Core thesis

Replace the developer's coordination role progressively:
- L0: Dashboard — human decides everything, trellis shows state
- L1: Advisor — trellis recommends, human decides (MVP)
- L2: Copilot — trellis proposes actions, human approves
- L3: Autopilot — trellis drives delivery, human steers at epic level

### Design principle: slots-first

All work should trend toward happening in worktree slots. The original checkout
stays on main as a stable reference. Trellis designs for this model without
enforcing it yet — slot-based work is the first-class path, non-slot work is
supported but not promoted.

### Scope relative to issue #117

Issue #117 asks: "Explore building a UI for the work lifecycle — work-start,
work-end, work-pause, work-resume, slot management, epic iteration."

This spec covers #117 scope in Batches 0–5 (MVP): workspace scanning, slot
management UI, work lifecycle operations, issue/dependency intelligence, and
LLM coordinator L1. Features beyond #117 (garden provenance, drafthouse
integration, LLM L2/L3, velocity tracking) are post-MVP and will be filed as
separate issues when implementation reaches that point.

## 3. Architecture

```
┌─────────────────────────────────────────────────────┐
│              Electron Shell (multi-window)           │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐       │
│  │Window 1│ │Window 2│ │Window 3│ │Window N│       │
│  │ tabs   │ │ tabs   │ │ tabs   │ │ tabs   │       │
│  └────────┘ └────────┘ └────────┘ └────────┘       │
│  BrowserWindow → localhost:N (dynamic port)         │
│  Electron IPC for cross-window state sync           │
│  Electron store for layout persistence              │
│  Detach/attach any panel ↔ independent windows      │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              Trellis Sidecar (Quarkus)               │
│                                                      │
│  ┌────────────┐ ┌────────────┐ ┌──────────────────┐ │
│  │   Tmux     │ │ Workspace  │ │   Issue Engine    │ │
│  │  Manager   │ │  Scanner   │ │  + Critical Path  │ │
│  │ (own impl) │ │            │ │  + Recommendations│ │
│  └────────────┘ └────────────┘ └──────────────────┘ │
│  ┌────────────┐ ┌────────────┐ ┌──────────────────┐ │
│  │   Work     │ │  Artifact  │ │     Garden        │ │
│  │ Lifecycle  │ │  Browser   │ │    Service        │ │
│  │  Manager   │ │            │ │  (post-MVP)       │ │
│  └────────────┘ └────────────┘ └──────────────────┘ │
│  ┌────────────┐                                      │
│  │  Project   │  Quinoa serves pages/blocks-ui       │
│  │Bootstrapper│  pages-push (SSE) + REST             │
│  └────────────┘                                      │
└──────────────────────────────────────────────────────┘
         │                        │
    tmux sessions            GitHub API
    (persist independently)  (issues, PRs)
```

### Key properties

- **Electron multi-window** — Electron BrowserWindows pointing at localhost:N
  (dynamic port, allocated by the sidecar). Electron IPC provides cross-window
  state synchronisation. Native window management enables drag-to-detach,
  multi-monitor layout persistence, and OS-level window positioning — capabilities
  browser `window.open()` cannot reliably deliver. Proven pattern from sparge
  (~/claude/sparge): Electron shell launches the Quarkus jar, no Node.js
  application logic needed.
- **Sidecar is the persistent process** — launched by Electron on startup (or
  via `trellis start` alias for `java -jar` / `mvn quarkus:dev` during
  development). tmux sessions and cached state persist across Electron restarts.
  Sidecar survives Electron quit — Electron reconnects on relaunch.
- **Own tmux management** — trellis implements its own TmuxManager, a thin
  ProcessBuilder wrapper around tmux CLI. Uses `trellis-*` naming convention
  (vs claudony's `claudony-*`). No shared dependency with claudony — TmuxService
  is ~200 lines of ProcessBuilder calls; sharing it would couple trellis to
  claudony's CaseHub-specific session model for no benefit.
- **Single port** — Quinoa serves the pages/blocks-ui frontend on the same port
  as REST and SSE APIs. pages-push SDK provides typed server→client push via SSE
  with `TopicRegistry`, `EventBroadcaster`, and `PushMessage` builders.
- **Workspace root as input** — point trellis at a root (e.g. ~/claude/casehub/)
  and it scans everything beneath.

### Dependency chain

`pages` → `blocks-ui` → **trellis sidecar** (+ `pages-push` for server→client push)
**trellis shell** (Electron) → `trellis sidecar` (localhost:N)

### Quinoa package distribution

Pages and blocks-ui are consumed as Maven SNAPSHOT artifacts
(`casehub-pages-npm`, `casehub-blocks-ui-npm`). Maven unpacks them into
`src/main/webui/.casehub-packages/` during the `initialize` phase.
`package.json` uses `portal:` resolutions pointing to `.casehub-packages/`.
No npm registry authentication needed. This follows the convention documented
in `casehub-pages/docs/quinoa-convention.md`.

## 4. Core Services

### 4.1 Workspace Scanner

Scans a root directory and builds the organisation model.

**Discovers:**
- Repos — every git repo under the root, with branch state, last activity, remote URL
- Slots — `worktrees/` directories, their `.slot` files, lifecycle state
  (active / ready-to-land / landed / archived). These are created by the
  existing `work-slot` skill (`slot_manager.py`) — trellis reads them, not owns them.
- Paused work — `.pause-stack` files across workspaces, with age
- Adhoc branches — non-main branches with no `.meta` (untracked work)
- Epics — `.epic` and `.slot` files with `Type: epic`, batch progress

**Behaviour:**
- Filesystem watcher (Java WatchService) for live updates, with fallback polling
- State push via `casehub-pages-push`: `PushMessage` builders with typed operations
  (snapshot on connect, append/replace/remove on changes). `TopicRegistry` manages
  per-topic subscriptions (e.g. `workspace/{root}/repos`, `workspace/{root}/slots`).
  `EventBroadcaster` fans out changes to all subscribed browser windows via SSE.
- Scans on startup, watches for changes thereafter
- **Direct notification from lifecycle manager:** when the Work Lifecycle Manager
  (§4.4) completes a filesystem-mutating operation (slot create, pause, resume),
  it notifies the scanner directly via an in-process CDI event. The scanner
  updates its model immediately and pushes via pages-push — no wait for the
  filesystem watcher or next rescan cycle. This eliminates the race condition
  between "API returns slot created" and "dashboard shows the slot."

**Failure modes:**
- **WatchService event loss** — Java WatchService on macOS (kqueue) can miss events
  under high filesystem throughput. Mitigation: periodic rescan (every 60s) reconciles
  watcher state with filesystem. Rescan is lightweight — stat calls only, no git
  operations.
- **Corrupted `.slot` / `.meta` files** — malformed YAML/properties. Mitigation:
  parse with fallback — corrupted files are logged as warnings and excluded from the
  model until next successful parse. Never crash the scanner.
- **Git repo in inconsistent state** — e.g. mid-rebase, locked index. Mitigation:
  skip repos with `.git/index.lock` present; retry on next scan cycle.

### 4.2 Tmux Manager (trellis-owned)

Trellis implements its own TmuxManager — a thin ProcessBuilder wrapper around
the tmux CLI. This follows claudony's proven `tmux-as-external-state-store`
pattern but without any claudony dependency.

**Capabilities:**
- Create/destroy tmux sessions with convention names (`trellis-slot-3-engine`)
- Stream terminal output to xterm.js via WebSocket (FIFO pipe architecture,
  same pattern as claudony: `tmux pipe-pane` → named FIFO → virtual thread
  read loop → WebSocket send)
- Accept input — from human via xterm.js, or from LLM coordinator
  (`tmux send-keys -t name -l "text"`)
- Bidirectional — the LLM can read terminal output and send keystrokes
- Session discovery on restart — `tmux list-sessions` filtered by `trellis-*`
  prefix, matching claudony's bootstrap pattern
- Session metadata via tmux options — supplementary metadata stored as tmux
  session options (`tmux set-option @trellis_slot`, `@trellis_repo`,
  `@trellis_issue`), recovered on restart via `tmux show-options`. This
  follows claudony's proven pattern (`@casehub_case_id`, `@casehub_role`)
  and keeps tmux as the single source of truth — no separate metadata file

**Why not share claudony's TmuxService:**
- TmuxService is ~200 lines of ProcessBuilder wrappers — the extraction cost
  exceeds the sharing benefit
- Claudony's session model includes CaseHub-specific concepts (caseId, roleName,
  ExpiryPolicy, fleet federation) that trellis does not need
- `TerminalWebSocket` lives in `claudony-app` (Quarkus application module), not
  `claudony-core` — it cannot be consumed as a library jar
- Platform boundary rules: application-tier repos must not depend on each other.
  While trellis is not a CaseHub application, importing claudony's module creates
  transitive dependency on `casehub-platform-api` and `casehub-qhorus` — coupling
  that violates the principle of peer isolation

**Failure modes:**
- **tmux session dies unexpectedly** — monitored via periodic `tmux has-session`
  check (same pattern as claudony's `ClaudonyWorkerExecutionManager`). Dead
  sessions are removed from the registry and the UI is notified via pages-push.
- **Sidecar crashes** — tmux sessions survive independently. On restart,
  `bootstrapRegistry()` re-discovers all `trellis-*` sessions from tmux.
  Browser reconnects automatically via SSE reconnection.
- **FIFO read stalls** — virtual thread timeout (30s). If FIFO read blocks
  indefinitely, the thread is interrupted and the WebSocket connection is
  closed with a reconnection hint.

### 4.3 Issue Engine + Critical Path

GitHub API integration with delivery intelligence.

**Issue management:**
- Per-repo issue list with grouping (epics, labels, milestones, dependency graph)
- Backlog cache — stored locally in `~/.trellis/cache/`, refreshed on demand or
  interval, avoids hammering GitHub API
- Cross-repo view — issues referencing other repos, cross-repo epics

**Critical path computation:**
- Parse blocked-by/blocks relationships from issue bodies and labels
- Build a DAG per epic (nodes = issues, edges = dependencies)
- Compute critical path — the longest chain of dependent issues
- Identify bottlenecks — issues whose completion unblocks the most downstream work
- Parallel opportunity detection — unblocked issues that can run simultaneously

**Dependency parsing format:**
- **Labels:** `blocked-by:#N` label on an issue means it is blocked by issue #N
  in the same repo. Cross-repo: `blocked-by:owner/repo#N`.
- **Issue body:** `## Dependencies` section with checklist items:
  `- [ ] #N — description` (same repo) or `- [ ] owner/repo#N — description`.
  Checked items (`- [x]`) indicate resolved dependencies.
- **Cross-repo:** full `owner/repo#N` format. Trellis resolves via GitHub API.
- **Cycle detection:** Kahn's algorithm (topological sort). If the sort does not
  consume all nodes, the remaining nodes form one or more cycles. Trellis logs
  the cycle and presents it in the UI as a warning — cycles are real (accidental
  circular dependencies in issue trackers happen). Cycle nodes are excluded from
  critical path computation but shown in the DAG visualisation.
- **Closed issues in DAG:** treated as completed nodes. Their edges remain (they
  may still be on the critical path historically). Visualised as greyed-out nodes.

**Failure modes:**
- **GitHub API unreachable** — serve from local cache (`~/.trellis/cache/`).
  UI shows "cached at {timestamp}" indicator. Background retry every 60s.
- **Malformed dependency references** — unparseable `blocked-by` labels or body
  references are logged as warnings, excluded from the DAG. The issue still
  appears as an unconnected node.
- **Rate limits** — conditional requests (If-None-Match/ETag) reduce API calls.
  When rate-limited, serve from cache and display remaining reset time.

**Recommendations engine (algorithmic — no LLM):**
- For each repo: suggest 2–3 next issues with scored ranking
- Factors: critical path position, dependency unlocking impact, epic momentum
  (near-complete epics get priority), scale fit, idle slot capacity
- Cross-epic: shared dependencies that advance multiple epics, resource contention
  between epics
- Output: ranked issue list with factor scores. This is a pure algorithmic system
  delivered in Batch 3 — no LLM required. The LLM Coordinator (§6, Batch 5)
  consumes these rankings as input and adds natural language reasoning on top
  (e.g. "I recommend #42 because it unblocks 3 downstream issues and you have
  an idle slot in engine"). The two layers are intentionally separate: B3 is
  deliverable and testable without an LLM.

### 4.4 Work Lifecycle Manager

Exposes soredium's externalised lifecycle scripts as REST API operations,
callable by button click or LLM coordinator. No Claude Code process needed —
all lifecycle skills have heavily externalised their mechanical operations into
standalone Python scripts.

| Operation | Script calls | What it does |
|-----------|-------------|--------------|
| start | `work_router.py` → `branch_create.py create-branches` → `scaffold.py` | Detect state, create branch, scaffold .meta + JOURNAL.md |
| end | `land_branch.py rebase` → `land_branch.py push` → `land_branch.py stamp` + `close_artifacts.py` + `branch_cleanup.py` | Rebase, push, stamp branch closed, close issue |
| pause | `pause_exec.py commit-wip` → `pause_exec.py push-and-stack` | WIP commit, push branches, add to pause stack |
| resume | `resume_exec.py checkout-branches` → `resume_exec.py rebase` → `resume_exec.py reset-wip` | Checkout branch, rebase, undo WIP commit |
| slot-create | `slot_manager.py create-slot` | Create worktree slot for multi-repo work |
| slot-list | `slot_manager.py list-slots` | List all slots with status |
| slot-merge | `slot_manager.py merge-slot` | Land ready-to-land slots |
| slot-scan-ready | `slot_manager.py scan-ready` | Find slots ready to land (`.phase-a-complete` marker) |
| slot-check-deps | `slot_manager.py check-cross-deps` | Verify cross-repo Maven deps landed on main |
| slot-remove | `slot_manager.py remove-slot` | Archive or delete a slot |
| slot-archive | `slot_manager.py archive-slot` | Move landed slot to attic with SHA verification |
| epic-setup | `epic_manager.py write` | Write .epic with batch plan (children parsed via Issue Engine) |
| next | `epic_manager.py advance` | Advance to next child issue in epic |

**Script invocation model:** The sidecar calls Python scripts directly via
`ProcessBuilder`, not through Claude Code. The scripts already exist in
soredium's lifecycle skills:
- `work-start/`: `branch_create.py`, `scaffold.py`
- `work-end/`: `land_branch.py` (rebase/push/stamp), `close_artifacts.py`,
  `branch_cleanup.py`, `artifact_promote.py`, `workspace_artifacts.py`
- `work-pause/`: `pause_exec.py` (commit-wip, push-and-stack)
- `work-resume/`: `resume_exec.py` (checkout-branches, rebase, reset-wip)
- `work/`: `work_router.py` (state detection)
- `work-slot/`: `slot_manager.py`, `epic_manager.py`

All scripts follow the same convention: subcommand + positional args + KEY=value
params, stdout produces KEY=value output, non-zero exit on error.

**Script path discovery:** The sidecar resolves script paths via the
`trellis.skills.path` config property, defaulting to `~/.claude/skills/`
(where `sync-local` installs soredium skills). Example: the `start` operation
calls `${trellis.skills.path}/work-start/branch_create.py`. Prerequisites:
Python 3 must be on PATH (`#!/usr/bin/env python3`). Sibling imports (e.g.
`common.py` in work-end) resolve naturally because ProcessBuilder sets the
working directory to the script's parent directory.

**Two-tier invocation model — mechanical vs full-featured:**

The button-click path is a **fast lane** for mechanical operations. It excludes
the LLM-only parts of the skills: code review (work-end), squash analysis
(work-end), coherence checks (work-start), and protocol checks.

This means **button-click work-end pushes code without review** — intentionally.
The full work-end skill gate (code review before push) is a Claude Code session
concern, not a mechanical operation. When to use each path:

| Path | When to use | What's included |
|------|------------|-----------------|
| Button click (fast lane) | Trivial changes, doc fixes, metadata-only, already-reviewed code | Rebase, push, stamp, close issue |
| Terminal (full-featured) | Substantive code changes, first-time landing | Code review + squash analysis + all mechanical steps |

The UI labels the button-click work-end action with "(skip review)" to make the
semantic difference visible. The terminal path is always available via the slot's
terminal panel — the user runs `work end` in a Claude Code session there.

For the full-featured flow (code review + squash analysis before landing), the
user opens a Claude Code session via the terminal panel and runs `work end`
there. This is the natural path at autonomy levels L2/L3.

**Relationship to existing skills:** Trellis does not replace the work lifecycle
skills. The skills remain the primary interface for Claude Code sessions. Trellis
calls the same underlying scripts — the REST API is a parallel entry point to
the same mechanical operations.

**Failure modes:**
- **Script fails mid-execution** — e.g. `land_branch.py rebase` hits a conflict.
  Script returns non-zero exit with `ERROR=rebase_conflict` on stdout. The
  sidecar reports the error to the UI. The user can resolve in the terminal and
  retry via the UI.
- **Concurrent operations on the same slot** — mutex per slot in the lifecycle
  manager. Second operation receives HTTP 409 Conflict with the running
  operation's description.

### 4.5 Artifact Browser

Resolves and serves workspace artifacts.

**Artifact types:**
- Specs — `$WORKSPACE/specs/<branch>/`, rendered markdown
- ADRs — `$PROJECT/docs/adr/`, rendered markdown
- Journals — `$WORKSPACE/design/JOURNAL.md`
- Handovers — `$WORKSPACE/HANDOFF.md`
- Design reviews — active ADR design reviews with status tracking

Provenance (linking artifacts to garden entries) is deferred to post-MVP
(Batch 6a). The provenance recording convention (`.provenance.yaml` sidecars)
does not yet exist in the skill ecosystem — it will be designed and implemented
as a prerequisite to the Garden Service.

### 4.6 Garden Service (post-MVP)

Knowledge garden integration: search, browse, and provenance tracking.
Deferred to Batch 6a — the provenance recording mechanism (`.provenance.yaml`
sidecars, skill changes to write them) does not exist yet and must be designed
separately.

**Search (Batch 6a):** query the garden via gardenSearch MCP or fallback grep.
Filter by domain, recency, usage frequency.

**Provenance recording (Batch 6a):** when skills search the garden during spec
creation, record which GE-IDs were consulted. Requires a new convention for
how `brainstorming` / `work-start` writes `.provenance.yaml` alongside specs.
This convention will be designed as part of the Garden Service implementation.

**Lineage queries (Batch 6a):**
- Forward: spec → which garden entries informed it
- Reverse: garden entry → which specs/work items reference it

### 4.7 Project Bootstrapper

First-run onboarding for known project families.

**Registry:** ships with `~/.trellis/projects.json` listing known projects.
Each entry: name, description, parent repo URL, setup script/skill reference,
expected folder structure.

**Bootstrap flow:**
1. User picks a project (e.g. "casehub")
2. Trellis creates `~/claude/<project>/`
3. Clones the parent repo
4. Runs the parent's setup (which clones child repos, configures workspaces)
5. Workspace scanner picks up the new tree → dashboard populates

**Extensible:** "new app" template support planned for later.

## 5. UI Composition

### 5.1 Window Management (Electron)

Multi-window with detach/attach, replacing manual iTerm2 window management.
Electron provides native window management that browser APIs cannot reliably
deliver (programmatic multi-monitor positioning, OS-level drag-to-detach,
per-monitor layout memory). Proven pattern from sparge.

- **Main window** — always exists, shows the epic delivery dashboard
- **Detachable panels** — any panel (terminal group, repo detail, artifact viewer)
  can be dragged out into its own Electron BrowserWindow. For terminal panels:
  **transfer semantics** — detaching a terminal transfers its WebSocket
  connection to the new window (the old window loses that terminal). One active
  viewer per tmux session, matching claudony's click-to-switch pattern. The FIFO
  pipe architecture writes to one consumer; simultaneous multi-window viewing of
  the same session is not supported. To view multiple terminals simultaneously,
  open them as separate tabs within one window.
- **Tabs within windows** — each window supports 1..N tabs. A slot window might
  have tabs for each repo's terminal plus the spec viewer.
- **Layout persistence** — window positions, sizes, screen assignments, tab
  arrangements saved via electron-store (JSON file). Restored on launch.
  Per-workspace layouts. Electron's `screen` API tracks monitor geometry —
  windows remember which monitor they belong to.
- **Cross-window IPC** — Electron IPC provides cross-window state sync.
  Actions in one window (e.g. "start slot") can open terminals in the right
  detached window. All windows share the same sidecar SSE connection for
  server-pushed state updates via pages-push.
- **Future option** — if the Electron shell proves heavier than needed, a
  native launcher (start sidecar + open default browser) is a viable
  fallback. The sidecar and UI are fully browser-compatible by design.

### 5.2 Primary View: Epic Delivery Dashboard

The default view. Answers: "what do I need to do next to land this epic?"

**Layout:**
- **Top bar** — epic selector + KPI row (`kpi-metric-row`): critical path length,
  % complete, projected completion, active slots, bottleneck count
- **Center** — dependency graph (DAG). Nodes = issues, edges = dependencies.
  Color-coded: done / active (in slot) / unblocked / blocked. Critical path
  highlighted. Click node → issue detail.
- **Right panel** — "Next actions" recommendations with reasoning. At L1: human
  reads and acts. At L2+: approve/reject buttons.
- **Bottom** — batch progress timeline. Current batch, safe exit points, batch
  boundaries.

**Cross-epic view:** when multiple epics are active:
- Resource contention — two epics competing for the same repo's attention
- Shared dependencies — completing issue X advances both epics
- Portfolio recommendations — which epic to focus on based on completion
  proximity and priority

### 5.3 Repo Detail View

Drill into a single repo, contextualised within its epic(s).

**Tabs:**
- **Issues** — grouped browser (epics, labels, dependencies, blocked-by/blocks).
  Backlog with search/filter. "Recommended next" with reasoning. One-click
  "Start work" per issue → slot creation dialog.
- **Work** — active and completed work. Each item: branch, slot, issue, status,
  specs. Click → slot detail with terminals.
- **Artifacts** — specs, ADRs, journals. Rendered markdown. Links to active
  design reviews.

### 5.4 Slot / Work Item Detail View

Focused on a single piece of work.

- **Terminal panels** — xterm.js for each repo in the slot. Tab layout for
  multi-repo slots. LLM coordinator's session visible (observation mode).
- **Sidebar** — issue context, .meta info, epic progress (if in an epic),
  spec list, active design review status.
- **Actions** — work-end (skip review), work-end (full, via terminal), work-pause,
  work-next (epic). Post-MVP: open design review (Batch 6c).

### 5.5 Garden View (post-MVP — Batch 6a)

Knowledge garden browser and search. Deferred with the Garden Service (§4.6).

- **Search** — full-text across garden entries, filter by domain/recency/usage
- **Entry viewer** — rendered markdown
- **Usage map** — which specs/work items reference this entry (reverse provenance)

### 5.6 Design Review View

Drafthouse integration for spec and document reviews.

- **Per-work-item** — reviews for the current slot's specs
- **Global** — all ongoing design reviews across all work. Status per review
  uses the ADR tool's actual tracker statuses: OPEN, ADDRESSED, VERIFIED,
  REJECTED, ACCEPTED, CONTESTED. No translation layer — trellis reads
  `tracker.md` directly. Runtime stats: duration, point count, resolution rate.
- **Launch** — "review this spec" from the artifact browser launches the ADR
  review tool (`python3 review.py --spec <path> --source-dirs <paths>`) in a
  trellis-managed tmux session. The review runs in the background; trellis
  monitors `progress.log` and `tracker.md` for status updates, pushing them
  to the UI via pages-push.

### 5.7 Component Reuse from blocks-ui

| View element | Component |
|---|---|
| KPI bar | `kpi-metric-row` |
| Work item lists | `work-item-inbox` + `work-item-row` |
| Activity feed | `notification-inbox` |
| Terminal panels | xterm.js (trellis-owned WebSocket integration) |
| Design review | drafthouse components |
| Issue/backlog tables | `pages-table` |
| Epic progress | `commitment-viz` + `blocks-timeline` |
| Spec/ADR viewer | markdown renderer (from drafthouse or new) |

## 6. LLM Coordinator

A Claude Code session in a managed tmux session with full org awareness.

### Context (what it sees)

- Full dependency graph across all repos and epics
- All slot state (active, paused, landed, archived)
- Terminal output from active sessions (read access, throttled)
- Issue bodies, labels, comments, cross-references
- Spec contents (garden provenance deferred to post-MVP, see §4.6)
- Velocity history (issues completed per time period)

### Capabilities (gated by autonomy level)

| Level | Can do |
|-------|--------|
| L1 (MVP) | Query the algorithmic recommendations engine (§4.3) for ranked next-actions, add natural language reasoning and context, answer "what should I work on?" with explanation |
| L2 | Propose actions (start slot, advance epic, pause work) → user clicks approve → trellis executes |
| L3 | Act directly — create slots, run work-start, advance epics, flag humans when blocked. User observes via xterm.js and can intervene. |

### Terminal interaction

- Read other tmux sessions' output via `tmux capture-pane` (throttled to avoid
  overwhelming context)
- Send input to other sessions via `tmux send-keys`
- User observes all of this in real time via xterm.js panels

### ISX integration (future)

ISX removes Claude Code's permission prompts, enabling L3 autonomy without
constant HIL approval. Separate implementation step.

## 7. Data Model

### Read from filesystem (existing — not owned by trellis)

| File | What | Authoritative for |
|------|------|-------------------|
| `.meta` | Branch scaffold | Issue, covers, SHA, design-repo |
| `.slot` | Slot context | Issue, repos, epic batch plan |
| `.epic` | Single-repo epic state | Batch plan, active issue |
| `.pause-stack` | Paused branches | Pause stack per workspace |
| `worktrees/attic/` | Archived slots | Completed work history |

### Read from GitHub API

- Issues: state, labels, body, cross-references, blocked-by/blocks
- PRs: state, review status, head branch
- Epic structure: parent → child issue checklist

### Trellis-owned state

| Path | What |
|------|------|
| `~/.trellis/workspaces.json` | Recent workspace roots (launcher) |
| `~/.trellis/projects.json` | Bootstrapper registry |
| `~/.trellis/cache/<repo>/issues.json` | Issue backlog cache per repo |
| `~/.trellis/velocity/<epic>.json` | Historical velocity data per epic |
| electron-store JSON | Window layout (positions, tabs, monitor assignments, per-workspace) |
| tmux session options | Session metadata (`@trellis_slot`, `@trellis_repo`, `@trellis_issue`) |

### Trellis does NOT own

- Issue state → GitHub is authoritative
- Branch state → git is authoritative
- Slot lifecycle → .slot files are authoritative
- Garden entries → hortora garden is authoritative

## 8. Execution Plan

### Dependency graph

```
B0 (skeleton) ──┬──→ B1a (workspace scanner)
                │         │
                │         ├──→ B2a (issue engine)
                │         │        │
                │         │        └──→ B3 (critical path + recommendations)
                │         │                    │
                │         │                    └──→ B5 (LLM coordinator L1)
                │         │
                │         └──→ B2b (work lifecycle manager)
                │                    │
                │                    └──→ B4 (one-click work-start from UI)
                │
                ├──→ B1b (session manager integration)
                │         │
                │         └──→ B2c (terminal panels in UI)
                │                    │
                │                    └──→ B4 (one-click work-start)
                │
                ├──→ B1c (multi-window + detach)
                │
                └──→ B1d (project bootstrapper)

B2a + B2b ──→ B4 (one-click work-start ties issues to lifecycle to terminals)

Post-MVP (after B5):
  B6a: garden service + provenance
  B6b: artifact browser
  B6c: drafthouse integration
  B7:  LLM coordinator L2 (propose actions)
  B8:  LLM coordinator L3 (autopilot) + ISX
  B9:  velocity tracking + projections
```

### Batch plan

**Batch 0 — Skeleton** (foundation, must be first)

| # | Task | Scope | Estimate |
|---|------|-------|----------|
| 0.1 | Create `hortora/trellis` repository with two sub-projects: `sidecar/` (Quarkus/Maven) and `shell/` (Electron/npm) | pom.xml, package.json, project structure, CLAUDE.md | S |
| 0.2 | Sidecar boots with Quinoa — serves blank pages app on dynamic port | Quarkus application, Quinoa config, esbuild, pages dependency | S |
| 0.3 | Electron shell — launches sidecar jar, opens BrowserWindow at dynamic port | Electron main process, sidecar lifecycle management | M |
| 0.4 | `npm start` launches the whole thing (Electron + sidecar) | Following sparge pattern | S |
| 0.5 | CI — build and test | GitHub Actions or local validation | S |

**Batch 1 — Core services (parallel tracks)**

Four independent tracks, all depend on B0 only:

| # | Task | Track | Depends on | Estimate |
|---|------|-------|-----------|----------|
| 1a.1 | Workspace scanner — discover repos under root | Scanner | B0 | M |
| 1a.2 | Workspace scanner — discover slots, .meta, .pause-stack | Scanner | 1a.1 | M |
| 1a.3 | Workspace scanner — filesystem watcher + SSE push (pages-push) | Scanner | 1a.2 | M |
| 1a.4 | Org dashboard — repo list + slot/work map (pages + blocks-ui) | Scanner UI | 1a.2 | L |
| 1b.1 | TmuxManager — create/destroy sessions, ProcessBuilder wrappers | Sessions | B0 | M |
| 1b.2 | TerminalWebSocket — FIFO pipe streaming + xterm.js | Sessions | 1b.1 | M |
| 1b.3 | Session naming convention (`trellis-*`) + discovery on restart | Sessions | 1b.1 | S |
| 1c.1 | Multi-window Electron — detach/attach BrowserWindows + IPC | Windows | B0 | L |
| 1c.2 | Tab management within windows | Windows | 1c.1 | M |
| 1c.3 | Layout persistence (electron-store) + multi-monitor | Windows | 1c.2 | M |
| 1d.1 | Project bootstrapper — registry + clone + setup | Bootstrap | B0 | M |
| 1d.2 | Launcher UI — recent workspaces + "set up a project" | Bootstrap | 1d.1 | S |

**Parallelism:** 1a, 1b, 1c, 1d are fully independent. Four slots.

**Batch 2 — Intelligence layer (partial parallelism)**

| # | Task | Track | Depends on | Estimate |
|---|------|-------|-----------|----------|
| 2a.1 | Issue engine — GitHub API client, backlog cache | Issues | 1a.2 | M |
| 2a.2 | Issue engine — dependency graph parser (blocked-by/blocks) | Issues | 2a.1 | M |
| 2a.3 | Issue browser UI — grouped list, backlog, search/filter | Issues UI | 2a.1 | L |
| 2b.1 | Work lifecycle manager — wrap lifecycle scripts as REST endpoints | Lifecycle | 1a.2 | M |
| 2b.2 | Work lifecycle manager — execute in trellis tmux sessions | Lifecycle | 2b.1 + 1b.1 | M |
| 2c.1 | Terminal panels — xterm.js in slot detail view | Terminals | 1b.2 + 1c.1 | M |
| 2c.2 | Terminal tab layout for multi-repo slots | Terminals | 2c.1 + 1c.2 | M |

**Parallelism:** 2a (issues) and 2b (lifecycle) are independent. 2c depends on
both sessions (1b) and windows (1c).

**Batch 3 — Critical path (the core value)**

| # | Task | Depends on | Estimate |
|---|------|-----------|----------|
| 3.1 | Critical path algorithm — DAG computation per epic | 2a.2 | L |
| 3.2 | Bottleneck detection — rank issues by unlocking impact | 3.1 | M |
| 3.3 | Parallel opportunity detection — optimal slot allocation | 3.2 | M |
| 3.4 | Recommendations engine — next-action suggestions with reasoning | 3.2 | L |
| 3.5 | Epic delivery dashboard UI — DAG viz, KPIs, recommendations panel | 3.4 + 1a.4 | XL |
| 3.6 | Cross-epic portfolio view | 3.5 | M |

**Batch 4 — One-click work-start (ties everything together)**

| # | Task | Depends on | Estimate |
|---|------|-----------|----------|
| 4.1 | "Start work" button in issue browser → slot creation dialog | 2a.3 + 2b.2 | M |
| 4.2 | Slot creation → terminal auto-opens in correct window | 4.1 + 2c.1 | M |
| 4.3 | Epic context — start from recommendation, link to batch plan | 4.1 + 3.4 | M |

**Batch 5 — LLM Coordinator L1 (advisor)**

| # | Task | Depends on | Estimate |
|---|------|-----------|----------|
| 5.1 | Coordinator tmux session — managed by session manager | 1b.1 | M |
| 5.2 | MCP tools for coordinator — query org state, issues, critical path | 5.1 + 3.1 | L |
| 5.3 | Coordinator reads other sessions' output (throttled) | 5.1 + 1b.2 | M |
| 5.4 | Coordinator UI — observation panel, recommendation display | 5.2 + 2c.1 | M |

**--- MVP boundary ---**

**Batch 6 — Knowledge layer (parallel tracks, post-MVP)**

| # | Task | Track | Depends on | Estimate |
|---|------|-------|-----------|----------|
| 6a.1 | Garden service — search integration | Garden | B0 | M |
| 6a.2 | Garden service — provenance recording (.provenance.yaml) | Garden | 6a.1 | M |
| 6a.3 | Garden UI — search, entry viewer, usage map | Garden | 6a.2 | L |
| 6b.1 | Artifact browser — resolve specs/ADRs/journals from .meta | Artifacts | 1a.2 | M |
| 6b.2 | Artifact browser — rendered markdown viewer | Artifacts | 6b.1 | M |
| 6b.3 | Artifact browser — provenance links to garden entries | Artifacts | 6b.2 + 6a.2 | S |
| 6c.1 | Drafthouse integration — launch review from artifact browser | Reviews | 6b.2 | M |
| 6c.2 | Design review list — all active reviews, status, stats | Reviews | 6c.1 | M |

**Batch 7–9 — Autonomy escalation (sequential)**

| # | Task | Depends on | Estimate |
|---|------|-----------|----------|
| 7.1 | LLM coordinator L2 — propose actions with approve/reject UI | B5 | L |
| 7.2 | Action execution pipeline — approved actions → lifecycle manager | 7.1 | M |
| 8.1 | LLM coordinator L3 — autonomous action with observation | 7.2 | L |
| 8.2 | ISX integration — permission-free execution | 8.1 | L |
| 9.1 | Velocity tracking — issues/week per epic, historical trends | 3.1 | M |
| 9.2 | Completion projections — estimated dates based on velocity + critical path | 9.1 | M |

### Summary: batch parallelism

```
B0 ─────────────────────────────── (sequential, foundation)
  │
  ├── B1a (scanner)    ─┐
  ├── B1b (sessions)    │ 4 parallel tracks
  ├── B1c (windows)     │
  └── B1d (bootstrap)  ─┘
        │
  ├── B2a (issues)     ─┐
  ├── B2b (lifecycle)   │ 3 partially parallel tracks
  └── B2c (terminals)  ─┘
        │
     B3 (critical path) ── (sequential, core value)
        │
     B4 (one-click start) ── (integration batch)
        │
     B5 (LLM L1)       ── (sequential)
        │
  ═══ MVP ═══════════════════════════════════════
        │
  ├── B6a (garden)     ─┐
  ├── B6b (artifacts)   │ 3 parallel tracks
  └── B6c (reviews)    ─┘
        │
     B7 → B8 → B9      ── (sequential, autonomy escalation)
```

### Epic structure for driving via slots

Each batch maps to a GitHub epic. Child issues map to the numbered tasks.
Recommended slot allocation:

| Batch | Slots needed | Can run with |
|-------|-------------|-------------|
| B0 | 1 | Nothing (must be first) |
| B1a–d | Up to 4 | All four in parallel |
| B2a–c | Up to 3 | Partially parallel |
| B3 | 1–2 | After B2a completes |
| B4 | 1 | After B2+B3 |
| B5 | 1 | After B3 |
| B6a–c | Up to 3 | All three in parallel, post-MVP |
| B7–9 | 1 each | Sequential |

Total: ~52 tasks across 10 batches. MVP is batches 0–5 (~35 tasks).

## 9. Open Questions

1. ~~**Claudony dependency model**~~ — **RESOLVED:** Trellis implements its own
   TmuxManager. No claudony dependency. See §4.2.
2. **DAG visualisation library** — build on pages' ECharts integration (has graph
   support), or use a dedicated DAG library (dagre, elk.js)?
3. ~~**Sidecar lifecycle**~~ — **RESOLVED:** `trellis start` launches the Quarkus
   sidecar directly (`java -jar` or `mvn quarkus:dev`). Browser windows connect
   to localhost:N. Browser close does not affect the sidecar. See §3.
4. **GitHub API rate limits** — with 20+ repos, aggressive polling hits rate limits.
   Mitigation: conditional requests (ETag/If-None-Match), local cache with
   staleness indicator, configurable refresh intervals. See §4.3 failure modes.
5. ~~**Provenance recording mechanism**~~ — **RESOLVED:** Deferred to post-MVP
   (Batch 6a). The convention will be designed as part of the Garden Service
   implementation. See §4.6.
