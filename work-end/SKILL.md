---
name: work-end
description: >
  Use when the current branch is complete and ready to close — user says
  "work-end", "close this branch", or "wrap up this issue". Must be invoked
  from the working branch, not main. Replaces "epic close".
---

# work-end

Closes the current branch cleanly. Promotes artifacts, merges the journal,
closes the issue, rebases the project branch onto the project base branch, marks the
branch closed, returns to the workspace base (main).

<HARD-GATE>
**Code review is mandatory before any push or PR.** You MUST invoke the
`code-review` skill on the branch diff before Step 8j (push/PR). There are
NO exempt branches — not "mechanical" changes, not "tests already pass",
not "small diff". The review catches what you missed. Skipping it is the #1
failure mode of this skill.

**Doc sync is mandatory.** `update-claude-md` and `implementation-doc-sync`
are part of the pre-close sweep and default to ON. They catch convention drift
and stale documentation that compounds across sessions.

**Main-branch mutations go through work-end only.** Never run
`git checkout main && git merge <branch>` manually — this bypasses
pull-before-merge, squash-before-push, and fork-first delivery. If work
needs to land on main, use work-end on the branch. There is no safe shortcut.
The pre-push hook blocks diverged pushes, but prevention is better than detection.
</HARD-GATE>

### Red Flags — thoughts that mean STOP

| Thought | Reality |
|---------|---------|
| "This branch was mechanical" | Mechanical changes have mechanical bugs. Review catches them. |
| "Tests passed, it's fine" | Tests verify behaviour, not code quality or spec compliance. |
| "The diff is small" | Small diffs have the highest bug-per-line ratio. |
| "I'll review after merging" | Post-merge review is post-incident review. |
| "Doc sync has nothing to sync" | Run it and let the skill decide. Your guess is often wrong. |
| "CLAUDE.md hasn't changed" | Conventions established during implementation need to be captured. |
| "I'll promote artifacts manually" | 195 orphaned specs. Run close_artifacts.py. The verification gate catches you. |
| "close_artifacts.py is overkill for this branch" | The script takes 2 seconds. Skipping it loses specs permanently. |

---

## Path Resolution (run first, always)

Run the bundled context script — installed, version-controlled, no hardcoded paths:

```bash
python3 ~/.claude/skills/project/ctx.py
```

**Never write a script to /tmp/ for path resolution.** `/tmp/` is shared across sessions — a stale script from a previous session in a different project will silently return the wrong workspace and project paths, contaminating the entire close operation.

Use the printed values as **concrete strings** in ALL subsequent commands.
Never re-assign to shell variables. Replace every `<WORKSPACE>`, `<PROJECT>`, `<BRANCH_NAME>`,
`<PROJECT_SHA>`, `<ISSUE_N>`, `<COVERS>`, `<OWNER_REPO>`, `<BASE_BRANCH>` placeholder
with the actual value from the script output.

---

## Pre-conditions

Run `python3 ~/.claude/skills/project/ctx.py` first. Use `CURRENT_BRANCH` from its output. Check in order:

0. **Branch divergence check** — read `BRANCH_MISMATCH` from ctx.py output.
   If `BRANCH_MISMATCH=yes`: **hard stop.**
   > "⚠️ Workspace and project branches have diverged ($MISMATCH_DETAIL).
   > This can cause work-end to close the wrong issue or stamp the wrong branch.
   >
   > Options:
   > 1. Switch workspace to match project: `git -C $WORKSPACE checkout $PROJECT_BRANCH`
   > 2. Switch project to match workspace: `git -C $PROJECT checkout $CURRENT_BRANCH`
   > 3. Abort — investigate the mismatch first"
   >
   Do NOT proceed until the branches are aligned. This check prevents the
   class of bugs where `.meta` from a stale workspace branch provides wrong
   issue/covers/SHA context for the close operation.

0b. **Epic confirmation gate** — read `IS_EPIC` from ctx.py output.
   If `no`, skip silently. If `yes`, run:
   ```bash
   python3 ~/.claude/skills/work-slot/epic_manager.py check <EPIC_PATH>
   ```
   Read `EPIC_COMPLETE`, `SAFE_EXIT`, `CURRENT_BATCH`, `TOTAL_BATCHES`,
   `ACTIVE_ISSUE` from output.

   Three outcomes, evaluated as an if/elif/else chain:

   | Check (in order) | UX |
   |-------------------|----|
   | `EPIC_COMPLETE=yes` | Proceed silently — all children done |
   | `SAFE_EXIT=yes` | "Batch N/M complete. Safe exit point — close? (y/n)" |
   | Neither | "⚠ Mid-batch (issue #X of batch N/M). Partial close loses context. Continue? (y/confirm-partial)" |

   `EPIC_COMPLETE=yes` implies `SAFE_EXIT=yes` — the if/elif ordering ensures
   only the most specific arm fires. The mid-batch confirmation requires typing
   `confirm-partial`, not just `y`.

   **Slot mode caveat:** In slot mode, "close" means Phase A (squash + push
   branch). The prompt should say "run Phase A" not "run work-end" — the slot
   is merged separately via `work-slot merge`.

1. **If `$WORKSPACE/design/.pause-stack` exists and has entries** — check whether
   the target branch is in the stack:
   - **Current branch is in the stack** (ending a paused branch without resuming it):
     allowed. After all close steps complete, remove this branch from the stack
     (Step 9 will handle it — see "Stack cleanup on end" below).
   - **Current branch is NOT in the stack but stack is non-empty**: inform the user
     the stack has N other paused branches. Continue — this is normal when ending
     the active branch while others are paused.

2. **`$WORKSPACE/design/.meta` exists?** (check `HAS_META` from ctx.py)
   - **YES** → proceed (read values from ctx.py output as normal).
   - **NO** → check branch:
     - **On main or `$PROJECT_BASE_BRANCH`** → "Nothing to close — you're on
       `$CURRENT_BRANCH`." Exit cleanly.
     - **On a feature branch** → graceful degradation:
       1. **Resolve issue:**
          - `INFERRED_ISSUE` populated (from ctx.py) →
            `gh issue view $INFERRED_ISSUE --repo $OWNER_REPO`,
            extract title and confirm with user
          - `INFERRED_ISSUE` populated but `gh issue view` fails
            (network error, issue not found, `OWNER_REPO` empty) →
            present inferred number for manual confirmation:
            "Branch references issue #N but verification failed —
            confirm, enter a different number, or skip."
          - `INFERRED_ISSUE` empty →
            ask user for one-line work description,
            offer to invoke issue-workflow Phase 2 to create an issue
          - User declines issue creation →
            set `ISSUE_N=""` and `COVERS=""`.
            Steps depending on `ISSUE_N` (8e spec posting, 8a issue close)
            are skipped.
       2. **Set context values** (from ctx.py output + defaults):
          - `BRANCH_NAME` = `CURRENT_BRANCH` (from ctx.py — the git branch name)
          - `ISSUE_N` = confirmed issue number (or empty if declined)
          - `ISSUE_REPO` = `OWNER_REPO` (from ctx.py)
          - `COVERS` = `ISSUE_N` (single issue only without `.meta`)
          - `DESIGN_REPO_KEY` = `""` (from ctx.py; Step 3 defaults to "project")
          - `PROJECT_SHA` = `""` (no baseline)
          - `META_SECTION_HASHES` = `""` (no section hashes)
          - `FLYWAY_NEXT_V` = `""` (from ctx.py, already empty without `.meta`)
       3. Proceed with normal close flow using these values.

3. **If `$WORKSPACE/design/.meta` exists but `$CURRENT_WORKSPACE == main`** (orphaned)
   → hard stop. Offer to switch to the surviving branch and close from there, or discard.

