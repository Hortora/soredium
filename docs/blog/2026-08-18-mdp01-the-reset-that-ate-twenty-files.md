---
layout: post
title: "The Reset That Ate Twenty Files"
date: 2026-08-18
entry_type: note
subtype: diary
projects: [soredium]
tags: [git, safety, work-end, incident, defence-in-depth]
---

I lost a day's work last week. Twenty files — nine example pages, five mock data files, modifications to three config files — all gone. No branch. No commits. No stash. No recovery.

The mechanism was straightforward. I'd been working on a showcase gallery in blocks-ui, building pages, testing them in Playwright, iterating on bugs. Everything was on main, nothing committed. A separate session ran `work-end` on the same repo for a different issue. Work-end rebases onto upstream before merging, and git rebase needs a clean tree. The automation saw a dirty tree and cleaned it — `git reset --hard HEAD`. My files vanished.

The reflog confirmed it: `reset: moving to HEAD` right before the rebase started. No stash entry. Untracked files had never been in git's object store, so `git fsck --lost-found` couldn't help either.

## Two failures, not one

The obvious failure is that work-end destroyed uncommitted changes. But the deeper one is that hours of work accumulated on main without a single commit. I already had a feedback memory telling me to commit frequently — "WIP commits after every green test, squash later" — and it was ignored. Soft guidance that doesn't get followed is indistinguishable from no guidance at all.

The cross-session aspect is what makes this genuinely non-obvious. Each session assumes exclusive access to the working tree — an implicit contract that git doesn't enforce. When work-end sees a dirty tree and needs to rebase, it's doing exactly what it should from its own perspective. The problem is that "dirty tree from another source" is a normal state in multi-session work, not an error condition. Treating it as something to clean away is the mistake.

## The fix: three layers

Defence in depth, because any single layer can be bypassed.

**Layer 1 — Scripts stash automatically.** A `safety_stash()` function in `work_end_execute.py` now runs `git stash push -u` before every rebase and land operation. The `-u` flag catches untracked files. Named stash messages make recovery discoverable. This is unconditional — it runs even when higher-level checks say the tree should be clean.

**Layer 2 — The skill forbids destructive cleanup.** A DIRTY-TREE-PROTOCOL block in work-end's SKILL.md now mandates that only `git stash` or a `wip:` commit are acceptable for handling a dirty tree. `git reset --hard`, `git checkout -- .`, and `git clean -fd` are explicitly banned.

**Layer 3 — A Stop hook enforces commits.** A new hook fires after every response and warns if uncommitted changes exist. A global rule in my working-style says to commit after every response that creates or modifies files. The feedback memory still exists, but now it has mechanical backing.

Layer 1 is the one that would have saved my work. Layers 2 and 3 reduce the odds of needing it.

The uncomfortable part is how long the "commit frequently" guidance existed without being followed. The rule was there. The reasoning was sound. It just didn't happen. Making it mechanical — a hook that warns, a global instruction that doesn't leave room for "I'll commit when I'm done" — is the only way to close that gap. Soft rules rot. Mechanical enforcement survives contact with a long session.
