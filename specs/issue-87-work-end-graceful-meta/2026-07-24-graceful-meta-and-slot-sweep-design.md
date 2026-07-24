# Design: work-end graceful .meta + slot-mode per-repo sweep

**Branch:** issue-87-work-end-graceful-meta
**Issues:** #87 (work-end graceful without .meta), #88 (slot-mode per-repo sweep)
**Date:** 2026-07-24

---

## Issue #87 — work-end graceful without .meta

### Problem

work-end hard-stops at pre-condition 2 when `$WORKSPACE/design/.meta` is absent.
This blocks closing branches that were created manually, created before the
scaffold system existed, or where `.meta` was accidentally deleted.

### Design

Replace the hard gate with graceful degradation. Changes span ctx.py (additive
output), work-end SKILL.md (pre-condition 2, Step 3, Step 5, Step 8d), and
ARC42STORIES.MD (documentation update).

#### ctx.py enhancement

ctx.py already outputs `HAS_META`, `CURRENT_BRANCH`, `ISSUE_N`, and
`DESIGN_REPO_KEY`. When `.meta` is absent, these are empty (correct — no data).
Add one new output:

```python
# After existing CURRENT_BRANCH assignment (line 68)
inferred_issue = ""
if not issue_n and current_branch:
    m = re.search(r'issue-(\d+)', current_branch)
    if m:
        inferred_issue = m.group(1)

print(f"INFERRED_ISSUE={inferred_issue}")
```

`INFERRED_ISSUE` is populated only when `ISSUE_N` is empty (no `.meta`) and
the branch name matches `issue-NNN`. This is deterministic, testable, and
consistent with ctx.py's existing pattern-extraction role (it already parses
`GitHub repo:` and `Project base branch:` from CLAUDE.md).

#### New pre-condition 2 flow

```
.meta exists? (HAS_META from ctx.py)
  YES → read normally (no change to current behaviour)
  NO  → on a feature branch? (CURRENT_BRANCH != main && CURRENT_BRANCH != BASE_BRANCH)
    NO (on main/base) → "Nothing to close — you're on main." Exit cleanly.
    YES → graceful degradation:
      1. Resolve issue:
         - INFERRED_ISSUE populated (from ctx.py) →
           gh issue view INFERRED_ISSUE --repo OWNER_REPO,
           extract title and confirm with user
         - INFERRED_ISSUE populated but gh issue view fails
           (network error, issue not found, OWNER_REPO empty) →
           present inferred number for manual confirmation:
           "Branch references issue #N but verification failed —
           confirm, enter a different number, or skip."
           Fall through to the interactive path on failure.
         - INFERRED_ISSUE empty →
           ask user for one-line work description,
           offer to invoke issue-workflow Phase 2 to create an issue
         - User declines issue creation →
           set ISSUE_N="" and COVERS="".
           Steps depending on ISSUE_N (8e spec posting, 8a issue close)
           are skipped.
      2. Set context values (from ctx.py output + defaults):
         - BRANCH_NAME = CURRENT_BRANCH (from ctx.py — the git branch name)
         - ISSUE_N = confirmed issue number (or empty if declined)
         - ISSUE_REPO = OWNER_REPO (from ctx.py)
         - COVERS = ISSUE_N (single issue only; see Limitations below)
         - DESIGN_REPO_KEY = "" (from ctx.py; Step 3 defaults to "project")
         - PROJECT_SHA = "" (no baseline)
         - META_SECTION_HASHES = "" (no section hashes)
         - FLYWAY_NEXT_V = "" (from ctx.py, already empty without .meta)
      3. Proceed with normal close flow using these values
```

#### Step 3 modification

Step 3 currently re-reads `.meta` directly for `DESIGN_REPO_KEY`:
```bash
DESIGN_REPO_KEY=$(grep "^design-repo:" "$WORKSPACE/design/.meta" | sed 's/design-repo: //')
```

This contradicts Step 0's contract ("all values come from ctx.py output") and
fails when `.meta` is absent. Fix: use `DESIGN_REPO_KEY` from ctx.py output.
When empty (no `.meta`), apply the existing default case (`*) → "project"`).