4. **Workspace must have a clean working tree** — run before any other work:
   ```bash
   git -C "$WORKSPACE" status --short
   ```
   If any output appears, hard stop:
   > "Workspace has uncommitted changes on `$BRANCH_NAME`. Commit or discard them
   > before running work-end — stash is not used in this workflow."
   Do not proceed until the working tree is clean. Never stash automatically.

5. **Project base branch must have a clean working tree** — run before any other work:
   ```bash
   git -C "$PROJECT" status --short
   git -C "$PROJECT" log "$PROJECT_BASE_BRANCH"..origin/"$PROJECT_BASE_BRANCH" --oneline
   ```
   - If `git status --short` has output → hard stop:
     > "⚠️  Project `$PROJECT_BASE_BRANCH` has staged or unstaged changes — a previous operation
     >  was left incomplete. Resolve before closing this branch."
   - If remote is ahead of local → warn (non-blocking):
     > "⚠️  Remote `$PROJECT_BASE_BRANCH` is ahead of local — rebase before landing this branch's work."

   **Do NOT check whether local is ahead of remote.** At work-end, local `$PROJECT_BASE_BRANCH`
   will naturally be ahead once the branch is rebased onto it (step 8j). The mandatory fork push
   in step 8j is the mechanism that ensures work is preserved — not a pre-condition check.
   Checking "local ahead of remote → hard stop" would always fire incorrectly at work-end.

---

## Step 0 — Context (resolved by Path Resolution script)

All values — `WORKSPACE`, `PROJECT`, `OWNER_REPO`, `BASE_BRANCH`, `BRANCH_NAME`,
`PROJECT_SHA`, `ISSUE_N`, `ISSUE_REPO`, `COVERS` — come from `ctx.py` output.
Do not re-extract them with shell commands.

Note: ctx.py outputs `BASE_BRANCH`. This skill uses `PROJECT_BASE_BRANCH` as the
variable name. They refer to the same value.

`COVERS` is a comma-separated list of all issue numbers this branch closes (e.g. `"5,19,32,24"`).
When the branch was started for a single issue, `COVERS` equals `ISSUE_N`. When absent from
`.meta` (branches created before this feature), `COVERS` defaults to `ISSUE_N`.

---

## Step 1 — Branch Reconnaissance (mechanical script)

Run the bundled reconnaissance script to gather branch state and validate
the journal. Runs AFTER Step 3 (routing resolution) which provides
`DESIGN_REPO`. All operations are deterministic — no LLM subagent needed.

**Run:**

```bash
python3 ~/.claude/skills/work-end/branch_recon.py <WORKSPACE> <PROJECT> \
  branch=<BRANCH_NAME> base_branch=<PROJECT_BASE_BRANCH> \
  issue_repo=<ISSUE_REPO> covers=<COVERS> project_sha=<PROJECT_SHA> \
  design_repo=<DESIGN_REPO> meta_section_hashes=<META_SECTION_HASHES> \
  single_repo=<yes|no>
```

Substitute all `<PLACEHOLDER>` values with concrete strings from ctx.py
and Step 3.

**Output:** JSON object on stdout with this structure (all fields required,
arrays may be empty):

```json
{
  "issues": [{"number": N, "title": "...", "state": "OPEN|CLOSED"}],
  "commits": [{"sha": "abc1234", "message": "feat: ..."}],
  "commit_count": N,
  "diff_stats": "N files changed, N insertions, N deletions",
  "journal_entry_count": N,
  "journal_validation": {
    "arc42_exists": true|false,
    "section_drift": [{"section": "## S5", "stored_hash": "abc", "current_hash": "def"}],
    "anchored_entries": N,
    "unanchored_entries": N,
    "entries_without_anchors": ["### Entry heading"],
    "empty_journal": true|false
  },
  "warnings": ["..."]
}
```

**On return:**

1. Parse the JSON from stdout. If exit code is non-zero or JSON is malformed:
   warn the user and fall back to running the individual commands inline.

1b. If `warnings` is non-empty: the script hit something ambiguous (malformed
   journal entries, missing `section_hashes.py`, etc). Investigate each warning
   inline — run the relevant git/file commands yourself to resolve what the
   script flagged. The script handles the fast path; you handle edge cases.

2. Print the branch summary from JSON fields:

```
╔══ Branch Summary ═══════════════════════════════════╗
║  Branch: <BRANCH_NAME>
║  Issue:  #<issues[0].number> — <issues[0].title>   (primary)
║  Covers: #<N>, #<M>  ← omit if single issue
║  Started: <date from .meta>
║
║  Commits (<commit_count>):
║    <commits[].sha commits[].message, one per line>
║
║  Changed: <diff_stats>
║  Journal: <journal_entry_count> entries (or: no journal)
╚═════════════════════════════════════════════════════╝
```

3. Store the full JSON for use by Step 5 (journal validation decisions)
   and Step 7 (close plan construction).

---

## Step 2 — Flyway V re-scan

Re-scan at close time — another branch may have claimed the same V numbers since
branch creation.

```bash
git -C "$PROJECT" fetch --all 2>/dev/null || echo "⚠️ No network — scan skipped"
```

If conflict detected: offer `[R]` renumber affected migration files, `[A]` abort.
Block close until resolved.

---

## Step 3 — Resolve routing and set DESIGN_REPO

Read three-layer routing cascade for each artifact type. Warn on deprecated
vocabulary (`base`, `project repo`, `design-journal`). Show resolved table;
user confirms before proceeding.

**Capability detection** — for each resolved destination:
```bash
detect_capability() {
  local dest="$1"
  if [ -d "$dest/.git" ]; then
    git -C "$dest" remote get-url origin &>/dev/null 2>&1 && echo "remote-git" || echo "local-git"
  else
    echo "filesystem"
  fi
}
```

**Specs routing** — check the CLAUDE.md Routing table for a `specs` row. If present,
honour it (workspace or project). If absent, default to `project` (`$PROJECT/docs/specs/`).
Unlike earlier skill versions, specs routing IS configurable — projects that keep all
methodology artifacts in the workspace should declare `specs → workspace` in their
CLAUDE.md Routing table and specs will be promoted there instead.

**`$DESIGN_REPO` — use `DESIGN_REPO_KEY` from ctx.py output (do NOT re-derive from routing config):**

`DESIGN_REPO_KEY` comes from ctx.py (which reads `.meta` at parse time).
When `.meta` is absent, `DESIGN_REPO_KEY` is empty — the default case applies.

```bash
case "$DESIGN_REPO_KEY" in
  workspace)
    DESIGN_REPO="$WORKSPACE" ;;
  project)
    DESIGN_REPO="$PROJECT" ;;
  cross-repo:*)
    CROSS_REPO_NAME="${DESIGN_REPO_KEY#cross-repo:}"
    CANDIDATE="$(dirname "$PROJECT")/$CROSS_REPO_NAME"
    if [ -d "$CANDIDATE/.git" ]; then
      DESIGN_REPO="$CANDIDATE"
    else
      echo "⚠️ Cross-repo path not found at $CANDIDATE — cannot merge journal."
      echo "Options: [S]kip journal merge  [A]bort close"
      # Wait for user response before continuing
    fi ;;
  *)
    echo "⚠️ Unknown design-repo key '$DESIGN_REPO_KEY' — defaulting to project."
    DESIGN_REPO="$PROJECT" ;;
esac
```

`$DESIGN_REPO` must remain available through Step 8d. Do not recalculate it in
subsequent steps.

---

## Step 3b — Pre-close sweep

