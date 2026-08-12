# Decisions — Issue #222: REPL Shell

## D1: Python TUI framework

**Choice:** Textual from the start
**Alternatives:**
- cmd.Cmd first, Textual later — proves script API layer before adding TUI complexity, but requires migration
- prompt_toolkit — richer than cmd.Cmd but no widget tree or CSS; doesn't map to Tamboui
**Rationale:** Textual is Python's closest equivalent to Tamboui (CSS theming, widget tree, mouse support, async event loop). Starting here gives a clean 1:1 port path to Java/Tamboui with no intermediate migration.
**Trade-offs:** Higher initial complexity than cmd.Cmd; Textual has its own learning curve
**Exploration:** quick
**Status:** captured

## D2: App location in soredium

**Choice:** `tui/python/` and `tui/java/` (follow-on) under a shared `tui/` top-level directory
**Alternatives:**
- `app/python/` and `app/java/` — generic; "app" is ambiguous
- `python-app/` and `java-app/` as separate top-level dirs — clear but less grouped
- Extend soredium's `engine/` — conflates garden operations with lifecycle operations
**Rationale:** Says exactly what it is. Groups the two runtime implementations under one directory. Python imports existing scripts in place (no moves). Java will be a full port.
**Trade-offs:** Introduces a new top-level directory; `engine/` stays separate (consolidation is a future decision)
**Exploration:** quick
**Status:** captured

## D3: Script consumption strategy

**Choice:** Refactor existing scripts to expose clean library APIs
**Alternatives:**
- Thin adapter layer in the REPL — no script changes, but fragile coupling to sys.argv patterns
- Subprocess fallback — treat non-importable scripts as external processes
**Rationale:** Scripts continue to work within Claude Code (CLI entry points preserved) but also become importable. Prepares the codebase for the eventual full Java port — clean APIs document what needs reimplementing.
**Trade-offs:** Requires touching ~15 existing scripts; must maintain backward compatibility with skill invocations
**Exploration:** quick
**Status:** captured

## D4: Architecture — UI to script layer relationship

**Choice:** Event-driven command layer (Approach C)
**Alternatives:**
- Thin orchestrator (A) — Textual calls scripts directly; simple but orchestration couples to UI, must reimplement for Java
- Command layer returning results (B) — portable but request/response only; would need migration to events for Tamboui
**Rationale:** Both Textual and Tamboui are event-driven frameworks. Starting with typed events (dataclasses in Python) aligns with both from day one — no intermediate migration. Commands emit events like BranchCreated, PlanAdvanced, PromotionComplete; the UI subscribes and renders.
**Trade-offs:** More infrastructure upfront than B, but the delta is small (events are just dataclasses, Textual has built-in message system)
**Exploration:** quick
**Status:** captured

## D5: LLM integration

