# Delegate Mechanical work-end Steps to Subagents

**Issue:** Hortora/soredium#82
**Date:** 2026-07-17
**Status:** Approved

## Problem

work-end accumulates 2200–6800 tokens of intermediate tool output (git logs,
file listings, issue API responses, journal content) across its 12+ steps.
By the time it reaches squash analysis (Step 8j), the context window is
stressed — Claude frequently suggests continuing in a new session, which
loses the context needed for remaining steps.

## Solution

Replace three groups of read-heavy mechanical steps with subagent dispatches.
Each subagent runs in an isolated context, absorbs all intermediate output,
and returns a compact structured JSON result. The parent context sees the
dispatch prompt (~350–550 tokens) and the return value (~200–350 tokens),
instead of the full raw output (500–3500 tokens per group).

## Scope

**In scope:** work-end only (Approach A — surgical).
**Out of scope:** handover (#83), work-start, git-commit. Handover follows
once the pattern is proven.

### Not Delegated (with rationale)

Issue Hortora/soredium#82 lists five work-end delegation candidates. Three are
addressed below. Two are intentionally not delegated:

- **Pre-conditions check** (.pause-stack, .meta, working tree, remote state):
  Each failure requires immediate human interaction — hard stops, choice prompts,
  branch switching offers. The check itself is cheap (~100 tokens of status output);
  the value is the interactive response to each failure, which must stay in the
  parent. Delegating saves nothing and adds latency.

- **Routing resolution** (read routing cascade, detect capabilities, resolve
  DESIGN_REPO): Requires user confirmation of the resolved routing table before
  proceeding. The resolution logic is a few config reads and a table display
  (~150 tokens). The interaction makes delegation awkward — the subagent would
  return a table, the parent would display it, the user would confirm, then the
  parent would proceed. No token savings justify the round-trip.

## Delegation Points

### 1. Branch Reconnaissance (replaces Steps 1 + 5)

**When:** After path resolution and routing resolution (Step 3), before
pre-close sweep (Step 3b). Step 3 must complete first because it resolves
DESIGN_REPO, which this subagent needs for journal validation.

**What the subagent does:**
- Fetches issue title(s) from GitHub for all COVERS issues
- Runs `git log --oneline` for branch commits
- Runs `git diff --shortstat` for change summary
- Reads JOURNAL.md and counts entries
- Computes current ARC42STORIES.MD section hashes via `section_hashes.py`
- Compares against baseline hashes from .meta
- Counts anchored vs unanchored journal entries

**Step 4 (artifact inventory) remains inline.** The pre-close sweep (Step 3b)
creates artifacts — blog entries, ADRs, specs. Step 4 must run after 3b to
inventory the complete set. It is cheap (~5 `ls` commands, ~100 tokens) and
does not benefit from delegation.

**Prompt parameters (from ctx.py and Step 3 resolution):**
- WORKSPACE, PROJECT, BRANCH_NAME, BASE_BRANCH
- ISSUE_N, COVERS, ISSUE_REPO (for GitHub API)
- PROJECT_SHA (for diff range)
- META_SECTION_HASHES (pipe-separated baseline hashes from ctx.py output)
- DESIGN_REPO (resolved filesystem path from Step 3 — not the key)
- SECTION_HASHES_SCRIPT (`~/.claude/skills/project/section_hashes.py`)
- SINGLE_REPO_MODE (yes/no — when yes, WORKSPACE == PROJECT)

**Return format (all fields required; arrays may be empty):**
```json
{
  "issues": [{"number": 82, "title": "...", "state": "OPEN"}],
  "commits": [{"sha": "abc1234", "message": "feat: ..."}],
  "commit_count": 5,
  "diff_stats": "4 files changed, 120 insertions, 30 deletions",
  "journal_entry_count": 3,
  "journal_validation": {
    "arc42_exists": true,
    "section_drift": [{"section": "## S5", "stored_hash": "abc", "current_hash": "def"}],
    "anchored_entries": 2,
    "unanchored_entries": 1,
    "entries_without_anchors": ["### Entry about X"],
    "empty_journal": false
  }
}
```

**Downstream consumers:**
- Step 7 (close plan) uses `commits`, `diff_stats`, `journal_entry_count`
- Step 7 also uses `artifacts` from inline Step 4 (not from this subagent)
- Step 5 decisions use `journal_validation` (drift → offer fix/skip/abort)
- Step 8h (final report) uses `artifacts` from inline Step 4

**Error handling:** If the subagent returns empty or malformed JSON, warn
the user and fall back to running Steps 1, 5 inline. This is graceful
degradation — the skill works exactly as before, just without the context
savings.

**Model:** Sonnet (mechanical — git commands, hash comparison, GitHub API).

**Estimated savings:** 500–1400 tokens of raw output → ~550 tokens
(prompt ~350 + return ~200). Net savings: ~150–850 tokens.

---

### 2. Squash Analysis (replaces analysis phase of Step 8j)

**When:** After rebase onto base branch, before squash execution.

**What the subagent does:**
- Runs `commit_gather.py` to collect structured per-commit data (sha, subject,
  body, author, date, files, insertions, deletions, issue_refs, patch_id)
- Self-reads `squash-policy.md` for classification rules
- Self-reads git-squash `SKILL.md` — the prompt directs it to Step 3
  ("Classify commits") and its sub-steps 3a–3i for the full classification
  procedure (same-issue clustering, CI arc detection, proximity-grouped
  resolution, temporal scrutiny, file-overlap MERGE, cross-author check,
  cherry-pick detection). The prompt explicitly tells the subagent to
  ignore Steps 0–2 (working branch, filter-repo, range resolution) and
  Steps 4–9 (plan display, execution, review gate, swap). The SKILL.md
  has clear `###` step headers making section navigation reliable.
- Runs strategy detection (merge-commit PRs → reconstruction, else scope
  clustering or flat)
- Classifies each commit: KEEP / SQUASH / MERGE / DROP
- Proposes groups with draft squash messages and per-commit/per-group annotations
- Collects sub-issue references (`Closes #N`, `Fixes #N`, `Resolves #N`) from
  branch commits
- Cross-references against COVERS to identify refs that would be lost in squash

**Prompt parameters:**
- PROJECT path
- BASE_BRANCH, BRANCH_NAME
- COVERS (comma-separated issue numbers)
- Blessed remote name (upstream or origin)
- Path to squash-policy.md
- Path to git-squash SKILL.md
- Path to commit_gather.py
- SINGLE_REPO_MODE (yes/no)

**Return format (all fields required; arrays may be empty):**
```json
{
  "total_commits": 8,
  "strategy": "D",
  "groups": [
    {
      "label": "feat(#82): delegate lifecycle steps to subagents",
      "action": "KEEP",
      "commits": [
        {
          "sha": "abc1234",
          "message": "feat: ...",
          "classification": "KEEP",
          "flags": []
        }
      ],
      "proposed_message": "feat(#82): delegate mechanical work-end steps to subagents\n\nRefs #82",
      "annotations": []
    },
    {
      "label": "squash: fixups and docs",
      "action": "SQUASH",
      "commits": [
        {
          "sha": "def5678",
          "message": "fix: typo",
          "classification": "SQUASH",
          "flags": ["proximity-grouped"]
        },
        {
          "sha": "ghi9012",
          "message": "docs: update readme",
          "classification": "SQUASH",
          "flags": []
        }
      ],
      "proposed_message": null,
      "annotations": ["proximity-grouped: no semantic overlap with KEEP target"]
    }
  ],
  "sub_issue_refs": ["#83"],
  "refs_not_in_covers": ["#83"],
  "warnings": [],
  "blocking_flags": []
}
```

Per-commit `flags` carry annotations that the parent surfaces in the plan
display (e.g. `proximity-grouped`, `temporal:18min`, `cross-author`,
`cherry-pick:release/2.1`, `file-overlap:group-3`). Per-group `annotations`
carry group-level context (title fitness warnings, handover-survived-filter,
net-no-op pairs). `warnings` are informational messages for the user.
`blocking_flags` are issues that must be resolved before execution (e.g.
duplicate `Closes #N`).

**Downstream consumers:**
- Parent formats groups into the plan display, presenting per-commit flags and
  group annotations alongside classifications and proposed messages
- Parent presents the plan for user approval (accept / edit / reject)
- On approval, parent executes the squash via `rebase_exec.py` (see below)
- `refs_not_in_covers` are appended as `Closes #N` trailers to the squash message

**Execution after approval (parent — not the full git-squash skill):**

The parent calls `rebase_exec.py` directly. Invoking the full `/git-squash`
skill would re-classify all commits, re-present a plan, and duplicate the
subagent's work. The execution path:

1. Build a rebase todo file from the approved groups. For each group:
   - One `pick` line for the KEEP commit, then `fixup` lines for absorbed commits
   - If the group has a non-null `proposed_message`: append an
     `exec git commit --amend -m "<proposed_message>"` line after the group's
     last `fixup`. At this point in the rebase, HEAD is the group's KEEP
     commit, so `--amend` targets the correct commit.
   - For the last group: if `refs_not_in_covers` is non-empty, add the
     `Closes #N` trailers via a separate `-m` flag (git separates each
     `-m` argument with a blank line — `\n` inside double quotes produces
     literal backslash-n in `sh -c`, not a newline).
   Example todo for 3 groups:
   ```
   pick abc1234 feat: group 1
   fixup aaa1111 absorbed commit
   exec git commit --amend -m "feat(#82): group 1 proposed message"
   pick def5678 feat: group 2
   fixup bbb2222 absorbed commit
   exec git commit --amend -m "feat(#83): group 2 proposed message"
   pick ghi9012 docs: group 3
   fixup ccc3333 absorbed commit
   exec git commit --amend -m "docs: group 3 proposed message" -m "Closes #84"
   ```
2. Call `rebase_exec.py multi <PROJECT> base=<base-sha> todo-file=<path>` —
   on failure, the script auto-aborts and restores pre-squash state
3. Run post-squash interval tree verification (5 evenly-spaced samples,
   same procedure as git-squash Step 6)

Working branch is not needed in the two-repo case — the Step 8j rebase
already brought commits onto the base branch, `rebase_exec.py` auto-aborts
on failure, and the original feature branch ref provides a safety net.

**Single-repo filter-repo:** In single-repo mode, the Step 8j rebase
brings scaffold commits (`.meta`, `JOURNAL.md`, `design/` directory) onto
the base branch alongside real commits. In two-repo mode these files live
in the workspace repo and never enter the project squash range.

Before dispatching the subagent in single-repo mode, the parent must:
1. Create a temporary working branch from the base branch
2. Run `filter-repo` on it to strip scaffold paths (`.meta`, `JOURNAL.md`,
   `design/`) with `--prune-empty always`
3. Dispatch the subagent to classify on the post-filter-repo branch
4. Execute the squash on the working branch
5. Swap the working branch with the base branch via `branch_swap.py`

The scaffold paths are deterministic (always the same files), so no Q&A
is needed — the parent knows what to strip. Step 8j-cleanup (which removes
scaffold from main after squash) is still needed to clean the working tree,
but filter-repo ensures scaffold commits don't pollute the squash groups.

**Sub-issue reference collection:** The subagent's `sub_issue_refs` and
`refs_not_in_covers` replace the inline "Collect sub-issue references
before squash" section in work-end Step 8j. The inline collection is
removed — the subagent does this as part of its classification pass.

**Error handling:** If the subagent returns empty or malformed JSON, warn
and offer: (a) invoke `/git-squash` manually, (b) skip squash entirely
(user takes responsibility for noisy history).

**Model:** Opus. The classification procedure involves reasoning-intensive
passes: same-issue clustering across non-adjacent commits, CI development arc
detection, proximity-grouped resolution with semantic scanning, title fitness
assessment, and cross-author policy application. These are judgment tasks,
not pattern matching.

**Estimated savings:** 1500–3500 tokens of inline output (commit_gather data,
classification reasoning, policy reads) → ~900 tokens (prompt ~550 + return
~350). Net savings: ~600–2600 tokens. This is the single highest-value
delegation point.

---

### 3. Hygiene Scan (replaces Step 8i)

**When:** After execution steps 8a–8h, before squash (8j).

**What the subagent does:**
- Verifies all workspace blog entries exist at the blog destination
  (reads blog-routing.yaml, compares file lists)
- Checks for Flyway V-number collisions if Flyway was used on this branch
- Lists workspace branches with no commits in 7 days (stale)
- For each workspace branch with `design/EPIC-CLOSED.md`:
  - Checks whether blog/spec files reached workspace main (unrecovered artifacts)
  - Checks whether the corresponding project branch has a `chore: branch closed` stamp
- Skips the CURRENT branch being closed (it's handled by 8j)

**Prompt parameters:**
- WORKSPACE, PROJECT, BRANCH_NAME
- Blog destination path (from routing resolution in Step 3)
- Whether Flyway was used on this branch (from .meta)
- SINGLE_REPO_MODE (yes/no — when yes, workspace branches and project branches
  are the same repo; the "corresponding project branch" check for unstamped
  branches checks the same branch, not a separate repo)

**Return format (all fields required; arrays may be empty):**
```json
{
  "unpublished_blogs": ["2026-07-15-entry.md"],
  "flyway_conflicts": [],
  "stale_branches": [
    {"branch": "issue-71-old", "last_commit_age": "12 days"}
  ],
  "unrecovered_artifacts": [
    {"branch": "issue-50-closed", "type": "blog", "file": "2026-06-01-entry.md"},
    {"branch": "issue-50-closed", "type": "spec", "file": "design-doc.md"}
  ],
  "unstamped_branches": [
    {"branch": "issue-50-closed", "has_epic_closed": true, "project_branch_exists": true}
  ]
}
```

**Downstream consumers:**
- `unpublished_blogs` non-empty → parent blocks and returns to 8g (max 2 attempts;
  after second failure, present user with options: fix routing manually, skip with
  warning, or abort close — do not loop indefinitely)
- `unrecovered_artifacts` → parent offers cherry-pick per item (user confirms each)
- `unstamped_branches` → parent offers to stamp per branch (user confirms each)
- `stale_branches` → parent reports (informational only)
- `flyway_conflicts` → parent warns (informational)

**Error handling:** If the subagent returns empty or malformed JSON, warn
and skip. Hygiene is advisory — it catches drift but doesn't block the close.
Exception: if blog verification cannot run, warn explicitly since unpublished
blogs DO block.

**Model:** Sonnet (file comparisons, git branch scanning).

**Estimated savings:** 500–2000 tokens of raw output → ~550 tokens
(prompt ~350 + return ~200). Net savings: ~150–1450 tokens.

---

## Dispatch Template Pattern

All three delegation points follow the same pattern in work-end's SKILL.md:

```markdown
### Step N — [Name] (delegated to subagent)

Dispatch a read-only subagent. The subagent's execution stays in its own
context — only the JSON return enters the parent window.

**Dispatch:**

Agent(
  description: "[short label]",
  prompt: "[inline template with {PLACEHOLDER} values substituted from ctx.py]",
  model: "[sonnet or opus — see each delegation point's Model section]"
)

**Return format:**
[JSON schema]

**On return:**
- Validate JSON shape (required keys present)
- If malformed: [specific fallback per delegation point]
- Use [specific fields] for [downstream step]
```

The prompt is inline in the skill — no separate prompt files. When the
subagent needs policy knowledge (squash analysis), the prompt tells it
to read the existing source-of-truth file (squash-policy.md). No
convention duplication.

## Modification Summary

### Lines removed from work-end SKILL.md
- Step 1 branch summary block (~30 lines)
- Step 5 journal validation block (~30 lines)
- Step 8i hygiene scan block (~60 lines)
- Step 8j analysis interleaved with execution (~50 lines of analysis logic,
  including inline sub-issue reference collection — replaced by subagent)
- **Total: ~170 lines removed**

### Lines added
- Branch reconnaissance dispatch block (~35 lines)
- Squash analysis dispatch block (~40 lines)
- Hygiene scan dispatch block (~30 lines)
- **Total: ~105 lines added**

### Net: skill shrinks by ~65 lines

### Steps unchanged
- Path resolution (ctx.py) — already cheap
- Pre-conditions — already cheap, interactive (not delegated — see Scope)
- Flyway re-scan (Step 2) — one script call
- Routing resolution (Step 3) — cheap + interactive (not delegated — see Scope)
- Pre-close sweep (Step 3b) — interactive (user toggles)
- Code review (Step 3c) — interactive, invokes another skill
- Step 4 (artifact inventory) — remains inline after 3b; cheap (~100 tokens)
- Spec selection (Step 6) — interactive
- Close plan (Step 7) — synthesis, now from compact JSON + inline Step 4
- Execution steps 8a–8h — destructive, need user confirmation
- Steps 9–12 — interactive or synthesis

## Total Context Savings

Estimates include both the prompt template and return value in the "After"
column. Prompt templates contain inline instructions plus substituted
parameter values; they are not negligible.

| Delegation | Before (tokens) | After (prompt + return) | Net savings |
|-----------|----------------|------------------------|-------------|
| Branch reconnaissance | 500–1400 | ~550 | 150–850 |
| Squash analysis | 1500–3500 | ~900 | 600–2600 |
| Hygiene scan | 500–2000 | ~550 | 150–1450 |
| **Total** | **2500–6900** | **~2000** | **900–4900** |

The parent context window reclaims 900–4900 tokens that previously
accumulated from intermediate tool output. The lower bound represents
small branches (few commits, few artifacts); the upper bound represents
complex branches with many commits and multiple artifact types. Both
ends are meaningful — even the lower bound keeps the context below the
threshold where Claude suggests continuing in a new session.

## Constraints

- Subagents cannot invoke skills or read CLAUDE.md — all instructions
  must be in the dispatch prompt or in files the prompt points to.
- Subagents should not write files or make destructive changes — they
  are read-only analysts. All mutations happen in the parent.
- Return format must be validated before use — a malformed return should
  never corrupt the close flow.

## Testing

Each delegation point can be tested by:
1. Running work-end on a test branch with the delegation active
2. Comparing the JSON return against manually computed expected values
3. Verifying the close plan (Step 7) renders correctly from the JSON
4. Verifying fallback behaviour when the subagent is artificially failed

No automated test infrastructure exists for skill execution — testing is
manual and observational. The existing `validate_all.py` validators check
SKILL.md structure, not runtime behaviour.
