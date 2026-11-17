# Audit findings the work-end rewrite must address

Compiled from the 2026-11-16 workend auditor session. These are failure
patterns observed in production, not theoretical risks.

---

## 1. Promotion fails silently, landing succeeds anyway

**Pattern:** Work-end promotes artifacts (specs, blogs, images) as a
separate step from landing. If promotion fails — pre-push hook rejects,
merge conflict, session interrupted — the landing still succeeds. The
branch gets stamped "closed." The slot gets archived. The blog sits in
the workspace forever.

**Evidence:** 48 workspace blogs + 36 spec dirs found stuck mid-pipeline
across 7 repos. Additionally 62 blogs were published to blog sites but
never copied to project `docs/blog/`. Every audit session since August
2026 has found more stranded content.

**What the rewrite must do:** Promotion must either be atomic with
landing, or landing must refuse to complete without a promotion stamp.
"Promoted but not verified" is the same as "not promoted."

---

## 2. Promotion deletes source before verifying destination

**Pattern:** `close_artifacts.py` deletes the workspace source file
after copying it to the destination. If the destination write fails
(directory doesn't exist, git commit fails), the file is gone from both
locations. See soredium#483.

**What the rewrite must do:** Verify the destination has the file before
removing the source. Or don't remove the source at all — let workspace
cleanup handle it.

---

## 3. Sessions don't understand "canonical" vs "origin"

**Pattern:** Slot clones have three remotes: `local` (canonical repo on
disk), `origin` (GitHub fork), `upstream` (GitHub blessed). When asked
to "sync to canonical," sessions compare against `origin` and report
"0 ahead" while canonical on disk is hundreds of commits behind.

**Evidence:** Slot 196 session reported "all 8 repos synced" with a
table showing "ahead=0 behind=0" for every repo. Actual state: 271
neocortex commits, 529 agency workspace commits, 1082 neocortex
workspace commits ahead of canonical.

**What the rewrite must do:** The two-verb model (land = disk, publish =
network) addresses this. But also: slot clones should not have GitHub
remotes at all (#515 stage 2). With only `local`, there's nowhere to
push except canonical, and "sync" becomes unambiguous.

---

## 4. `local/main` tracking refs go stale

**Pattern:** When a slot clone pushes to `local` (canonical), the push
updates canonical's working tree via `updateInstead`. But the slot
clone's `local/main` tracking ref is NOT updated — it still points to
whatever it was at clone time. Any check using
`git log local/main..HEAD` reports false divergence.

**Evidence:** The auditor reported slots as "not synced" when they
actually were. The sessions had pushed to `local` correctly, but the
tracking ref was stale. Only after `git fetch local` did the ahead
count drop to 0.

**What the rewrite must do:** After every push to `local`, run
`git fetch local` to update the tracking ref. Or use a different
verification method that doesn't rely on the tracking ref.

---

## 5. Post-commit hook pushed to GitHub — accidental safety net

**Pattern:** `install_post_commit_hook()` adds
`git push -u origin HEAD 2>/dev/null || true` to every slot clone.
This pushes every commit (including workspace blogs, specs) to GitHub
immediately. It was designed for slot-to-GitHub sync, but it
accidentally created a backup of workspace content on GitHub.

**Evidence:** When 186 attic slot directories were deleted (Nov 9
incident), all content was recoverable because the hook had pushed it
to GitHub. Canonical repos had fetched from GitHub, bringing the objects
locally. `pin_rescue.py` pinned 10,683 unreachable commits. Recovery
agents extracted 113 blogs + 496 specs + 144 images.

**Tradeoff:** The hook also causes squash divergence. Every WIP commit
is on GitHub. After squash-merge, the feature branch has different SHAs
than main. Audit tools see false divergence. The recovery inventory
inflated from 950 real candidates to 13,119 because of this.

**What the rewrite must decide:** If slot clones lose GitHub remotes
(#515 stage 2), the hook stops working. The safety net disappears.
Content is on canonical disk only until `publish` runs. If the machine
dies between `land` and `publish`, workspace content not yet landed or
published is at risk. The `land` command must push workspace content to
canonical — not just project code.

---

## 6. `|| true` swallows push failures

**Pattern:** The post-commit hook uses `|| true`, so push failures are
silent. If the network is down, auth expires, or rate limiting kicks in,
the commit stays local-only with no indication of failure.

**What the rewrite must do:** Any push that serves as a backup or sync
mechanism must report failures, not swallow them. If `land` pushes to
canonical and it fails, that's a hard error — not something to continue
past.

---

## 7. Workspace content is the vulnerable layer, not project code

**Pattern:** Project code lands via squash-merge to main and gets pushed
to GitHub mechanically. The landing path is well-tested. Workspace
content (blogs, specs, design docs, plans) depends on a separate
promotion step that has historically been the weak link.

**Evidence:** Every recovery effort has found workspace artifacts, never
project code. The 113 recovered blogs, 496 specs, and 144 images were
all workspace content. Project code was always on main.

**What the rewrite must do:** Workspace content must travel the same
reliable path as project code. The current design has two separate
paths with different reliability levels — one mechanical (code landing),
one fragile (artifact promotion). The rewrite should unify them or make
the artifact path equally mechanical.

---

## 8. The protect-slots.sh hook was a no-op

**Pattern:** The hook used the wrong JSON key (`input` instead of
`tool_input`) and wrong exit behavior (`exit 0` + stdout instead of
`exit 2` + stderr). It printed "BLOCK" to stdout but Claude Code
ignores stdout from PreToolUse hooks — only stderr + non-zero exit
actually blocks.

**Evidence:** The hook was deployed and "working" for months. It never
blocked a single command. The attic deletion went through it without
resistance.

**Lesson for the rewrite:** Any hook that guards against destructive
operations must be tested end-to-end by actually attempting the
destructive operation and verifying the block. Printing "BLOCK" is
not blocking.

---

## 9. Archive must hard-stop on live Claude Code sessions

**Pattern:** `archive_slot()` moves the slot directory to attic.
If a Claude Code session is running in the slot, its conversation
history writes start failing silently (CWD moved out from under it).
`--force` previously bypassed the active-session check.

**Fix already landed:** `is_claude_session()` in `slot_claude.py`
detects Claude Code processes (Electron version-string pattern like
`2.1.325`). In `archive_slot()`, Claude sessions are now a hard stop
that `--force` cannot bypass. Non-Claude processes (node, zsh) remain
force-bypassable.

**What the rewrite must preserve:** This guard must survive the rewrite.
Any operation that moves or deletes a slot directory must check for live
Claude Code sessions first, unconditionally.

---

## 10. Transient filesystem scanners cause false session detections

**Pattern:** `find_active_sessions()` uses `lsof +D` to find processes
with open file descriptors in a slot. Filesystem scanners (`bfs`,
Spotlight, Time Machine) transiently appear in the results. On the
first archive attempt they look like active sessions; on retry they're
gone.

**Evidence:** `bfs` appeared as PID 10692 during slot 222 archive
attempt, identified as a Claude session by the version-string regex.
Retry succeeded because the scanner had moved on.

**What the rewrite should do:** Retry once after a short delay if the
only active sessions are non-Claude processes. Or filter out known
scanner process names.

---

## 11. DB state drifts from disk reality

**Pattern:** Work-end records events in the worklog DB, but not all
state transitions are recorded. `work_items.state` never transitions
to "ended." `slot-phase-a` events are rarely recorded. If work-end
fails between DB write and disk write, DB leads disk.

**Evidence:** Slot 220 was archived by another session but DB still
said `active`. Manual DB update was required.

**What the rewrite must do:** DB writes and disk writes should be
paired — if one fails, the other is rolled back or at least flagged.
The DB should never be ahead of disk reality.

---

## Related soredium issues

| Issue | Topic |
|-------|-------|
| #523 | Artifact tracking in worklog DB |
| #528 | sync-slot command |
| #515 | Canonical sync / one landing flow |
| #483 | Promotion deletes before verifying |
| #246 | Forced audit at work-end |
| #270 | Slot resolution tracking |
| #323 | Slot checkpoint at batch boundaries |
| #472 | Cross-repo issue hygiene at close |
| #182 | Work observability pipeline |
