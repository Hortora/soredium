# Subagent Delegation for work-end Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> executing-plans to implement this plan task-by-task. Each task
> uses the Edit tool for structural changes to SKILL.md.

**Focal issue:** #82 — Delegate mechanical lifecycle steps to subagents to prevent context overflow
**Issue group:** #82

**Goal:** Replace three read-heavy mechanical steps in work-end with subagent dispatches that return compact structured JSON, saving 900–4900 tokens of parent context per invocation.

**Architecture:** Three delegation points in work-end/SKILL.md. Each replaces an inline step block with a dispatch template that sends a subagent with concrete parameters, receives structured JSON, and feeds downstream steps. Existing Python helper scripts (artifact_promote.py, branch_cleanup.py, blog_dest.py) are unchanged. The git-squash skill's squash-policy.md and rebase_exec.py are referenced by the squash analysis subagent but not modified.

**Tech Stack:** Markdown (SKILL.md editing), Agent tool (subagent dispatch), JSON (return formats)

## Global Constraints

- All edits target `work-end/SKILL.md` in the soredium repo
- No separate prompt files — dispatch templates are inline in the skill
- Subagents are read-only — all mutations stay in the parent
- Return format validation: all fields required, arrays may be empty
- Sync to `~/.claude/skills/` via `sync-local` after all edits
- Run `python3 scripts/validate_all.py --tier commit` after each task to catch structural issues

---

### Task 1: Branch Reconnaissance Delegation (Steps 1 + 5)

**Files:**
- Modify: `work-end/SKILL.md` — replace Step 0+1 branch summary block and Step 5 journal validation block with a single delegation dispatch block

**Interfaces:**
- Consumes: ctx.py output (WORKSPACE, PROJECT, BRANCH_NAME, BASE_BRANCH, ISSUE_N, COVERS, ISSUE_REPO, PROJECT_SHA, META_SECTION_HASHES), DESIGN_REPO from Step 3 resolution
- Produces: JSON with `issues`, `commits`, `commit_count`, `diff_stats`, `journal_entry_count`, `journal_validation` — consumed by Step 7 (close plan) and journal validation decisions

**Context:** Currently Step 0+1 runs 4 bash commands (gh issue view, git log, git diff --shortstat, journal entry count) with their output staying in parent context. Step 5 runs section hash comparison and anchor counting. Both are replaced by a single subagent dispatch that returns compact JSON.

The new step runs AFTER Step 3 (routing resolution) because it needs DESIGN_REPO for journal validation. Step 4 (artifact inventory) remains inline after Step 3b (pre-close sweep) since 3b creates artifacts.

- [ ] **Step 1: Locate the branch summary block in work-end/SKILL.md**

Find the section starting with `## Step 0 + Step 1 — Context` (around line 108) through the end of the branch summary output format block (around line 154). This entire block is replaced.

Read work-end/SKILL.md lines 108–154 to confirm the exact boundaries.

- [ ] **Step 2: Replace the branch summary block with reconnaissance dispatch**

Replace the `## Step 0 + Step 1` section with a new `## Step 1 — Branch Reconnaissance (delegated to subagent)` section. The new section contains:

1. A brief description: "Dispatch a read-only Sonnet subagent to gather branch state and validate the journal. Runs after Step 3 (routing resolution) which provides DESIGN_REPO."

2. The dispatch template showing the Agent tool call with:
   - `description: "Branch reconnaissance for work-end"`
   - `model: "sonnet"`
   - Inline prompt template with `{PLACEHOLDER}` values listing all parameters from ctx.py and Step 3
   - The prompt tells the subagent to:
     - Fetch issue titles from GitHub for all COVERS issues
     - Run git log --oneline and git diff --shortstat
     - Read JOURNAL.md and count entries
     - Run section_hashes.py on ARC42STORIES.MD in DESIGN_REPO
     - Compare against META_SECTION_HASHES baseline
     - Count anchored vs unanchored entries
     - Return JSON matching the spec's return format

3. The return format JSON block (from spec §1)

4. On-return instructions:
   - Validate JSON shape (all required keys present)
   - If malformed: warn user, fall back to inline Steps 1+5
   - Use `journal_validation` for Step 5 decisions (drift → fix/skip/abort)
   - Use `commits`, `diff_stats`, `journal_entry_count` for Step 7 close plan
   - Use `issues` for branch summary display