Before inventorying artifacts, verify the branch leaves nothing behind. Present
this checklist:

```
Pre-close sweep — create before presenting the close plan?

[x] 1  write-content          capture any work on this branch worth a diary entry
[x] 2  adr                    record any significant architectural decisions without a formal ADR
[x] 3  protocol sweep         formalise any project rules established or re-enforced this branch
[x] 4  forage sweep           check for gotchas, techniques, or undocumented behaviours
[x] 5  update-claude-md       sync any new workflow conventions to CLAUDE.md
[x] 6  implementation-doc-sync  sync documentation with code changes this branch made

Type numbers to toggle, "all" to toggle all, or "go" to proceed:
```

Defaults: all six on. The user may deselect any that clearly don't apply (e.g. "go"
immediately if the branch was a one-line typo fix). Do not auto-skip — the point is
to make the decision explicit.

<SESSION-BOUND-ITEMS>
**Items 1, 3, 4 (write-content, protocol sweep, forage sweep) are session-bound.**
They depend on conversation context that does not survive to the next session.
They cannot be deferred — "defer to next session" means "lose forever." If the
session is wrapping mid-work (handover, not work-end), these three must still run
before the session ends. The user may skip them explicitly, but the skill must
never offer "defer" as an option for these items.

Items 2, 5, 6 (adr, update-claude-md, implementation-doc-sync) work from file
state and git history — they can be deferred to a continuation session if needed.
</SESSION-BOUND-ITEMS>

Run checked items in this order:
1. **Forage sweep** — while context is full; findings may feed the blog entry
2. **Protocol sweep** — while context is full (invoke `protocol` skill with `SWEEP` operation)
3. **update-claude-md** — sync new conventions before doc-sync reads them
4. **implementation-doc-sync** — sync documentation with code changes
5. **adr** — invoke `adr` skill for each candidate identified
6. **write-content** — last, so it can synthesise the full branch narrative including any forage/protocol submissions

**Why this step exists:** Step 4 inventories artifacts that *were written*. Without this
sweep, the close plan accurately reports "blog: no new entries" when it should say "blog:
no new entries (and none were considered)." The sweep converts the inventory from a
snapshot into a verified statement. Only after this step is complete does the close plan
accurately reflect what the branch leaves behind.

After all checked items complete, proceed to Step 3c.

### Step 3b-slot — Per-repo sweep (slot mode only)

When `is_slot_path()` detects a slot path in `$PROJECT` (slot mode), replace the
single-repo sweep above with a per-repo loop:

**1. Discover repos in the slot:**

Priority: `.slot` is authoritative (read via `parse_slot_md()` from
`slot_manager.py`). Fallback: if `.slot` is absent, scan the slot
directory for git repos (via `get_slot_repos()`). `.slot` is preferred
because it records the intended repo set at slot creation; directory scan
may find repos added ad-hoc after creation.

- Primary repo = `$PROJECT` (the repo work-slot was invoked from)
- Secondary repos = other repos in the slot

**2. Per-repo loop** (primary + secondaries), in this order:

For each repo R:
  a. **protocol sweep** against R's `docs/protocols/` — captures rules first
  b. **update-claude-md** against R's CLAUDE.md — syncs conventions
     (including newly captured protocols)
  c. **implementation-doc-sync** against R's `docs/` — syncs documentation
     (using up-to-date CLAUDE.md)

Retargeting: the LLM sets repo R's path as context for each skill
invocation, reading/writing R's files using absolute paths. Skills that
invoke scripts with CWD assumptions may need explicit path parameters —
discovered and addressed during implementation.

Each skill commits its own changes independently (per-skill commits, same
as current non-slot behaviour). The squash step (8j) consolidates commit
granularity before landing.

**3. Session-bound** (run once, not per-repo), in this order:
  a. **forage SWEEP** — global (no change)
  b. **adr** — primary workspace `adr/` (shared across repos, not per-repo)
  c. **write-content** (diary) — primary workspace `blog/` only
     (last, so it can synthesise the full branch narrative)

---

## Step 3c — Code review (mandatory — HARD GATE)

**This step cannot be skipped.** A prior spec review does NOT replace implementation
review — specs validate design, implementation review validates the code actually
delivered. Resource leaks, concurrency bugs, missing validation, and subtle
misinterpretations only surface in code. Scale the depth, not skip the review.

**Choose the review type.** Two options:

- **Code review** (`code-review`) — checklist pass over the diff. Fast, cheap.
  Catches style issues, missing tests, obvious bugs. This is a pre-commit
  sanity check.
- **Final review** (`design-review --mode final-review`) — full adversarial
  review with two independent sessions debating the implementation. Multiple
  rounds, $5-25. Catches architectural mismatches, missing failure modes,
  spec deviations.

**When to use which:**

| Situation | Default |
|-----------|---------|
| Spec was adversarially reviewed (this session or recent) | **code-review** — the adversarial pass already happened on the design; code review checks the implementation |
| No spec review, structural diff (new files, renames, config changes) | **final-review** — no prior adversarial pass, structural changes warrant one |
| No spec review, body-only diff (method implementations, imports) | **code-review** — low-risk changes, checklist is sufficient |
| Implementation diverged significantly from reviewed spec | **final-review** — new architectural decisions the spec didn't cover |

Classify the branch diff:

1. Get diff stats: `git -C "$PROJECT" diff "$PROJECT_BASE_BRANCH"..HEAD --stat`
2. Check for structural changes (new files, deletions, renames, new
   classes, signature changes, config changes) vs body-only
3. Check whether a design-review ran this session (check for a review
   workspace under `~/adr/` matching the branch name or spec)

Present:
> "Branch diff: N files, M lines ({structural|body-only}).
>  Spec review: {yes — adversarially reviewed | no prior review}.
>  Recommended: {code-review | final-review}. Run? [y]es / [o]ther / [s]kip"
- y → invoke the recommended review
- o → invoke the alternative (code-review ↔ final-review)
- s → skip (user takes responsibility)

If the review surfaces issues:
- **Critical/Important issues** → fix before proceeding. Re-run review after fixes.
- **Minor issues** → fix or note. Do not block on minors alone.

Only proceed to Step 4 after code review passes (no critical/important issues open).

**Why here and not at Step 8j:** By Step 8j you've already built the close plan,
merged the journal, posted specs, and closed issues. Discovering a code problem
at that point means unwinding all of that. Reviewing here — before any close
machinery runs — means fixes are cheap and the close plan reflects reviewed code.

---

## Step 4 — Inventory artifacts

```bash
ls "$WORKSPACE/adr/" 2>/dev/null | grep -v INDEX.md
ls "$WORKSPACE/blog/" 2>/dev/null | grep -v INDEX.md
ls "$WORKSPACE/snapshots/" 2>/dev/null | grep -v INDEX.md
ls "$WORKSPACE/specs/" 2>/dev/null | grep -v INDEX.md
ls "$WORKSPACE/plans/" 2>/dev/null | grep -v "^attic$"
cat "$WORKSPACE/design/JOURNAL.md"
```

Check whether the blog directory has any entries at all. This only determines
whether to run `publish-blog` — the skill itself handles the "what's new" check
by comparing the workspace blog against the destination:

```bash
BLOG_HAS_ENTRIES=$(ls "$WORKSPACE/blog/" 2>/dev/null | grep -v INDEX.md | grep -q "\.md$" && echo yes || echo no)
```

---

## Step 5 — Journal validation decisions

Journal validation data comes from the Branch Reconnaissance subagent
(Step 1). Use the `journal_validation` field from its return to drive
decisions:

