---
layout: post
title: "The Workspace Gets a Workspace"
date: 2026-05-22
type: phase-update
entry_type: note
subtype: diary
projects: [cc-praxis]
tags: [workspace-init, methodology, blog-routing]
---

cc-praxis defines the workspace model. It ships the `workspace-init` skill,
documents the `proj/` and `wksp/` symlinks, and explains how methodology
artifacts should live separately from source code. What it didn't have was
a workspace of its own.

I fixed that today.

Before setting up the workspace, I addressed a small inconsistency in
`work-end`. Step 8g — blog publishing — asked before invoking `publish-blog`.
Every other artifact routing step in the same skill executes silently. One
line changed to auto-invoke instead.

Then the workspace.

Claude and I worked through the setup: public, `wsp-cc-praxis` as the GitHub
repo name, prefix style. The first push failed — `Permission denied (publickey)`.
SSH keys aren't configured on this machine. Switching the remote from
`git@github.com` to `https://github.com` fixed it immediately. Worth noting:
the error points at the push, not at the underlying auth gap.

The more interesting decision was CLAUDE.md. The file is 39KB — full project
conventions, skill architecture, pre-commit checklist, everything. I chose to
migrate it to the workspace rather than keep it in the project repo. That
appends the full content to a workspace hub file and symlinks the project's
`CLAUDE.md` back. Opening Claude in either location loads the same config.

One thing we didn't migrate: `docs/_posts/`. Those 17 posts are Jekyll source
— they publish at `mdproctor.github.io/cc-praxis/blog/` and belong in the
project. The workspace has a `blog/` staging directory now, but the existing
posts stay where they are.

That surfaced a question I haven't answered. The blog-routing config routes
`entry_type: note` entries to `mdproctor.github.io/_notes/`. Every casehub
post goes there. No cc-praxis post ever has — they live only on the project
site. Should that change? I left it open.

The workspace lives at `~/claude/public/cc-praxis/`, pushed to
`mdproctor/wsp-cc-praxis`. Navigation symlinks are in place on both sides.