5. The branch summary display format (the `╔══ Branch Summary` box) — constructed from JSON fields, not raw git output.

- [ ] **Step 3: Remove Step 5 journal validation block**

Find `## Step 5 — Journal validation` (around line 333) through the end of `**5d — Empty journal**` (around line 359). Replace the entire block with:

```markdown
## Step 5 — Journal validation decisions

Journal validation data comes from the Branch Reconnaissance subagent
(Step 1). Use the `journal_validation` field from its return to drive
decisions:

- **`section_drift` non-empty:** `[U]` update journal anchors, `[S]` skip drifted sections, `[A]` abort
- **`unanchored_entries > 0`:** `[F]` fix via update-design, `[S]` skip merge, `[C]` continue accepting loss
- **`empty_journal == true`:** `[W]` write retrospective via update-design, `[S]` skip and accept permanent loss
- **`arc42_exists == false`:** `[C]` create from journal entries, `[S]` skip merge entirely
```

- [ ] **Step 4: Update Step 7 close plan to reference JSON fields**

In the Step 7 close plan section, update any references to "branch summary from Step 1" or "journal validation from Step 5" to reference the reconnaissance JSON fields explicitly. The close plan should say things like "from Branch Reconnaissance: {commit_count} commits, {diff_stats}" rather than recalling raw git output.

- [ ] **Step 5: Update the Skill Chaining / Reads from section**

At the bottom of the skill, update the `**Reads from:**` line to include "Branch Reconnaissance subagent JSON" alongside the existing sources.

- [ ] **Step 6: Validate**

```bash
python3 scripts/validate_all.py --tier commit
```

Expected: PASS with no CRITICAL findings. WARNING is acceptable if it flags a section reference that moved.

- [ ] **Step 7: Sync and commit**

```bash
python3 scripts/claude-skill sync-local --all -y
git -C /Users/mdproctor/claude/hortora/soredium add work-end/SKILL.md
git -C /Users/mdproctor/claude/hortora/soredium commit -m "feat(#82): delegate branch reconnaissance to subagent in work-end

Replace Steps 1 + 5 (branch summary, journal validation) with a single
Sonnet subagent dispatch. Raw git/GitHub output stays in the subagent's
context; parent receives compact JSON for the close plan and journal
validation decisions.

Refs #82"
```

---

### Task 2: Hygiene Scan Delegation (Step 8i)

**Files:**
- Modify: `work-end/SKILL.md` — replace Step 8i hygiene scan block with a delegation dispatch block

**Interfaces:**
- Consumes: WORKSPACE, PROJECT, BRANCH_NAME from ctx.py; blog destination path from Step 3 routing; Flyway status from .meta; SINGLE_REPO_MODE from ctx.py
- Produces: JSON with `unpublished_blogs`, `flyway_conflicts`, `stale_branches`, `unrecovered_artifacts`, `unstamped_branches` — consumed by parent for user-facing offers (cherry-pick, stamp, blog retry)

**Context:** Step 8i currently runs ~60 lines of multi-branch scanning with `comm`, `git log`, `git show`, and issue API calls. The subagent absorbs all this; the parent only sees findings that need user action.

- [ ] **Step 1: Locate Step 8i in work-end/SKILL.md**

Find `### 8i — Hygiene scan` (around line 533) through the end of the unstamped branches stamp block (around line 596). Read to confirm exact boundaries.

- [ ] **Step 2: Replace Step 8i with hygiene scan dispatch**

Replace the entire `### 8i — Hygiene scan` section with a new `### 8i — Hygiene scan (delegated to subagent)` section containing:

1. Brief description: "Dispatch a read-only Sonnet subagent to scan for hygiene issues across workspace branches."

2. Dispatch template with:
   - `description: "Hygiene scan for work-end"`
   - `model: "sonnet"`
   - Inline prompt listing parameters and telling the subagent to:
     - Compare workspace blog files against blog destination (from routing)
     - Check Flyway V-number collisions if applicable
     - List branches with no commits in 7 days
     - For branches with EPIC-CLOSED.md: check artifact recovery and stamp status
     - Skip the current BRANCH_NAME
     - Handle SINGLE_REPO_MODE (same repo for workspace and project)
   - Return JSON matching the spec §3 format

