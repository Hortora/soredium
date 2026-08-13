---
layout: post
title: "Soredium without the LLM"
date: 2026-08-11
entry_type: note
subtype: diary
projects: [soredium]
tags: [tui, cli, architecture, textual, tamboui]
---

Someone asked: can I follow the soredium workflow without an LLM?

The answer turned out to be more interesting than expected. Yes, for the mechanics — start a branch, advance through a plan queue, pause mid-work, resume later, close and land the branch. These operations are already Python scripts. `ctx.py` resolves context, `lifecycle.py` manages state transitions, `plan_manager.py` tracks issue queues. The LLM orchestrates the sequence today, but the sequence itself is mechanical.

No, for the reasoning — sweeps that scan conversation memory for knowledge worth preserving, adversarial design reviews, narrative synthesis, code review that understands intent. Those need a model. But they're the minority of operations in a typical session.

The question led somewhere I hadn't planned. Instead of a traditional REPL, we designed a panel-based TUI — persistent header showing branch and state, an action panel on the left listing only what's valid right now, a content area on the right showing the last command's output. No typing commands. Arrow keys and Enter. The lifecycle state machine already knows which transitions are legal from any state; the action panel derives directly from it. If you're on an active branch with a queue, you see `next`, `pause`, `end`, `session`. On main with nothing running, you see `start`, `what-next`. The user never has to guess.

The deeper design question was portability. I want this in Python now (using Textual) and in Java later (using Tamboui, a new TUI framework with CSS theming and a three-layer API that maps well to Textual's model). That ruled out coupling the orchestration to the UI. The architecture landed on three layers: a command layer that calls refactored scripts and emits typed events, a TUI that subscribes and renders, and a session SPI that handles LLM CLI handoff.

The session SPI is where it gets interesting. The TUI needs to launch an LLM session for the reasoning work — but it shouldn't be tied to any specific CLI. Claude, Aider, Gemini, a local model. The solution: tmux as a universal session multiplexer. The TUI creates named tmux sessions per repo and slot, shows their status on a home screen, and attaches by suspending itself and handing terminal control to tmux. Detach returns to the TUI. The CLI doesn't know it's being managed — tmux handles the complexity.

That home screen became the natural entry point. Run `soredium`, see every repo and slot across the workspace — which ones have active branches, which have running LLM sessions, which are idle. Enter one to see its lifecycle view. This is a workspace manager, not just a project tool.

The event-driven command layer is the piece I'm most interested in watching evolve. Every state-changing command emits typed dataclass events — `BranchCreated`, `PlanAdvanced`, `WorkEnded`, `CommandFailed`. The TUI subscribes. The stateless CLI prints them as JSON Lines. The Java port reimplements the commands natively; the events are the contract. It's the kind of boundary that makes porting mechanical rather than creative.

The foundation is built — events module, script refactoring for importable library APIs across fifteen scripts, and the full command layer with action derivation. The TUI itself is next. I'm curious whether the Textual widget tree maps as cleanly to Tamboui's toolkit as I expect, or whether the Java port will surface assumptions baked into the Python side.
