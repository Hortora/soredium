---
layout: post
title: "The function name was the design smell"
date: 2026-08-18
entry_type: note
subtype: diary
projects: [soredium]
tags: [work-slot, gitignore, design-review]
---

Slot 110's close left `.gitignore` changes scattered across squash commits. The slot setup had been writing `.mvn/maven.config` and `.mvn/slot-settings.xml` into every cloned repo's `.gitignore` — but never committing them. They'd drift through the branch as unexplained modifications until work-end swept them into the squash, where they looked like noise.

The fix seemed obvious: extract a new `ensure_gitignore_baseline()` function, have it commit its own changes, done. We wrote the spec that way. Then the decision review came back and pointed out what we'd missed.

`slot_manager.py` already had three separate functions touching `.gitignore` — `setup_maven_config()` appending patterns, `_unignore_subdir()` removing them, `_symlink_gitignored_assets()` reading them. Extracting a fourth would scatter ownership further, not consolidate it. The reviewer's alternative was better: rename `setup_maven_config()` to `setup_slot_repo()` and expand it. One function, one call pattern, no new call sites. The misleading name was the actual design smell — a function called "maven config" that was already half-managing `.gitignore` just needed an honest name and the rest of its job.

The second revision was about who commits. Every setup function in `slot_manager.py` modifies files without committing — `_exclude_symlinks`, `configure_slot_remotes`, `replicate_claude_md`, all of them. We'd proposed making `ensure_gitignore_baseline` the first one that commits internally. The reviewer asked: why should gitignore be the exception? The callers (`create_slot`, `add_repo`) already know the lifecycle context. They should own the commit. This keeps tests lightweight — `tmp_path` and a text file, no git repo scaffolding.

The spec review caught a subtler problem. The existing code used Python's `in` operator to check whether a pattern exists in `.gitignore` — `if e not in content`. That works fine for `.mvn/maven.config`. It breaks for the new patterns: `.claude` is a substring of `.claude/`. If a repo already has `.claude/` in its `.gitignore`, the substring check reports `.claude` as present and skips it. We need both forms because git's trailing-slash patterns match directories only, silently skipping symlinks. Line-by-line matching with a set of stripped lines fixes both problems at once.

The implementation landed in two commits. `setup_slot_repo()` now ensures six baseline patterns exist — the two Maven files plus `.worktrees` and `.claude` in both bare and trailing-slash forms. The callers commit a `chore:` message that git-squash will fold into the first real work commit at work-end. The whole thing is idempotent — repos that already have the patterns get no commit at all.

What made this interesting wasn't the code — it was watching the decision review catch something the brainstorming missed. "Extract a new function" felt clean and principled. "Rename the existing function" felt like a compromise. It was the opposite: the rename consolidated ownership while the extraction would have fragmented it. Sometimes the less dramatic change is the better design.
