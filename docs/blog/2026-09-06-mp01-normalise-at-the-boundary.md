---
layout: post
title: "Normalise at the Boundary"
date: 2026-09-06
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [topology, workspace, monorepo, architecture]
series: issue-333-subfolder-scoped-workspaces
---

# Normalise at the Boundary

Soredium's workspace model assumed one thing from the start: a project IS a git repo root. `topology.py` resolves symlinks, finds `.git`, and calls that the project. `ctx.py` reads CLAUDE.md from that location. Every downstream consumer gets one path and uses it for everything — git operations, config, artifact scoping.

This falls apart the moment a monorepo enters the picture. A container repo like quarkmind has multiple independent apps sharing one git repo. Each app needs its own workspace, its own CLAUDE.md, its own session scope. But the pipeline has no concept of "project scope" distinct from "git root."

The first instinct was to add a flag — `IN_SUBFOLDER=yes` — and let consumers branch on it. But that's the wrong abstraction. Every consumer would need a conditional: "if subfolder, read from scope; else, read from git root." Scattered switches. Multiple code paths. The kind of thing that works until someone writes a new consumer and forgets the check.

The principle that sharpened the design: **there is no subfolder mode.** There is always a project scope and a git root. Sometimes they happen to be the same directory. The pipeline doesn't know or care.

This reframing eliminated every conditional. `Topology` gained one field: `git_root`. The existing `project` field kept its name but refined its meaning — it's now "the project scope," which for single-repo projects is identical to the git root. `ctx.py` always reads two CLAUDE.md files (scope and root) and merges them. For single-repo, both reads hit the same file, so the merge is a no-op. Same code path, same result, zero behavioral change.

The symlink search needed restructuring too. The old code checked for `wksp/` at the git root. When your app folder is `quarkmind/apps/foo/` with `wksp/` right there, the old search looks at `quarkmind/` and finds nothing. The fix: walk up from CWD toward the git root, checking each directory for symlinks. Same pattern as how git finds `.git`. CWD wins over root — if both have `wksp/`, the closer one takes precedence.

One sharp finding from the adversarial review: `git -C $PROJECT add .` from a subfolder only stages files in that subfolder. If a session modifies a root-level file (parent pom dependency), the staging silently misses it. This isn't a "gradual migration" — consumers that stage or diff MUST use `$GIT_ROOT`. The spec was updated to mark this as mandatory, not cosmetic.

Another subtlety: the CLAUDE.md merge uses `is not None`, not Python's `or`. An app that sets `Blog directory:` to empty (intentionally no blog) shouldn't inherit the root's blog directory. `or` treats empty strings as falsy and falls through. `is not None` distinguishes "field present but empty" from "field absent."

The workspace-init side is straightforward. When CWD is inside a git repo but not the root, offer to scope the workspace. After setup, the symlinks encode the decision. The pipeline is uniform from that point forward.

What makes this interesting beyond the specific feature: the "normalise at the boundary" principle is applicable whenever you're tempted to add a mode flag. If you can make the inputs uniform early, the pipeline stays clean. The flag approach is seductive because it's local — you add one check, it works for your case. But it distributes the complexity across every consumer, forever. Normalising is more work upfront and less work in total.

The consumer skill updates — making work-start, work-end, and git-commit use `$GIT_ROOT` for git operations — are the next step. The infrastructure is in place; the wiring is what turns it into a usable feature.
