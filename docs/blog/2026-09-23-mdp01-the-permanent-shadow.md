---
layout: post
title: "The Permanent Shadow"
date: 2026-09-23
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [slots, clone, family-repos, workflow]
---

# The Permanent Shadow

I've been losing work to a problem that shouldn't exist. The canonical repo — the one cloned from GitHub, the one that holds main — is also where I do all my daily work. Another Claude session running `work-end` on a different branch can `git reset` or `git checkout` in that same directory, and anything uncommitted is gone.

The fix is obvious once you name it: stop working in the canonical. Give every repo in a family a permanent clone — a local `git clone --local` that shares objects with the canonical via hardlinks, costs almost nothing on disk, and is where all solo work happens. The canonical stays on main permanently.

The mental model becomes three tiers. The canonical is the reference shelf — you pull from it, you don't work on it. The clone is your workbench — you branch, commit, and push from here. Numbered slots are still there for the 10% case where you need genuinely parallel cross-repo work.

I started with the question of whether to invert the directory structure — put clones at the top level and push canonicals into a subdirectory, since you spend 90% of your time in the clone. But the tooling cost of that inversion outweighed the ergonomic gain. Instead: `casehub/clone/engine/` alongside `casehub/engine/`, with `casehub/slots/` for the numbered slots.

The implementation has three layers. Topology detection in `ctx.py` now recognises two new states: `IN_CLONE` (you're inside a `clone/` directory whose grandparent has `slots/`) and `IN_CANONICAL_FAMILY` (you're in a canonical repo that belongs to a family). A new `clone_manager.py` handles creation, status checks, and per-repo decline persistence. And `work-start` gained a clone redirect step — when it detects you're in a canonical, it offers to create or redirect to the clone.

The whole feature ships disabled. A `clone_enabled` flag in `settings.json` gates it system-wide. I want to live with the detection layer for a while before turning it on — making sure `ctx.py` correctly identifies canonicals and clones across all the family layouts before any session starts auto-redirecting. When it's ready, one config change turns it on everywhere.

The laziness is deliberate. No bulk clone on family setup. No eager creation of 36 clones for repos you might never touch. The clone for a repo is created the first time you try to work in it — or on demand if you ask for it.
