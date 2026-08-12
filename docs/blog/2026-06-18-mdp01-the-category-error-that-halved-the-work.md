---
layout: post
title: "The Category Error That Halved the Work"
date: 2026-06-18
type: phase-update
entry_type: note
subtype: diary
projects: [cc-praxis]
tags: [externalisation, ctx-py, architecture, permissions]
---

The original plan was to extract 18 embedded bash blocks from 7 skill files. An audit found 294 across 27. At that point the question shifted from "which blocks" to "what's actually in those blocks?"

Most of them were one-liners. A `grep` for the project type. An `ls` to check if a file exists. A `git log` to count unpushed commits. Individually trivial — but each one triggers a permission prompt, each one loads into the context window, and each one is token cost the LLM pays without gaining anything. The bash block is there because the skill was written as a sequence of commands. The LLM doesn't need to see `grep "## Project Type" CLAUDE.md` — it needs the answer.

That observation splits the problem cleanly. There are blocks where the LLM needs the *result* (data lookups), and blocks where the LLM needs the *side effect* (write operations). The first category goes into ctx.py — the shared context script that already handles path resolution. The second goes into per-skill Python scripts.

The interesting design moment was the "contextual" question. Some blocks look like they can't be extracted — `git commit -m "<message the LLM writes>"`, or `gh issue create --body "<content the LLM generates>"`. The message is contextual, surely? But the commit operation isn't. The LLM generates the message (reasoning), then a script runs the commit (execution). Every block decomposes this way. There is no block where the execution itself requires judgment. Judgment applies to inputs and outputs — never to the act of running a command.

Once that category error is resolved, the architecture falls out naturally. ctx.py absorbs 85 cheap lookups — project type, issue tracking status, file existence checks, config parsing. Fourteen new fields, all local file reads, total runtime under 10ms. That single script expansion eliminates more blocks than all the per-skill scripts combined.

The per-skill scripts handle the write operations: git commit sequences, GitHub API calls, file creation, branch swaps. Eleven skills got scripts. Four didn't — their remaining operations (a single `git add + commit` or `gh issue create`) were too thin to justify a script with argument parsing, error handling, and tests. The threshold crystallised as a rule: three or more operations get a script, one or two in a rarely-used skill get inlined.

The result is what the skill files should have been from the start: pure workflow guidance. Decision trees, user messages, reasoning steps. No mechanical code. No permission prompts. Skills load faster because they're shorter. The LLM focuses on what to do, not how to run a command.

Between ctx.py, the eleven per-skill scripts, and the four skills whose blocks dissolved into ctx.py entirely, project-init is quietly becoming a Python runtime for the whole skill ecosystem. That's a different thing than it started as — worth watching whether it stays clean or starts accumulating responsibilities it shouldn't have.
