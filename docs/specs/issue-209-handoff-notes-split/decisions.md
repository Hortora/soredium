# Decisions — issue-209-handoff-notes-split

## D1: NOTES.md lives on an orphan branch in a permanent worktree

**Choice:** `$WORKSPACE/.notes/NOTES.md` on an orphan `notes` branch, checked out via `git worktree add --orphan`.
**Alternatives:**
- Gitignored file — no merge conflicts but no history. Rejected: notes accumulate over months; history is worth having.
- Tracked on main — merge conflicts when multiple slots modify it. Rejected: the problem that started this issue.
- Branch-scoped (in `design/`) — cleaned up at work-end. Rejected: notes persist across branches.
**Rationale:** Orphan branch has no shared history with main or feature branches — merge conflicts are impossible by design. Same pattern as gh-pages. Git 2.42+ has `git worktree add --orphan` as a single command.
**Trade-offs:** One extra worktree per workspace. Trivial disk cost (shared object store).
**Exploration:** deep-analysis
**Status:** captured

## D2: Read NOTES.md when deciding what to do, not when already tasked

**Choice:** Surface notes in what-next mode (`work` with no issue), after work-end, and in `/brief`. Don't surface during `work start #N` or `work continue`.
**Alternatives:**
- Always at session start — noise when you already have a task. Rejected.
- Only on demand — notes are invisible and forgotten. Rejected.
**Rationale:** Notes are context for "what should I do?" moments, not for "I know what I'm doing" moments.
**Trade-offs:** Notes not visible when deep in a task. Acceptable — if it's urgent, it should be an issue.
**Exploration:** quick
**Status:** captured

## D3: Default ON in wrap checklist

**Choice:** Flip handover item 8 from `[ ]` to `[x]`.
**Alternatives:**
- Keep OFF — notes never get captured. Rejected: defeats the purpose.
**Rationale:** The prompt is light ("anything to note for later?"). User can skip with Enter.
**Trade-offs:** One extra prompt at wrap time.
**Exploration:** quick
**Status:** captured

## D4: workspace-init creates the notes worktree

**Choice:** `workspace-init` creates the orphan branch and worktree as part of one-time workspace setup.
**Alternatives:**
- Manual setup — users forget. Rejected.
- Lazy creation on first write — adds complexity to every write path. Rejected.
**Rationale:** One-time setup belongs in workspace-init. Same place that creates the workspace repo, symlinks, and CLAUDE.md.
**Trade-offs:** workspace-init gets one more step.
**Exploration:** quick
**Status:** captured

## D5: Writable mid-session, not just at wrap

**Choice:** Notes can be appended anytime during a session (direct write to `$WORKSPACE/.notes/NOTES.md`), not only during the handover wrap checklist.
**Alternatives:**
- Wrap-only — too late for "remember this" moments mid-work. Rejected.
**Rationale:** Sticky notes get written when the thought occurs, not at session end.
**Trade-offs:** None — it's a file append.
**Exploration:** quick
**Status:** captured