**When `PROJECT_SHA` is empty (`HAS_META=no`):** `section_drift` will be
empty (no baseline hashes to compare). The remaining checks
(`arc42_exists`, `empty_journal`) still apply — a branch without `.meta`
can still have a journal.

- **`arc42_exists == false`:** `[C]` Create from journal entries — journal becomes the initial ARC42STORIES.MD content. `[S]` Skip merge entirely.
- **`section_drift` non-empty:** `[U]` update journal anchors, `[S]` skip drifted sections, `[A]` abort
- **`unanchored_entries > 0`:** `[F]` fix via update-design, `[S]` skip merge, `[C]` continue accepting loss
- **`empty_journal == true`:** `[W]` write retrospective via update-design, `[S]` skip and accept permanent loss

If multiple conditions are true, present them in the order above — existence
before drift before anchors before empty.

---

## Step 6 — Select specs for GitHub posting

If tracking enabled: list `$WORKSPACE/specs/`, ask which to post as
collapsible comments on the GitHub issue. Skip silently if tracking disabled.

---

## Step 7 — Present close plan

Present the plan:

```
work-end close plan — <branch-name>

  Flyway V check     ✅ no conflicts
  Artifact routing
  ├── adr/<N>        → project      [remote-git]
  ├── blog/<N>       → workspace    [remote-git]
  ├── specs/<N>      → project      [remote-git]
  └── snapshots/<N>  → workspace    [remote-git]
  Plan archiving     → plans/attic/<branch-name>/  [workspace main]
  Journal merge      → ARC42STORIES.MD  (<N> sections)
  Spec posting       → #<N>  (<filenames>)
  Issues             → close #<all issues from COVERS, e.g. "#5, #19, #32, #24">
  Publish blog       → 8g (N unpublished entries → destination)
  Project rebase     <branch> → <base-branch>
  Squash             <blessed-remote>/main..HEAD (mandatory before any push)
  Fork push          → origin/main (mandatory, no skip — fork is always updated first)
  Blessed repo       → prompt: push / PR / skip  (upstream remote, if present)
  Slot archive       → slots/attic/<N>/  (slot mode only — B7)

Approve all, or step by step? (all / step)
```

**The Publish blog line is always shown.** `publish-blog` compares the workspace
blog against the destination and publishes only what's missing — it handles the
"what's new" check. Do not attempt to pre-count new entries here.

---

## Slot Mode Detection

After path resolution, check if `$PROJECT` is a slot path (via `is_slot_path()`,
which checks for `/slots/` and legacy `/worktrees/`):

- **If yes → slot mode.** Phase A/B split applies. See below.
- **If no → normal mode.** Existing step ordering unchanged.

### Phase A — "Ready to land" (slot mode only)

Runs when the human says "work end" in a slot. Executes review,
verification, and squash — but defers merge and all post-merge actions.

**What runs in Phase A:**
- Steps 3b–3c (pre-close sweep, code review) — as normal
- Steps 4–7 (inventory, journal validation, spec selection, close plan)
- Step 8d–8e (journal merge, spec posting) — safe before merge
- Step 8h (final report — partial, covering what Phase A completed)
- Step 8i (hygiene scan)
- Step 8j modified: squash commits, push branch to origin. **Stop before
  rebase onto main.** Do not merge, do not push main.

**What is deferred to Phase B:**
- Steps 8a–8c (artifact promotion, spec cleanup) — 8c depends on 8b
- Step 8f (issue close) — depends on successful merge
- Step 8g (blog publish) — depends on successful merge
- Steps 8k–12 (build verification, mark closed, ARC42 scan, handover)

**After Phase A completes:**
- Write `.phase-a-complete` marker via script (also records the event
  in the worklog):
  ```bash
  python3 ~/.claude/skills/work-end/phase_a_complete.py <SLOT_ROOT> \
    branch=<BRANCH_NAME> repos=<comma-separated-repo-names> \
    family-root=<FAMILY_ROOT>
  ```
  Read `MARKER=<path>` and `WORKLOG=yes|skipped` from output.
- Desktop notification via `terminal-notifier`:
  "Slot N ready to land: <branch> on <primary-repo>"
- **Offer slot closure:**
  > "Phase A complete. Would you like to merge, stamp, and archive
  > this slot now? (y/n)"
  >
  > If **yes** → proceed to Phase B immediately (same session).
  > If **no** → stop. Slot stays as "ready to land" for later merge
  > via `work-slot merge` from the main repo.

**Epic note (slot and single-repo):** When closing an epic where all
batches are complete (the last `work next` or `work-slot next` set
`epic_complete=true`), the epic issue itself is included in COVERS
(added by `work next` step 4). work-end closes it alongside the child
issues. If the epic still has open batches (safe exit mid-epic), only
the completed child issues are in COVERS — the epic issue stays open.
To resume remaining children: run `work epic #N` again — it detects
already-closed children and plans only the open remainder.

### Phase B — "Land it" (slot mode only)

Runs when the human returns to the slot and says "merge" or "work end"
again. work-end detects `.phase-a-complete` in the slot root and enters
Phase B directly.

**Corrected ordering — merge first, then post-land actions:**

**B1. Rebase branches onto current main.** Slots are standalone clones
(`git clone --shared`), not git worktrees. The clone has its own refs —
the original repo cannot see the clone's branches directly. Rebase the
branch in the **slot clone**:

```bash
git -C <slot>/<repo> fetch origin main
git -C <slot>/<repo> rebase origin/main
```

If any branch rebase conflicts: hard stop. No main has been modified.
Human resolves the conflict on the branch in the slot clone, then
re-triggers Phase B.

**B1b. Cross-repo dependency check.** Before pushing, verify provider repos
will land before consumers:

```bash
python3 ~/.claude/skills/work-slot/slot_manager.py check-cross-deps <family-root> slot=<N>
```

If `CHECK=fail`: the output lists which provider repos must land first.
Reorder the push sequence in B2 accordingly (providers before consumers).
If a provider's changes are still on a feature branch, **hard stop** —
the consumer cannot be pushed until the provider lands.

**B2. Push rebased branch, then fast-forward original.** Only after all
rebases succeed. Clones do not share refs with the original — the rebased
branch must be pushed from the clone first, then merged in the original:

```bash
# Push rebased branch from clone to original (updates the branch ref)
git -C <slot>/<repo> push origin <branch> --force-with-lease

# In the original repo: fetch, then fast-forward main
git -C <original>/<repo> fetch origin
git -C <original>/<repo> merge --ff-only <branch>
git -C <original>/<repo> push origin main
```

If `--ff-only` fails or push fails, retry from B1 — max 3 attempts.
After 3 failures, hard stop with manual instructions.

**B3. Close issues.** All issues in `$COVERS`.

**B4. Promote artifacts.** Runs deferred 8a–8c.
Operations needing `main` checked out use the **original workspace**.
Operations reading from the branch use the **slot workspace clone**.

Pass `scan-workspace` to `close_artifacts.py` so artifacts are scanned
from the slot workspace (where they live on the branch), not the original
workspace (which is on main after B2 merge):

```bash
python3 ~/.claude/skills/work-end/close_artifacts.py \
  <ORIGINAL_WORKSPACE> <PROJECT> <BRANCH_NAME> \
  issue-repo=<ISSUE_REPO> covers=<COVERS> \
  scan-workspace=<SLOT_WORKSPACE>
```

Without `scan-workspace`, Phase B would scan the original workspace
(now on main) and find no branch artifacts to promote.

**B5. Publish blog entries (8g).** Run against the **original workspace**.

**B6. Stamp branches as closed.** Both project and workspace branches.

**Content verification before stamping (mandatory):**

Before writing any stamp, verify the branch content actually landed on main.
Compare source files between the branch and main — if there's a diff, content
was lost during squash and the stamp would be a lie.