3. Return format JSON block

4. On-return instructions:
   - `unpublished_blogs` non-empty → block and return to 8g (max 2 attempts; after second failure offer manual fix/skip/abort)
   - `unrecovered_artifacts` → offer cherry-pick per item (user confirms each)
   - `unstamped_branches` → offer stamp per branch (user confirms each)
   - `stale_branches` → report informational only
   - `flyway_conflicts` → warn informational
   - If malformed JSON → warn and skip (hygiene is advisory). Exception: if blog verification can't run, warn explicitly.

- [ ] **Step 3: Validate**

```bash
python3 scripts/validate_all.py --tier commit
```

- [ ] **Step 4: Sync and commit**

```bash
python3 scripts/claude-skill sync-local --all -y
git -C /Users/mdproctor/claude/hortora/soredium add work-end/SKILL.md
git -C /Users/mdproctor/claude/hortora/soredium commit -m "feat(#82): delegate hygiene scan to subagent in work-end

Replace Step 8i (multi-branch scanning, blog verification, stamp checks)
with a Sonnet subagent. Findings returned as JSON; parent handles user
confirmations for cherry-picks and stamps. Circuit breaker on blog
retry loop (max 2 attempts).

Refs #82"
```

---

### Task 3: Squash Analysis Delegation (Step 8j analysis phase)

**Files:**
- Modify: `work-end/SKILL.md` — split Step 8j into delegated analysis + inline execution

**Interfaces:**
- Consumes: PROJECT, BASE_BRANCH, BRANCH_NAME, COVERS from ctx.py; blessed remote name; paths to squash-policy.md, git-squash SKILL.md, commit_gather.py; SINGLE_REPO_MODE
- Produces: JSON with `total_commits`, `strategy`, `groups` (with per-commit classifications, flags, proposed messages), `sub_issue_refs`, `refs_not_in_covers`, `warnings`, `blocking_flags` — consumed by parent for plan display, approval gate, and rebase_exec.py execution

**Context:** This is the most complex and highest-value delegation. The current Step 8j interleaves analysis (commit classification) with execution (rebase, squash, push). The split separates these: analysis goes to an Opus subagent, execution stays inline. The subagent self-reads squash-policy.md and the classification steps (3a–3i) from git-squash SKILL.md.

- [ ] **Step 1: Locate the squash section in Step 8j**

Find the squash-related content in `### 8j` (around line 644). The section currently says "Invoke `/git-squash` with the range..." and includes sub-issue reference collection. Read the full 8j section to identify what is analysis (delegated) vs execution (stays inline).

- [ ] **Step 2: Replace the squash analysis portion of Step 8j**

Within `### 8j`, after the rebase block and before the push block, replace the squash invocation with a new subsection `**Squash analysis (delegated to subagent):**` containing:

1. Brief description: "Dispatch an Opus subagent to classify commits and propose a squash plan. The subagent reads squash-policy.md and git-squash SKILL.md Steps 3a–3i for classification rules."

2. Dispatch template with:
   - `description: "Squash analysis for work-end"`
   - `model: "opus"`
   - Inline prompt listing parameters and telling the subagent to:
     - Run commit_gather.py for structured per-commit data
     - Read squash-policy.md for classification rules
     - Read git-squash SKILL.md Step 3 and sub-steps 3a–3i only (ignore Steps 0–2 and 4–9)
     - Run strategy detection (merge-commit PRs → reconstruction, else scope clustering or flat)
     - Classify each commit: KEEP / SQUASH / MERGE / DROP
     - Propose groups with draft messages, per-commit flags, per-group annotations
     - Collect sub-issue references, cross-reference against COVERS
   - Return JSON matching the spec §2 format

3. Return format JSON block (including `flags`, `annotations`, `warnings`, `blocking_flags`)

4. On-return instructions:
   - Format groups into plan display with per-commit flags and group annotations
   - Present for user approval (accept / edit / reject)
   - If `blocking_flags` non-empty: resolve before allowing approval
   - On approval: execute squash (see below)
   - If malformed JSON: warn, offer `/git-squash` manually or skip

