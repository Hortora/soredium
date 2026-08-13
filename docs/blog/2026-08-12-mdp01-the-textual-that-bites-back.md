---
layout: post
title: "The Textual that bites back"
date: 2026-08-12
entry_type: note
subtype: diary
projects: [soredium]
tags: [tui, textual, testing, focus-model, workspace-manager]
series: issue-222-repl-shell
---

*Continues from [Soredium without the LLM](2026-08-11-mdp02-soredium-without-the-llm.md).*

The command layer existed. The events existed. The refactored scripts had typed results. Time to build the thing people would actually see.

Textual's widget tree mapped to the design almost directly. `HeaderBar` renders branch, state, and queue position. `ActionPanel` lists valid actions and handles keyboard navigation. `ContentArea` formats event output — briefs, step progress, errors, recommendations. `FooterBar` switches keybinding hints by mode. `SorediumApp` composes them, connects to the command layer, and runs commands in workers to keep the UI responsive.

The first interesting discovery was about focus. I had up/down bindings on the app for action panel navigation. They never fired. The `ContentArea` — a `RichLog` — has built-in `scroll_down` and `scroll_up` bindings that consume the keys before anything else sees them. The Textual focus model routes key events to the focused widget first, and the `RichLog` was winning. The fix was giving the `ActionPanel` its own `can_focus = True` and `BINDINGS`, then focusing it on mount. App-level bindings aren't global overrides — they're fallbacks.

The second was a naming collision. I called a method `_dispatch_action` on the app. Textual has an internal method with the same name but a different signature: `_dispatch_action(target, action_name, params)`. No warning at definition time. The app started fine. Then pressing any key produced `TypeError: takes 2 positional arguments but 4 were given`. The traceback pointed into Textual internals, not my code. Renaming to `_handle_action` fixed it. The lesson: treat `_dispatch_*` and `_check_*` as reserved prefixes on Textual App subclasses.

Both of these cost more time than they should have. The behaviour is internally consistent — widgets own their bindings, internal methods exist on the class — but nothing in the docs warns you. Textual's API surface is large enough that name collisions and focus routing are real hazards once you move beyond single-widget examples.

The third finding was about testability. Textual's `reactive` properties need a mounted widget to function. That pushes every test through `async with app.run_test()`, which takes half a second per test. I wanted faster feedback during TDD. The solution: plain instance variables and a `_build_display()` method that returns the rendered text. Unit tests instantiate the widget directly, call `_build_display()` or `move_down()`, assert against the result. No Textual infrastructure needed. Integration tests use the full app test framework with mocked backends. Two tiers: unit tests at ten milliseconds each for the widget logic, integration tests at half a second for the composed app.

After the Project View, the Home View. A discovery module scans configured paths for directories containing `.git` and `CLAUDE.md`, and for slot directories with `.slot` markers. Each discovered repo or slot gets a context resolution — branch, lifecycle state, issue number, tmux session status. The `HomeView` widget renders the list with session indicators: filled circle for running tmux sessions, half-circle for paused, empty for idle. Enter a repo to switch to the Project View. Escape to go back. When no `cwd` is provided, the app starts in Home View. With a `cwd`, it goes straight to Project View — the natural behaviour for launching from inside a project.

Between the two tasks, a detour through the test suite. Forty-seven failures across thirteen test files — stale test files for deleted scripts, marketplace.json drift, missing skill cross-references, a terminology violation, an incomplete function in the epic manager. The kind of accumulated debt that passes unnoticed when each session touches different files. Fixing them all at once was the right call. The epic manager fix was the only code change with real substance: `advance()` accepted a `meta_path` parameter but never used it to update the covers list. The test was right; the implementation was incomplete.

The TUI is taking shape as a workspace manager, not just a lifecycle tool. The home screen shows every repo and slot at a glance. The project view shows exactly what you can do and highlights what you should do next. No commands to memorise, no state to query manually. The command layer underneath doesn't care whether it's being driven by the TUI, the stateless CLI, or a future Java port — it just executes transitions and emits events.

Session providers and the CLI entry point are next. That's where the TUI stops being a standalone tool and becomes a launcher for LLM sessions — the bridge between the mechanical lifecycle and the reasoning work that still needs a model.