```bash
python3 ~/.claude/skills/work-end/verify_stamp.py <slot>/<repo> <branch> main
```

Read `VERIFIED=yes` from output. If `VERIFIED=no`, the script prints the
missing files. **Hard stop — do not stamp.** Report the content gap and
instruct the user to investigate before proceeding.

Only after verification passes, stamp in the **slot clones** (where the
branches are checked out):
```bash
git -C <slot>/<repo> commit --allow-empty -m "chore: branch closed — landed as <SHA> on main"
git -C <slot>/work commit --allow-empty -m "chore: branch closed — landed as <SHA> on main"
```

**B7. Archive.** Move the slot directory to `slots/attic/<N>/`
(preserves .slot, clone repos, and marker files for auditing). Use
`archive-slot` from `slot_manager.py` — do not delete the slot directory.
No `git worktree remove` is needed — slots are standalone clones.

**B8. Post-merge steps.** Steps 8k–12 from normal work-end.

**Phase B completion gate (mandatory before declaring complete):**

Before proceeding to B8, verify all prior steps ran:
- [ ] Branches rebased and pushed (B1–B2)
- [ ] Issues closed (B3)
- [ ] Artifacts promoted (B4)
- [ ] Branches stamped as closed (B6)
- [ ] **Slot archived — clones moved to `slots/attic/<N>/` (B7)**

B7 is the most commonly skipped step. If the slot directory still exists
under `slots/<N>/` (not in attic), B7 did not run — go back and
execute it before continuing.

---

## Step 8 — Execute

Failures are reported but do not stop remaining steps, **except**: journal merge
failure prompts the user before continuing to issue close.

**Report collector — init before first step:**

```bash
python3 ~/.claude/skills/work-end/close_report.py init /tmp/work-end-report.json
```

After each sub-step below, record results into the report (see `record` calls).
Step 8h renders the final report mechanically from this data.

### 8a — Close artifacts (single script call)

Run the unified artifact promotion script:

```bash
python3 ~/.claude/skills/work-end/close_artifacts.py \
  <WORKSPACE> <PROJECT> <BRANCH_NAME> \
  issue-repo=<ISSUE_REPO> covers=<COVERS>
```

Read output KEY=value lines:
- `WORKSPACE_PROMOTED=N` — artifacts promoted to workspace main
- `PROJECT_PROMOTED=N` — artifacts promoted to project repo
- `ISSUES_CLOSED=N` — GitHub issues closed
- `BLOG_PUBLISHED=N` — blog entries published to destination
- `BLOG_DEST=<path>` — resolved blog destination
- `PLANS_ARCHIVED=N` — plans moved to `plans/attic/<branch>/`
- `STAMP=<path>` — `.artifacts-promoted` stamp (only on full success)

If exit code is 0: all operations succeeded, stamp written. Continue.
If exit code is 1 (fatal): stop. Report the error.
If exit code is 2 (partial): report `FAILURES=` output. Ask user whether
to retry or proceed without the stamp. The stamp is NOT written on partial
failure — Step 8j will block the push.

**Record to report:**
```bash
python3 ~/.claude/skills/work-end/close_report.py record /tmp/work-end-report.json \
  step=artifacts result=ok \
  workspace_promoted=$WORKSPACE_PROMOTED project_promoted=$PROJECT_PROMOTED \
  issues_closed=$ISSUES_CLOSED \
  blog_published=$BLOG_PUBLISHED blog_dest=$BLOG_DEST \
  plans_archived=$PLANS_ARCHIVED
```

**This replaces the previous Steps 8a-8c, 8f, and 8g.** The script
internally resolves routing from CLAUDE.md, scans the workspace for
artifacts, calls `artifact_promote.py` and `blog_dest.py` with the
correct arguments, and writes the completion stamp.

**WORKSPACE DESIGN REPO CASE:** If `$DESIGN_REPO_KEY = workspace`, the
journal merge must happen separately — `close_artifacts.py` does not
handle journal merges (they require interactive user approval). Run
8d after 8a completes.

### 8a-verify — Verify promotion (mechanical — HARD GATE)

**This step cannot be skipped.** Evidence-based verification that artifacts
actually landed at their expected destinations. The LLM cannot rationalize
past files that aren't on disk.

```bash
python3 ~/.claude/skills/work-end/verify_promotion.py \
  <WORKSPACE> <PROJECT> [scan-workspace=<SCAN_WS>]
```

Read `VERIFIED`, `TOTAL`, `LANDED`, `MISSING`, `MISSING_LIST` from output.

**If `VERIFIED=no`** → **hard stop.** Report:
> "⚠️ Artifact promotion verification failed.
>  {MISSING} of {TOTAL} artifacts not at expected destination:
>  {MISSING_LIST}
>
>  Re-run close_artifacts.py (Step 8a) to fix. Do NOT proceed."

Do NOT continue to 8d, 8e, or 8j. The promotion must succeed before
any downstream steps run.

**If `VERIFIED=yes`** → continue silently.

**Why this exists:** LLMs executing work-end skip `close_artifacts.py` and
manually replicate promotion inline, silently dropping specs. The stamp gate
at 8j catches missing stamps but the LLM rationalizes around it. This
verification checks the filesystem directly — 195 orphaned specs across 22
workspaces proved the trust-based approach doesn't work.

### 8d — Journal merge

Uses `$DESIGN_REPO` (set in Step 3) and `$PROJECT_SHA` (set in Step 1).

**When `PROJECT_SHA` is empty** (no `.meta`), skip journal merge entirely.
The baseline read (`git show "$PROJECT_SHA":ARC42STORIES.MD`) requires a
valid SHA. Journal entries on the branch are preserved but not merged into
ARC42STORIES.MD — this is the expected degradation (no baseline = no
three-way merge possible).

**⚠️ Branch context matters:** When `$DESIGN_REPO_KEY = workspace`, the merge MUST
happen during the 8a main-visit (see 8a above) — not here. For `$DESIGN_REPO_KEY = project`,
run the full merge below on the project epic branch (committed before the rebase in Step 8j).

Steps:
1. Read baseline: `git -C "$DESIGN_REPO" show "$PROJECT_SHA":ARC42STORIES.MD`
2. Read current `$DESIGN_REPO/ARC42STORIES.MD`
3. Apply journal narrative per `§Section`, preserving independent main-branch changes
4. Write merged result
5. Post-merge verification: re-read each `§Section`; present to user (`[A]` accept,
   `[R]` redo, `[X]` abort) before committing
6. Commit and push:
   ```bash
   git -C "$DESIGN_REPO" add ARC42STORIES.MD
   git -C "$DESIGN_REPO" commit -m "docs($BRANCH_NAME): apply design journal"
   git -C "$DESIGN_REPO" push
   ```

If journal merge fails: prompt user before continuing to issue close.

### 8e — Spec posting

Post selected specs (from Step 6) as collapsible comments on the GitHub issue.

### 8f — Issue close

**Handled by 8a** (`close_artifacts.py` closes all issues in COVERS).
Read `ISSUES_CLOSED=N` from 8a output.

### 8g — Publish blog

**Handled by 8a** (`close_artifacts.py` publishes blog entries via `blog_dest.py`).
Read `BLOG_PUBLISHED=N` and `BLOG_DEST=<path>` from 8a output.

### 8h — Final report (mechanical)

Render the close-out report from the collected step results:

```bash
python3 ~/.claude/skills/work-end/close_report.py render /tmp/work-end-report.json
```

This produces a deterministic, structured summary of every operation performed.
The report is generated mechanically — not assembled by the LLM.