The architectural invariant is preserved: ctx.py reads `design-repo` from `.meta`
(creation-time routing), not from config. The "never re-derive from routing config"
principle (ARC42STORIES.MD line 679) is maintained — ctx.py reads `.meta`, Step 3
uses ctx.py's value.

#### Step 5 and Step 8d skip paths

**Step 5 (journal validation):** When `PROJECT_SHA` is empty (`HAS_META=no`),
`section_drift` will be empty (no baseline hashes to compare). The remaining
checks (`arc42_exists`, `empty_journal`) still apply — a branch without `.meta`
can still have a journal.

**Step 8d (journal merge):** When `PROJECT_SHA` is empty, skip journal merge
entirely. The baseline read (`git show "$PROJECT_SHA":ARC42STORIES.MD`) requires
a valid SHA. Journal entries on the branch are preserved but not merged into
ARC42STORIES.MD — this is the expected degradation (no baseline = no three-way
merge possible).

#### Slot mode + missing .meta

Reconstruction works the same way in slot mode. The reconstruction block
produces `BRANCH_NAME` from `CURRENT_BRANCH`, which is valid in a slot worktree.
Phase A/B uses `BRANCH_NAME` (reconstructed) and repos from SLOT.md or directory
scan — neither depends on `.meta` directly. `DESIGN_REPO_KEY` defaults to
"project" — in a slot, `$PROJECT` is the primary repo worktree, which is correct.

#### Limitations

- **Multi-issue COVERS:** Branches with multi-issue COVERS that lose their
  `.meta` will close only the primary inferred issue. Additional issues must be
  closed manually. This is inherent — multi-issue tracking requires `.meta`.
- **Journal merge:** Skipped entirely without `.meta` (no baseline SHA). Journal
  entries on the branch are preserved but not merged into ARC42STORIES.MD.
- **Design routing:** Defaults to "project." Branches that used workspace routing
  at creation time lose that information without `.meta`. This is acknowledged —
  `.meta` is the immutable record of creation-time routing (ARC42STORIES.MD L679).

#### What changes

- **ctx.py** — add `INFERRED_ISSUE` output (parse `CURRENT_BRANCH` for
  `issue-(\d+)` when `ISSUE_N` is empty). Additive — no existing output changes.
- **work-end/SKILL.md** pre-condition 2 — replace hard gate with graceful
  degradation block
- **work-end/SKILL.md** Step 3 — use `DESIGN_REPO_KEY` from ctx.py output;
  when empty, default to "project". Remove redundant `.meta` re-read.
- **work-end/SKILL.md** Step 5 — clarify that `section_drift` checks are
  no-ops when `PROJECT_SHA` is empty (no baseline to compare)
- **work-end/SKILL.md** Step 8d — add skip path: when `PROJECT_SHA` is empty,
  skip journal merge entirely
- **ARC42STORIES.MD** — update L2 Lifecycle section to document graceful `.meta`
  degradation as a supported mode alongside the normal `.meta`-present path

#### What doesn't change (for this issue)

