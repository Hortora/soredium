---
title: "The parent that ate the children"
date: 2026-08-20
author: mdp
entry_type: note
subtype: diary
projects: [soredium]
series: issue-255-slot-workspace-convergence
tags: [slots, workspace, git, migration, architecture]
---

# The parent that ate the children

Slot 138 had three repos — connectors, pages, examples — but one workspace clone for all of them. Plans and specs floated in ambiguous directories. The session in slot 138 didn't know it could write to pages. And when I asked where connectors' specs go, nobody could give a straight answer: `work-casehub/specs/` or `work-casehub/connectors/specs/`?

That's not a slot 138 problem. That's a workspace model problem.

## The N:1 that should have been 1:1

Outside slots, workspace-init creates separate git repos per project. `connectors` gets `wsp-casehub-connectors`. `pages` gets `wsp-casehub-pages`. Each project's `wksp` symlink points to its own workspace repo. Clean, independent, unambiguous.

Slots didn't do this. `create_slot` called `resolve_workspace_source`, which walked up to find the workspace repo. And there was the bug: it checked `parent/.git` before `target/.git`. Since `~/claude/public/casehub/` is itself a git repo, every child workspace repo — connectors, pages, examples, all of them — resolved to the parent. One clone for the entire family.

```python
target = wksp.resolve()           # ~/claude/public/casehub/connectors
parent = target.parent            # ~/claude/public/casehub/
if (parent / ".git").exists():    # TRUE
    return parent, "work"         # Returns the PARENT — wrong
```

The 1:1 mapping existed on disk. The code produced an N:1 mapping. The deduplication logic in `create_slot` (`ws_created` dict) was there specifically to handle the bug's consequences — without it, the same parent repo would get cloned once per project and fail on the second attempt.

The fix is one line: `git rev-parse --show-toplevel` instead of walking `.git` directories manually. Git already knows how to resolve to the nearest enclosing repo. We were outsmarting it.

## Fixing the structure, not the symptoms

Fixing `resolve_workspace_source` makes new slots correct. But 21 active slots and a full attic have the old structure. And every skill that touches workspace paths — work-end, work-start, topology detection, promotion, squash, merge — has conditional branches for "am I in a slot?" Twelve divergence points in work-end alone.

The design decision that shaped everything: no two code paths. We'd seen what happens when slot-specific logic accumulates — unreliable behaviour, confused sessions, ambiguous artifact placement. The convergence has to be absolute: a skill follows `wksp` and sees an identical workspace directory, whether it's in a slot or not.

The migration uses `format-patch --relative` to extract subdirectory-scoped commits from the family workspace clone and replay them into fresh per-repo clones. Cross-subdirectory commits produce partial patches — each repo gets its changes, atomicity across repos isn't preserved. Acceptable because workspace artifacts don't have cross-repo transactional dependencies.

For active slots with loaded sessions, symlink bridges keep old paths resolving. The family workspace clone stays as a shell with symlinks — old sessions see the same paths, writes land in the new per-repo clones through the symlinks.

## The convergence

The hardest part wasn't the detection fix or the migration. It was `merge_slot` — 300 lines of orchestration that processed project repos through a two-hop push (clone → original → GitHub) while explicitly skipping workspace repos. `cmd_land` in branch mode did the opposite: it handled workspace merge and stamp inline but had no two-hop path. Twelve divergence points, two separate orchestrators, neither complete.

The shared flow inverts the abstraction. Instead of branching on topology inside the flow, each topology constructs a batch of descriptors — repo path, original path, push target, transport type — and the flow processes them uniformly. Slot mode builds `TWO_HOP` descriptors. Branch mode builds `DIRECT` descriptors. The five steps (preflight, rebase, merge, push, stamp) don't know the difference.

`merge_slot` went from 300 lines of inline git commands to a dozen lines: build batch, call `land_batch`, write the `.landed` marker. `cmd_land` shrank similarly. Workspace repos are no longer skipped in slot mode — they go through the same flow as project repos, getting merged, pushed, and stamped for the first time.

## What this means

The workspace model is consistent from creation through close. A skill follows `wksp` and finds a workspace — slot or not. The twelve conditional branches in work-end collapsed into a transport flag on a dataclass. The transition code stays for fourteen days while old slots catch up; after that, detection simplifies to checking a single `.workspace` marker file.

The naming question resolved itself along the way. `work-casehub` could be anything. `wsp-casehub-connectors` can only be one thing. Identity over convention — which is what structural markers are, too.