**Closing summary — always append after the mechanical report:**

```
What this delivered:
  · <capability or fix — concrete outcome, not a task description>
  · <capability or fix>
  (2–4 bullets; omit if obvious from the issue title alone)

What this enables:
  → <follow-on work now unblocked, or new capability now possible>
  → <second item if applicable>
```

Generate from branch context — commits, issue title, COVERS list, and any issue
cross-references. Check COVERS issues on GitHub for 'blocked by' or 'depends on'
language to find what this unblocks. Omit **What this enables** entirely if nothing
follows directly — do not pad. Omit **What this delivered** if the issue title already
says it clearly and there is nothing to add.

### 8i — Hygiene scan (mechanical script)

Always run — not an offer. Run the bundled hygiene scan script to check
workspace branches for drift. All checks are deterministic — no LLM needed.

**Run:**

```bash
python3 ~/.claude/skills/work-end/hygiene_scan.py <WORKSPACE> <PROJECT> \
  branch=<BRANCH_NAME> blog_dest=<BLOG_DEST> \
  flyway_used=<yes|no> single_repo=<yes|no>
```

**Output:** JSON object on stdout with this structure (all fields required,
arrays may be empty):

```json
{
  "unpublished_blogs": ["filename.md"],
  "flyway_conflicts": [],
  "stale_branches": [{"branch": "issue-71-old", "last_commit_age": "12 days"}],
  "unrecovered_artifacts": [{"branch": "issue-50-closed", "type": "blog", "file": "2026-06-01-entry.md"}],
  "unstamped_branches": [{"branch": "issue-50-closed", "has_epic_closed": true, "project_branch_exists": true}]
}
```

**On return:**

1. Parse JSON from stdout. If exit code is non-zero or JSON is malformed:
   fall back to running the hygiene checks inline (list branches, check
   files, compare dates yourself). Hygiene is advisory — it catches drift
   but doesn't block the close. Exception: if blog verification cannot
   run, warn explicitly since unpublished blogs DO block.

2. **`unpublished_blogs` non-empty** → block and return to 8g. Max 2 attempts;
   after second failure, present options: `[F]` fix routing manually,
   `[S]` skip with warning, `[A]` abort close. Do not loop indefinitely.

3. **`unrecovered_artifacts`** → for each item, offer cherry-pick:
   > ⚠️ <type> `<file>` on closed branch `<branch>` never reached workspace main.
   > Cherry-pick to main? (y/n)
   Apply confirmed recoveries immediately. Run publish-blog for recovered blogs.

4. **`unstamped_branches`** → for each item where `project_branch_exists`, offer stamp:
   > ⚠️ Branch `<branch>` has EPIC-CLOSED.md but project branch is not stamped.
   > Stamp now? (y/n)
   If confirmed, stamp with the landing SHA format:
   ```bash
   git -C "$PROJECT" checkout <branch>
   git -C "$PROJECT" commit --allow-empty -m "chore: branch closed — landed as <LANDED_SHA> on $PROJECT_BASE_BRANCH"
   git -C "$PROJECT" checkout "$PROJECT_BASE_BRANCH"
   ```

5. **`stale_branches`** → report informational only.
6. **`flyway_conflicts`** → warn informational.

### 8j — Rebase project branch onto project base branch, push to fork, prompt for blessed repo

**This step is mandatory.** Implementation commits on the project branch must land on `$PROJECT_BASE_BRANCH` before the branch is marked closed.

**Rebase (mechanical script):**

```bash
python3 ~/.claude/skills/work-end/land_branch.py rebase <PROJECT> \
  branch=<BRANCH_NAME> base_branch=<PROJECT_BASE_BRANCH>
```

Outputs `FORK_REMOTE=`, `BLESSED_REMOTE=`, and `REBASE=ok` on success.

**Record to report:**
```bash
python3 ~/.claude/skills/work-end/close_report.py record /tmp/work-end-report.json \
  step=rebase result=ok branch=$BRANCH_NAME base=$PROJECT_BASE_BRANCH
```

| Topology | Meaning |
|----------|---------|
| `BLESSED_REMOTE` non-empty | Fork model — `FORK_REMOTE` is the fork, `BLESSED_REMOTE` is the blessed repo |
| `BLESSED_REMOTE` empty | Single-remote model — `FORK_REMOTE` is the blessed repo |

**If rebase fails** (`ERROR=REBASE_CONFLICT`):
- `ERROR_DETAIL` contains the git stderr from the failed rebase.
  If `FALLBACK=yes`: the script could not cleanly determine the conflict
  state. Run `git -C <PROJECT> rebase <BRANCH_NAME>` inline to see the
  full conflict output, then `git rebase --abort` after reading it.
- Report the conflicting files to the user.
- **Stop. Do not proceed to Step 9.**
- Instruct the user: resolve conflicts on `$PROJECT_BASE_BRANCH`, then re-run `work-end` to complete the close.

**Squash analysis (delegated to subagent) — mandatory before fork push:**

Squash runs BEFORE the fork push so both fork and blessed repo receive
identical history. This is not optional and must not be bypassed with
`--no-verify`.

Dispatch an Opus subagent to classify commits and propose a squash plan.
The subagent reads squash-policy.md and git-squash SKILL.md Steps 3a–3i
for classification rules. Sub-issue reference collection is also handled
by the subagent — no inline collection needed.

**Single-repo filter-repo preprocessing:** In single-repo mode, the rebase
brings scaffold commits (`.meta`, `JOURNAL.md`, `design/`) onto the base
branch. Before dispatching the subagent:
1. Create a temporary working branch from the base branch
2. Run `filter-repo` to strip scaffold paths with `--prune-empty always`
3. Dispatch the subagent on the post-filter-repo branch
4. Execute the squash on the working branch
5. Swap the working branch with the base branch via `branch_swap.py`

Skip the filter-repo preprocessing in two-repo mode.

**Dispatch:**

```
Agent(
  description: "Squash analysis for work-end",
  model: "opus",
  prompt: "You are a commit classification agent. Analyse commits and
    propose a squash plan. Do NOT execute any git rebase or destructive
    operations — analysis only.

    Parameters:
    - PROJECT: {PROJECT}
    - BASE_BRANCH: {PROJECT_BASE_BRANCH}
    - BRANCH_NAME: {BRANCH_NAME}
    - COVERS: {COVERS} (comma-separated issue numbers this branch closes)
    - BLESSED_REMOTE: {upstream or origin}
    - SQUASH_POLICY: ~/.claude/skills/git-squash/squash-policy.md
    - GIT_SQUASH_SKILL: ~/.claude/skills/git-squash/SKILL.md
    - COMMIT_GATHER: ~/.claude/skills/git-squash/commit_gather.py
    - SINGLE_REPO_MODE: {yes|no}

    Steps:
    1. Read SQUASH_POLICY for classification rules (KEEP/SQUASH/MERGE/DROP).
    2. Read GIT_SQUASH_SKILL — ONLY Step 3 and sub-steps 3a through 3i
       (the classification procedure). Ignore Steps 0-2 (working branch,
       filter-repo, range resolution) and Steps 4-9 (plan display,
       execution, review gate, swap). The SKILL.md has clear ### headers.
    3. Run: python3 {COMMIT_GATHER} {PROJECT}
       base={BLESSED_REMOTE}/{BASE_BRANCH}
       This returns structured per-commit data (sha, subject, body,
       author, date, files, insertions, deletions, issue_refs, patch_id).
    4. Run strategy detection: check for merge-commit PRs in the range.
       If found → reconstruction mode. Else → scope clustering or flat.
    5. Apply the full classification procedure from Steps 3a-3i:
       same-issue clustering, CI arc detection, proximity-grouped
       resolution, temporal scrutiny, file-overlap MERGE, cross-author
       check, cherry-pick detection.
    6. Propose groups with draft squash messages. Add per-commit flags
       (proximity-grouped, temporal:Nmin, cross-author, cherry-pick:branch,
       file-overlap:group-N) and per-group annotations.
    7. Collect sub-issue references (Closes/Fixes/Resolves #N) from all
       commit bodies. Cross-reference against COVERS — report refs not
       in COVERS that would be lost in squash.

    Return your results as a single JSON object with this exact
    structure (all fields required, arrays may be empty):
    {
      \"total_commits\": N,
      \"strategy\": \"B|D|E\",
      \"groups\": [
        {
          \"label\": \"feat(#82): description\",
          \"action\": \"KEEP|SQUASH|MERGE|DROP\",
          \"commits\": [
            {\"sha\": \"abc1234\", \"message\": \"feat: ...\", \"classification\": \"KEEP\", \"flags\": []}
          ],
          \"proposed_message\": \"feat(#82): ...\",
          \"annotations\": []
        }
      ],
      \"sub_issue_refs\": [\"#83\"],
      \"refs_not_in_covers\": [\"#83\"],
      \"warnings\": [],
      \"blocking_flags\": []
    }
    Return ONLY the JSON object, no other text."
)
```