- Pre-condition 3 (orphaned `.meta` on main) stays as-is
- `close_artifacts.py` unchanged (for this issue; issue #88 adds `scan-workspace`)
- ctx.py output contract for existing fields — `INFERRED_ISSUE` is additive
- Slot-mode detection unchanged
- All downstream steps receive values the same way (from ctx.py / SKILL.md context)

---

## Issue #88 — slot-mode per-repo sweep and scan-workspace

### Problem

In multi-repo slots, the pre-close sweep (Step 3b) and artifact promotion
target only the primary repo. Secondary repos' CLAUDE.md, docs, protocols,
and workspace artifacts are invisible.

### Design

Two changes: a per-repo sweep loop in SKILL.md, and a `scan-workspace`
parameter on `close_artifacts.py`.

#### Per-repo sweep (work-end Step 3b in slot mode)

Slot mode is detected by `/worktrees/` in the `$PROJECT` path (existing logic).

**Normal mode (no change):** sweeps run against `$PROJECT` as today.

**Slot mode — new Step 3b-slot:**

```
1. Discover repos in the slot:
   Priority: SLOT.md is authoritative (read via parse_slot_md() from
   slot_manager.py). Fallback: if SLOT.md is absent, scan the slot
   directory for git repos (via get_slot_repos()). SLOT.md is preferred
   because it records the intended repo set at slot creation; directory
   scan may find repos added ad-hoc after creation.

   - Primary repo = $PROJECT (the repo work-slot was invoked from)
   - Secondary repos = other repos in the slot

2. Per-repo loop (primary + secondaries), in this order:
   For each repo R:
     a. protocol sweep against R's docs/protocols/
        — captures rules first
     b. update-claude-md against R's CLAUDE.md
        — syncs conventions (including newly captured protocols)
     c. implementation-doc-sync against R's docs/
        — syncs documentation (using up-to-date CLAUDE.md)

   Each skill commits its own changes independently (per-skill commits,
   same as current non-slot behaviour). Batching commits per-repo would
   couple independent skills' fates — if the third skill fails, the first
   two's changes should still be committed. The squash step (8j)
   consolidates commit granularity before landing.

   Retargeting: the LLM sets repo R's path as context for each skill
   invocation, reading/writing R's files using absolute paths. Skills
   that invoke scripts with CWD assumptions may need explicit path
   parameters — discovered and addressed during implementation.

3. Session-bound (run once, not per-repo), in this order:
   a. forage SWEEP → global (no change)
   b. adr → primary workspace adr/ (shared across repos, not per-repo)
   c. write-content (diary) → primary workspace blog/ only
      — last, so it can synthesise the full branch narrative
```

#### close_artifacts.py scan-workspace parameter

New optional CLI parameter: `scan-workspace=<path>`

```bash
python3 close_artifacts.py <workspace> <project> <branch> \
  issue-repo=<repo> covers=<issues> \
  scan-workspace=<slot-workspace-path>
```

**When `scan-workspace` is provided:**
- Scan artifacts from the slot workspace at the given path
- Promote them to the original workspace (the `<workspace>` positional arg)
- Blog entries route to primary workspace only

**When omitted:** behaviour unchanged — scan `<workspace>` itself (current behaviour).

Called once per workspace in the slot. The loop lives in SKILL.md instructions,
not in the script — keeping `close_artifacts.py` composable and slot-agnostic.

#### Phase B step B4 wiring

In Phase B (slot mode), the original workspace is on main after B2 merge.
Artifacts to promote are on the **slot** workspace's branch. Step B4 must
pass `scan-workspace` when calling `close_artifacts.py`:

```bash
python3 close_artifacts.py <ORIGINAL_WORKSPACE> <PROJECT> <BRANCH_NAME> \
  issue-repo=<ISSUE_REPO> covers=<COVERS> \
  scan-workspace=<SLOT_WORKSPACE>
```

Without this, Phase B's `close_artifacts.py` would scan the original workspace
(now on main) and find no branch artifacts to promote.

#### What changes

- **work-end/SKILL.md** Step 3b — add slot-mode branch with per-repo sweep loop
- **work-end/SKILL.md** Phase B step B4 — pass `scan-workspace=<slot-workspace-path>`
  to `close_artifacts.py` (artifacts are on the slot workspace branch, not the
  original workspace which is on main after B2 merge)
- **work-end/close_artifacts.py** — add `scan-workspace` optional parameter;
  when present, scan artifacts from that path instead of the workspace arg
- **tests/** — new tests for `close_artifacts.py` covering `scan-workspace`

#### What doesn't change

- Normal-mode sweep (no slot) unchanged
- `close_artifacts.py` internal promotion logic unchanged — just a different source path
- Phase A/B split for slot mode unchanged
- `artifact_promote.py`, `blog_dest.py`, `branch_cleanup.py` unchanged

---

## Protocols

- **externalised-scripts-require-tests:** any changes to `close_artifacts.py` must
  ship with corresponding pytest tests in the same commit

## Testing

- **ctx.py** `INFERRED_ISSUE` — branch names matching `issue-NNN-*`, non-matching
  names, `.meta` present (should not infer), `.meta` absent with issue in branch name
- **close_artifacts.py** with `scan-workspace` — happy path, missing path, empty workspace
- **work-end SKILL.md** — instruction-only changes (pre-condition 2, Step 3, Step 5,
  Step 8d conditionals) are not unit-testable; validated through manual work-end runs