**Choice:** Depend on casehub platform `AgentProvider` SPI
**Alternatives:**
- Claude CLI subprocess directly — simpler but doesn't share the platform abstraction
- Direct Anthropic API — requires API key management separate from platform
- Pluggable provider built from scratch — reinvents what platform already provides
**Rationale:** casehub/platform already has `AgentProvider` with `agent-claude` (CLI subprocess) and `agent-langchain4j` implementations. Java app depends on `agent-api` directly. Python app needs a lightweight equivalent (likely Claude CLI subprocess, mirroring agent-claude's approach).
**Trade-offs:** Creates a dependency on casehub/platform for the Java app; Python side needs its own thin implementation of the same pattern
**Exploration:** quick
**Status:** captured

## D6: Issue scope

**Choice:** Python app first (this issue); Java/Tamboui app as follow-on issue
**Alternatives:**
- Both in this issue — ensures sync from day one but larger scope
**Rationale:** Python app proves the command layer and event architecture. Script refactoring happens here. Java port is a clean follow-on once the API surface is stable.
**Trade-offs:** Risk of Python-specific patterns creeping into the command layer that don't port cleanly
**Depends on:** D4 (event-driven architecture mitigates this — events are language-agnostic concepts)
**Exploration:** quick
**Status:** captured

## D7: UX model — guided, not guessing

**Choice:** Action panel with keyboard navigation
**Alternatives:**
- Smart prompt with suggestions — text input with auto-suggested next action and tab completion; closer to traditional REPL but still requires typing
- Dashboard with modal actions — multi-panel dashboard with keyboard shortcuts; richer information density but more complex interaction model
**Rationale:** The user should never have to guess what they can do or what to do next. A persistent action panel showing only valid actions for the current state, navigable with arrow keys and Enter, eliminates both problems. The lifecycle state machine already knows valid transitions — the action list derives directly from it.
**Trade-offs:** Less flexible than a text prompt for power users who want to type. Could add an optional command input for advanced use, but the primary interaction is selection-based.
**Exploration:** quick
**Status:** captured

## D8: Terminal UI layout — panels over scroll

**Choice:** Persistent panels that update in place
**Alternatives:**
- Scrolling log output (traditional REPL) — simple but information scrolls away; user must remember or re-run commands to see state
**Rationale:** Status, plan progress, and available actions should be always-visible, not scrolled past. Textual's widget system handles this natively — header bar (branch/state/issue), action panel (left), content area (right, scrollable for action output), footer (keybindings). Maps directly to Tamboui's toolkit layer.
**Trade-offs:** Requires more upfront layout work; terminal size constraints may need responsive handling
**Depends on:** D1 (Textual), D4 (events update panels reactively)
**Exploration:** quick
**Status:** captured

## D9: LLM session handoff — CLI SPI

**Choice:** Pluggable SessionProvider SPI with multiple implementation strategies
**Alternatives:**
- Hardcode Claude CLI integration — simpler but locks to one LLM
- TUI-only, no LLM integration — user manages LLM sessions entirely separately
**Rationale:** The TUI should not be tied to any specific LLM CLI. A SessionProvider SPI defines the contract (start with issue context, track active state, signal completion). Implementations handle the mechanics: suspending to an external CLI, automating a third-party CLI via I/O, or embedding a conversation panel natively. This supports Claude, Gemini, Aider, local models, or any future CLI.
**Trade-offs:** More abstraction upfront, but the SPI is tiny (3 methods). Each implementation is self-contained.
**Depends on:** D4 (event-driven architecture — session lifecycle emits events)
**Exploration:** quick
**Status:** captured

## D10: LLM session — suspend/resume as default implementation

**Choice:** Suspend/resume as the default SessionProvider, with automated and embedded as future options
**Alternatives:**
- Automated CLI driving only — programmatically read/write to a CLI subprocess; more complex, fragile across CLI versions
- Embedded panel only — native conversation widget; most ambitious, requires deep framework integration
**Rationale:** Suspend/resume works with any CLI immediately — Textual has `app.suspend()`, Tamboui can add it via existing terminal primitives (leave alternate screen, disable raw mode, run subprocess, restore). Automated driving (reading scroll, submitting prompts) and embedded panels are higher-value but higher-effort — they become additional SPI implementations later.
**Trade-offs:** Suspend/resume loses TUI context while the CLI runs (user can't see panels). Acceptable for v1 — the TUI refreshes state on resume.
**Depends on:** D9 (SPI defines the contract), D1 (Textual supports suspend natively; Tamboui needs small extension — author is accessible)
**Exploration:** quick
**Status:** captured

## D11: Home screen — multi-repo/slot workspace manager

**Choice:** Home view as the TUI's entry point, listing all repos and slots with state
**Alternatives:**
- Single-project only — user must cd to a repo and run soredium there; no cross-project navigation
- CLI argument to select project — `soredium --project casehub/engine`; functional but not guided
**Rationale:** The user works across multiple repos and slots. A home screen that discovers and lists them all — showing branch, lifecycle state, and slot assignment — lets you pick where to work without leaving the TUI. Enter a repo/slot → lifecycle view. Escape → back to home. This is the natural `soredium` entry point: run it, see everything, pick where to work.
**Trade-offs:** Needs a discovery mechanism (configured paths or auto-scan of ~/claude/). Adds a navigation layer to the TUI (screen stack or view switching). The lifecycle view we've designed becomes one level deeper.
**Depends on:** D7 (guided UX — home screen extends the action-panel pattern to repo/slot selection), D8 (panels — home screen is another panel layout)
**Exploration:** quick
**Status:** captured

## D12: Multi-session management via tmux

**Choice:** Use tmux sessions as the multiplexing layer for concurrent CLI sessions across repos/slots
**Alternatives:**
- Single-active-context — one session at a time, go back to home to switch. Simple but loses the "see all sessions" value that makes the home screen useful.
- CLI-specific remote APIs — depend on each CLI having attach/detach support (Claude --resume, etc.). Fragile, varies per tool.
- Embedded terminal emulator per slot — run multiple CLI sessions inside TUI panels. Most ambitious, requires terminal emulation.
**Rationale:** The home screen's value is seeing "slot 3 has Claude running, slot 7 is idle" and jumping between them. Tmux is the standard solution for session multiplexing — it works with any CLI, is universally available, and handles attach/detach natively. The TUI creates named tmux sessions per slot (`tmux new-session -d -s slot-7-issue-222 claude`), shows their status on the home screen, and attaches on selection.
**Trade-offs:** Adds tmux as a runtime dependency. Users need basic tmux familiarity (Ctrl-b d to detach). The TUI suspends while attached — you can't see the home screen and a CLI session simultaneously (that would require embedded terminals, future scope).
**Depends on:** D11 (home screen provides the multi-repo/slot view), D9 (SessionProvider gets a TmuxProvider implementation alongside SuspendingProvider)
**Exploration:** quick
**Status:** captured