**On return:**

1. Validate JSON shape. If malformed or empty: warn and offer
   `[G]` invoke `/git-squash` manually, `[S]` skip squash (user takes
   responsibility for noisy history).

2. If `blocking_flags` non-empty: present each flag and resolve before
   allowing approval.

3. Format groups into plan display with per-commit flags and group
   annotations. **Order by recommendation — the option that best preserves
   semantic intent is option 1.** Prefer keeping separate commits when they
   represent genuinely different concerns (feat vs fix vs docs for different
   subsystems, different issue refs). Aggressive single-commit squash is a
   later option, not the default. Present for user approval:
   > Squash plan: <total_commits> commits → <N groups> groups (strategy: <strategy>)
   > [A] Accept  [E] Edit  [R] Reject  [G] Run /git-squash instead

4. On approval, execute the squash:
   - Build a rebase todo from the approved groups. For each group:
     one `pick` line for the first commit, `fixup` lines for the rest.
   - For groups with a non-null `proposed_message`: append an
     `exec git commit --amend -m "<message>"` line after the group's
     last `fixup`. Use multiple `-m` flags for trailers (git separates
     each `-m` with a blank line). Do NOT use `\n` inside double quotes —
     POSIX sh interprets it as literal backslash-n.
   - For the last group: if `refs_not_in_covers` is non-empty, add
     `Closes #N` trailers via a separate `-m` flag.
   - Call `rebase_exec.py multi <PROJECT> base=<base-sha> todo-file=<path>`
     — on failure, the script auto-aborts and restores pre-squash state.
   - Run post-squash interval tree verification (5 evenly-spaced samples).

5. If user explicitly says "skip squash" or "no squash needed": accept
   and note it, then proceed. Never silently skip.

**Push to fork (mechanical script — mandatory, no skip):**

The push subcommand checks the `.artifacts-promoted` stamp, then pushes
to the fork remote. Both checks are mandatory — the script fails if the
stamp is missing or the push fails.

```bash
python3 ~/.claude/skills/work-end/land_branch.py push <PROJECT> \
  base_branch=<PROJECT_BASE_BRANCH> workspace=<WORKSPACE> \
  branch=<BRANCH_NAME>
```

If `ERROR=MISSING_STAMP`: **hard stop.** Return to Step 8a.
If `ERROR=PUSH_FAILED`: stop. Do not proceed to blessed repo delivery.

**Record to report:**
```bash
python3 ~/.claude/skills/work-end/close_report.py record /tmp/work-end-report.json \
  step=push-fork result=ok remote=$FORK_REMOTE branch=$PROJECT_BASE_BRANCH
```

The fork push is always required. The blessed repo can never receive
commits that the fork has not already received.

**Blessed repo delivery (fork model only — interactive prompt):**

If `$BLESSED_REMOTE` is non-empty (from the `rebase` subcommand output),
always prompt — three choices:

> "Deliver to `$BLESSED_REMOTE/$PROJECT_BASE_BRANCH`?
>   [P] Push directly   [R] Open PR   [N] Skip"

- **P — Push directly:**
  ```bash
  git -C "$PROJECT" push "$BLESSED_REMOTE" "$PROJECT_BASE_BRANCH"
  ```
- **R — Open PR:**
  ```bash
  gh pr create --base "$PROJECT_BASE_BRANCH" --head "$(git -C "$PROJECT" remote get-url "$FORK_REMOTE" \
      | sed 's|.*github.com[:/]\(.*\)\.git|\1|'):$PROJECT_BASE_BRANCH" --title "<issue title>" --body "Closes #$ISSUE_N"
  ```
- **N — Skip:** leave blessed repo delivery for later; note it in the 8h report. Fork already has the commits.

If no `$BLESSED_REMOTE`: no prompt — fork push is the final delivery.

**Stamp the project branch as closed (mechanical script):**

After all pushes complete, stamp the branch. The script verifies content
landed on the base branch (via `verify_stamp.py`), then writes the stamp.

```bash
python3 ~/.claude/skills/work-end/land_branch.py stamp <PROJECT> \
  branch=<BRANCH_NAME> base_branch=<PROJECT_BASE_BRANCH>
```

If `ERROR=VERIFICATION_FAILED`: **hard stop — do not stamp.** Report the
content gap from stderr. A false stamp is worse than no stamp — it marks
the branch as archived when its content never landed.

On success: outputs `STAMP=ok` and `LANDED_SHA=<sha>`.

**Record to report:**
```bash
python3 ~/.claude/skills/work-end/close_report.py record /tmp/work-end-report.json \
  step=stamp-project result=ok branch=$BRANCH_NAME landed_sha=$LANDED_SHA
```

This is mandatory, not an offer. An unstamped branch looks live to the next session.

**Stamp verification note:** `land_branch.py stamp` always calls `verify_stamp.py`
before writing the stamp — there is no code path that skips verification. In slot mode,
`merge_slot()` stamps directly after push success, which is a different but equivalent
verification mechanism (push to main succeeds only if content is on main).

**Why rebase and not merge --no-ff?** Rebase keeps the project base branch history linear and avoids a merge commit that references a branch consumers never saw. Fast-forward is a safe subset — `git rebase` fast-forwards when possible, replays commits otherwise.

### 8j-cleanup — Remove scaffold from main (single-repo mode only)

**Skip entirely in two-repo mode (`SINGLE_REPO_MODE=no`).**

In single-repo mode, Step 8j's rebase brings the scaffold commit (`.meta`, `JOURNAL.md`)
from the epic branch onto main. These files are ephemeral branch artifacts — they must not
persist on main. HANDOFF.md and blog entries that also land via rebase are intentional and
must not be removed.

After 8j completes (workspace/project is now on main):

If `$SINGLE_REPO_MODE = yes`:

Run: `python3 ~/.claude/skills/work-end/branch_cleanup.py cleanup-scaffold <WORKSPACE> single-repo=yes`
Read `CLEANED=yes` from output. The script removes `.meta`, `JOURNAL.md`, and `.epic` (if
present), removes the `design/` directory if empty, commits, and pushes.

**Why this step exists:** In two-repo mode, `.meta` and `JOURNAL.md` live on the workspace
epic branch only — they never reach workspace main. In single-repo mode, the workspace IS
the project repo, so the rebase in 8j brings them to main. This cleanup restores the
invariant. HANDOFF.md and blog entries reaching main via the same rebase are correct
behaviour — do not remove them.