5. **Single-repo filter-repo preprocessing:** Before dispatching the subagent in single-repo mode:
   - Create temporary working branch from base branch
   - Run filter-repo to strip scaffold paths (`.meta`, `JOURNAL.md`, `design/`) with `--prune-empty always`
   - Dispatch subagent on post-filter-repo branch
   - After squash execution, swap working branch with base branch via `branch_swap.py`

6. **Execution after approval (inline — not delegated):**
   - Build rebase todo from approved groups (pick + fixup lines)
   - For groups with proposed_message: append `exec git commit --amend -m "..." ` lines (using multiple `-m` flags for trailers, not `\n`)
   - Call `rebase_exec.py multi <PROJECT> base=<base-sha> todo-file=<path>`
   - Run post-squash interval tree verification (5 samples)
   - `refs_not_in_covers` appended as `Closes #N` trailers to the final group's message

- [ ] **Step 3: Remove the inline sub-issue reference collection**

The current Step 8j has a "Collect sub-issue references before squash" block with git log grep. Remove it — the subagent's `sub_issue_refs` and `refs_not_in_covers` fields replace this.

- [ ] **Step 4: Update the Skill Chaining section**

In the `**Invokes:**` list, change:
- `git-squash` — Step 8j (mandatory before fork push)
to:
- `git-squash` — Step 8j subagent reads squash-policy.md and SKILL.md Steps 3a–3i; parent calls rebase_exec.py directly for execution

- [ ] **Step 5: Validate**

```bash
python3 scripts/validate_all.py --tier commit
```

- [ ] **Step 6: Sync and commit**

```bash
python3 scripts/claude-skill sync-local --all -y
git -C /Users/mdproctor/claude/hortora/soredium add work-end/SKILL.md
git -C /Users/mdproctor/claude/hortora/soredium commit -m "feat(#82): delegate squash analysis to subagent in work-end

Split Step 8j into delegated analysis (Opus subagent classifies commits
per squash-policy.md) and inline execution (rebase_exec.py). Subagent
reads git-squash SKILL.md Steps 3a-3i for classification; parent
presents plan for approval and executes. Sub-issue reference collection
moved from inline to subagent.

Single-repo mode runs filter-repo preprocessing to strip scaffold
commits before classification.

Refs #82"
```

---

### Task 4: Final Validation and Documentation

**Files:**
- Modify: `work-end/SKILL.md` — verify all cross-references are consistent
- Run: validation suite

**Interfaces:**
- Consumes: all three delegation blocks from Tasks 1–3
- Produces: validated, committed, synced skill

- [ ] **Step 1: Read the modified skill end-to-end**

Read work-end/SKILL.md from top to bottom. Check:
- Step ordering makes sense (Path Resolution → Pre-conditions → Step 1 Recon → Step 2 Flyway → Step 3 Routing → Step 3b Sweep → Step 3c Review → Step 4 Inventory → Step 5 Journal decisions → Step 6 Specs → Step 7 Plan → Step 8 Execute including delegated 8i and 8j)
- No dangling references to removed inline steps
- Close plan (Step 7) correctly references JSON fields from reconnaissance
- 8h final report correctly references inline Step 4 artifacts (not reconnaissance)
- Skill Chaining section is complete and accurate

- [ ] **Step 2: Run full commit-tier validation**

```bash
python3 scripts/validate_all.py --tier commit
```

Fix any CRITICAL or WARNING findings.

- [ ] **Step 3: Follow docs/development/readme-sync.md**

Since SKILL.md was modified, follow the readme-sync workflow to check if README.md needs updating. The changes are internal to work-end's step structure — the skill's external interface (name, description, chaining) is unchanged, so README likely needs no update. But follow the workflow to let it decide.

- [ ] **Step 4: Final sync**

```bash
python3 scripts/claude-skill sync-local --all -y
```

Verify the installed skill at `~/.claude/skills/work-end/SKILL.md` matches the repo version.

- [ ] **Step 5: Commit any remaining changes**

If readme-sync produced changes:

```bash
git -C /Users/mdproctor/claude/hortora/soredium add -A
git -C /Users/mdproctor/claude/hortora/soredium commit -m "docs(#82): sync README after work-end subagent delegation

Refs #82"
```
