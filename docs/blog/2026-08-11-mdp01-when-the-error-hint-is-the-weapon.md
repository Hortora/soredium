---
layout: post
title: "When the Error Hint Is the Weapon"
date: 2026-08-11
entry_type: note
subtype: diary
projects: [soredium]
tags: [slots, safety, defensive-design, ctx]
---

A slot got deleted. Not archived — deleted. The safety net that exists precisely for the case where everything else goes wrong was permanently destroyed because a CLI error message helpfully suggested `--force-delete` and a Claude session followed the suggestion.

The error path was textbook defensive design failure. `remove-slot` refused to archive without a `.landed` marker — correct. The error message then said: `HINT=pass --force-delete to override`. Claude read the hint, described it to me as "force archive," and I approved what I thought was a safe operation. The slot was gone before either of us realised the flag meant permanent destruction, not forced archival.

The slot's data was safe — all work had been pushed to the original repos before removal. But the clone itself was the backup copy. Deleting it removed the last-resort recovery path.

I fixed this in three layers, because one fix prevents a recurrence but three fixes prevent a class of failure.

**Layer 1: remove the gun.** `remove_slot()` no longer has a permanent deletion code path. `--force-delete` is now an alias for `--force` — it skips the `.landed` check but still archives to `slots/attic/`. There is no flag that destroys a slot.

**Layer 2: block the workaround.** A PreToolUse hook intercepts any `rm -rf` targeting a `slots/` directory. Even if someone writes a raw `rm` command instead of going through `slot_manager`, the hook catches it. Only I can bypass it via `!` prefix.

**Layer 3: fix the upstream cause.** The reason work-end wasn't running properly in slots — which led to the manual cleanup that led to the deletion — was that `ctx.py` reported `SINGLE_REPO=yes` inside slot clones. The wksp symlink pointed to a workspace subdirectory (`../work/engine`), not a git root. The resolution function saw a valid directory without a `.git` and returned `None`. The fix: walk up to verify the target is inside a git repo, then return the subdirectory path itself — not the git root, because `.meta` lives at the subdirectory level.

That last detail matters. An earlier partial fix returned the git root instead of the subdirectory, which would have fixed the `SINGLE_REPO` detection but broken `.meta` resolution — looking for `work/design/.meta` when the scaffold is at `work/engine/design/.meta`. The correct answer isn't "find the nearest git root." It's "confirm this path is inside a git repo, then use the path the symlink actually points to."

The broader lesson: error hints in CLI tools are instructions to AI agents. A human reads `HINT=pass --force-delete` and thinks "that sounds dangerous, let me check what it does." An LLM reads it as the tool's own recommendation for how to proceed. The safest API is one where the destructive option doesn't exist — not one where it exists but is documented as dangerous.
