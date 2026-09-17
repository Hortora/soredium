---
layout: post
title: "Killing a one-character confusion: original → canonical"
date: 2026-09-17
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [slots, naming, llm-semantics]
---

Slot infrastructure uses cloned repos that point back to a shared local copy — the authoritative source. That copy was called the "original" everywhere: `resolve_original_repo`, `original_path`, `check_original_sync`, error strings, SKILL.md documentation.

The problem is that "original" and "origin" are one character apart, share the same Latin root, and collide in the same git context. When a skill says "push to the original's main", the LLM reads `git push origin main`. It's not a reasoning failure — it's a semantic proximity problem. The model's prior on `origin` as a git remote overwhelms the intended meaning of "original" as "the shared local clone." This was showing up repeatedly in slot close sequences, where the two-hop push path (`clone → original → remote`) was being collapsed into a single-hop push (`clone → origin`).

The fix is a rename: `original` → `canonical`. "Canonical" means the authoritative local copy and has zero collision with any git concept. It's distinctive enough that no amount of git-context priming will conflate it with a remote name.

The rename itself was mechanical — 23 files, 363 lines in each direction, zero logic changes. Production code across `work-slot/`, `work-end/`, `verification/`, and `scripts/`. Tests mirroring every production change. The scope rule was straightforward: rename anything that refers to the slot concept of "the authoritative local repo," leave alone anything that uses "original" in general English ("original branch" meaning the branch we were on before, "original content" meaning previous content).

The interesting question is whether this generalises. LLM-facing code has a constraint that human-only code doesn't: identifier names need to be semantically distant from other terms in the same domain. In human code, `original` is fine because a developer reads the variable declaration and builds a mental model. An LLM processes the token in context, and when the context is saturated with git terminology, "original" gets pulled toward "origin" by attention weight. This isn't unique to this case — any identifier that's one edit-distance away from a high-frequency domain term is a candidate for the same confusion.

Worth watching for the pattern elsewhere: if a slot session misroutes a push or a merge, check whether the identifier names are too close to the git vocabulary the model already knows.