### 8k — Final build verification (Java / Maven projects only)

**Run after 8j. Skip for non-Java projects.**

Read `PROJECT_TYPE` from the ctx.py output (already run in Path Resolution).

If `PROJECT_TYPE` is `java`, use `AskUserQuestion` with exactly these four options:

```
Build verification level?
  [F] Fast (default)   — mvn install -DskipTests -DskipITs
  [U] Unit tests       — mvn install -DskipITs
  [A] All tests        — mvn install
  [S] Skip
```

Map the answer to a command:
- F or Enter: `mvn install -DskipTests -DskipITs`
- U: `mvn install -DskipITs`
- A: `mvn install`
- S: skip step entirely

If the user types something else (e.g. "integration tests only"): run `mvn install -DskipTests`.

Run from project root:
```bash
mvn install [flags] -C "$PROJECT"
# or: mvn -f "$PROJECT/pom.xml" install [flags]
```

If the build **fails** → stop. Do not proceed to Step 9 (mark closed).
Report the failure and ask the user to fix it before closing.

If the build **passes** → add `✅ Build verified (mvn install)` to the 8h report and continue.

---

### Step path (alternative to all-at-once)

If user chose "step" in Step 7:

- Phase 1: Artifact routing (8a including publish-blog if blog/ has entries), 8b, 8c — confirm, execute, report → "Continue to journal merge? (y/n)"
- Phase 2: Journal merge (8d) — show each `§Section` before/after, confirm → "Continue to GitHub posting? (y/n)"
- Phase 3: Spec posting (8e), issue close (8f) → "Continue to branch merge? (y/n)"
- Phase 4: Merge project branch to `$PROJECT_BASE_BRANCH` (8j), build verification (8k if Java), EPIC-CLOSED.md, return workspace to main.

Note: publish-blog (8g) runs after issue close (8f), before 8i hygiene scan. It is not
an "offer" — it always runs. 8i then verifies the result; any unpublished entries block 8j.

---

## Step 9 — Mark closed

`EPIC-CLOSED.md` lives in `$WORKSPACE/design/` and is committed to the workspace
**epic branch** (not main), so the hygiene scan can traverse epic branches to detect it.

**Two-repo mode:** workspace is still on the epic branch at this point — commit directly.

**Single-repo mode:** after 8j the repo is on main. Switch to the epic branch to commit,
then return to main.

Run: `python3 ~/.claude/skills/work-end/branch_cleanup.py create-epic-closed <WORKSPACE> branch=<BRANCH_NAME> date=$(date +%Y-%m-%d) issues=<COVERS> single-repo=<yes|no>`
Read `CREATED=yes` from output. The script handles single-repo branch switching internally.

Branches are **not deleted**. `EPIC-CLOSED.md` is the signal for hygiene scan cleanup.

**Stack cleanup on end:** If this branch was in the pause stack (detected in Pre-conditions),
remove it now that the branch is closed:

Run: `python3 ~/.claude/skills/work-end/branch_cleanup.py cleanup-stack <WORKSPACE> branch=<BRANCH_NAME>`
Read `REMOVED=yes|no` from output. If `yes`, the branch was found and removed from the stack.

---

## Step 10 — Return to base branches

Project is already on `$PROJECT_BASE_BRANCH` from Step 8j. Switch both repos to main:

Run: `python3 ~/.claude/skills/work-end/branch_cleanup.py checkout-main <PROJECT> <WORKSPACE>`
Read `SWITCHED=yes` from output. The script checks out main and pulls in both repos.

---

## Step 11 — ARC42 stale scan

Only if `HAS_ARC42STORIES=yes` (from ctx.py output, already run in Path Resolution).
Catches cross-session drift not covered by work-end's per-commit scope — layer
statuses, resolved blockers, closed-issue forward refs.

See the handover skill's Step 2c for the three checks (layer statuses, external
blockers, forward-tense refs). Run the same procedure here. Commit fixes to
the project repo.

Skip silently if `HAS_ARC42STORIES=no`.

---

## Step 12 — Write HANDOFF.md and close the session

work-end includes the full session wrap. There is no need to invoke the handover
skill separately after work-end — everything is handled here.

### 12a — HANDOFF.md

Follow the handover skill's Steps 1–6 (check previous handover, recall from
context, gather orientation, build references, write HANDOFF.md, commit to
workspace main). The pre-close sweep (Step 3b) already ran forage, protocol,
update-claude-md, doc-sync, and write-content — do not re-run them or show the
wrap checklist. Only write the HANDOFF.md file.

**Important:** HANDOFF.md must be committed to workspace **main**, not the epic
branch (which is now closed). The workspace should already be on main from Step 10.

### 12b — Session rename

Suggest a session rename if the session name appears auto-generated (random
three-word pattern). Generate a concise 2–4 word name from the session's
content. The user types `/rename <name>` — it is a Claude Code built-in.

### 12c — Session close summary

Output the final tick-list:

```
Session wrap complete.

✅ Epic hygiene              (or ⏭ skipped)
✅ Forage sweep              N entries submitted  (or: nothing garden-worthy found)
✅ Protocol sweep            N protocols captured (or: nothing new)
✅ update-claude-md          (or ⏭ skipped)
✅ implementation-doc-sync   N docs updated, N issues filed  (or: nothing stale found / ⏭ skipped)
✅ journal-entry             (or ⏭ skipped — not mid-epic)
✅ arc42 stale scan          N items fixed  (or: nothing stale found / ⏭ skipped — no ARC42STORIES.MD)
✅ write-content (diary)     <entry filename>  (or ⏭ skipped)
✅ Code review               0 findings  (or: N findings fixed)
✅ HANDOFF.md committed      <workspace>/HANDOFF.md → main
```

Show every item — both ticked and skipped with reason.

## Skill Chaining

**Invoked by:**
- `work` — routing skill, when user says "work end" or selects end from feature branch menu
- `executing-plans` — after all plan tasks complete
- `subagent-driven-development` — final close step

**Invokes:**
- `code-review` — Step 3c, mandatory gate before artifact promotion (body-only diffs)
- `design-review` — Step 3c (`--mode final-review`), mandatory gate for structural diffs
- `forage` — SWEEP (Step 3b pre-close sweep)
- `protocol` — SWEEP (Step 3b pre-close sweep)
- `update-claude-md` — Step 3b pre-close sweep
- `implementation-doc-sync` — Step 3b pre-close sweep
- `adr` — Step 3b pre-close sweep
- `write-content` — Step 3b pre-close sweep (last, after other artifacts)
- `publish-blog` — Step 8g
- `git-squash` — Step 8j subagent reads squash-policy.md and SKILL.md Steps 3a–3i for classification; parent calls rebase_exec.py directly for execution

**Complements:**
- `work` — routing entry point
- `work-pause` — alternative (pause mid-work vs. close the branch)
- `handover` — work-end includes the full wrap (Step 12); handover is for
  mid-work sessions only
- `work-start` — opens branches; work-end closes them
- `work-slot` — slot detection triggers Phase A/B split
- `using-git-worktrees` — worktree cleanup happens during branch closure
- `verification-before-completion` — verification is implicit in work-end's
  pre-merge checks

**Reads from:** `ctx.py`, `.meta`, `.pause-stack`, CLAUDE.md, workspace artifact
directories. Branch state, journal validation, and issue titles come from the
Branch Reconnaissance subagent (Step 1). Hygiene findings come from the Hygiene
Scan subagent (Step 8i). Squash classification comes from the Squash Analysis
subagent (Step 8j).
