---
layout: post
title: "Nine stubs and a protocol"
date: 2026-08-12
entry_type: note
subtype: diary
projects: [soredium]
tags: [tui, session-spi, cli, architecture, lifecycle]
series: issue-222-repl-shell
---

*Continues from [The Textual that bites back](2026-08-12-mdp01-the-textual-that-bites-back.md).*

The prior entry ended with session providers and the CLI entry point being next. They turned out to be the simplest parts of the build — and the ones that revealed the biggest gap.

The Session SPI had an async protocol in the spec: `async def start()`, `async def stop()`. Implementation revealed the spec was wrong. Both providers do the same thing at the terminal level: block. TmuxProvider runs `tmux attach-session` — blocks until the user detaches. SuspendingProvider runs `subprocess.run(["claude"])` — blocks until claude exits. Neither is meaningfully async. The terminal can only belong to one process at a time, and yielding it is inherently synchronous.

The fix: drop async, add a `run()` method. `start()` prepares — creates the tmux session or stores context. `run()` blocks — attaches or launches. The app calls `start()`, then `with self.suspend(): provider.run()`, then refreshes state. The terminal yields, the subprocess owns it, the terminal returns. Auto-detection is a single check: if tmux is on PATH, use TmuxProvider; otherwise fall back to SuspendingProvider.

The CLI was simpler still. Parse a command name, import the module, call `execute()`, emit each returned event as a JSON line to stdout. `soredium status` produces `{"type": "StatusReady", "branch": "issue-42", "state": "active", ...}`. Exit codes: 0 success, 1 command failure, 2 bad arguments. Any tool that reads lines can drive the lifecycle.

Both went fast. And that's when the gap became visible.

The TUI renders. The Home View discovers repos. The Project View shows actions derived from the lifecycle state. The Session SPI yields the terminal to tmux or claude. The CLI emits JSON. But run any state-changing command — start, next, end, resume — and nothing happens. The command modules have the right signatures, the right imports, the right error guards. They return empty event lists.

The architecture is complete. The commands are hollow.

What's missing is the lifecycle three-phase protocol — the glue between commands and scripts. Every state-changing command needs it: `transition()` validates the move, effects call the refactored script APIs, `commit_transition()` writes atomically. Without it, nothing fires. That's the bottleneck. Eight child issues cover the remaining work; the protocol is the serial dependency that everything else fans out from. Three independent tracks — read-only commands, concurrency, config loading — can run in parallel, but the critical path is protocol, then wiring, then integration tests.

The Python TUI was always a stepping stone — validate the architecture, then port to Quarkus native via Tamboui. The architecture is validated. The question now is whether to finish wiring the Python commands first or start the Java port against the proven event model.
