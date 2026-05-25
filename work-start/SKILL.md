---
name: work-start
description: >
  Use when a task or session is beginning — the opening directive in any
  work-item prompt, or when the user says they are beginning work. Handles
  both new and existing branches. NOT optional, must NOT be skipped.
---

# work-start

Single entry point for all work. Detects state, creates or resumes a branch,
runs pre-checks. **Never skip this skill — even for small changes.**

---

## Path Resolution (run first, always)

```bash
WORKSPACE=$(git rev-parse --show-toplevel 2>/dev/null)
PROJECT=$(readlink -f proj 2>/dev/null)
[ -z "$PROJECT" ] && { echo "⚠️ No proj/ symlink found. Run workspace-init to set up."; exit 1; }
PROJECT_BASE_BRANCH=$(grep "^\*\*Project base branch:\*\*" CLAUDE.md 2>/dev/null | head -1 | sed 's/.*`\(.*\)`.*/\1/')
[ -z "$PROJECT_BASE_BRANCH" ] && PROJECT_BASE_BRANCH="main"
```

`WORKSPACE` is the git root of the current workspace. `PROJECT` follows the `proj/` symlink
to the project repo. All git commands use `-C "$WORKSPACE"` or `-C "$PROJECT"` explicitly.
Never use bare `git` without `-C <path>`. Never rely on CWD.

`PROJECT_BASE_BRANCH` is the project's base branch — read from `**Project base branch:** \`<name>\``
in CLAUDE.md; defaults to `main`. The workspace always uses `main` as its base branch.

---

## Branch Switch Helper

Use any time both repos must switch branches together. Never switch one alone.

```bash
git -C "$PROJECT" checkout <branch>
git -C "$WORKSPACE" checkout <branch>

PROJECT_BEHIND=$(git -C "$PROJECT" rev-list HEAD..origin/<branch> --count 2>/dev/null || echo 0)
WORKSPACE_BEHIND=$(git -C "$WORKSPACE" rev-list HEAD..origin/<branch> --count 2>/dev/null || echo 0)
if [ "$PROJECT_BEHIND" -gt 0 ] || [ "$WORKSPACE_BEHIND" -gt 0 ]; then
  echo "Remote has new commits (+${PROJECT_BEHIND} project, +${WORKSPACE_BEHIND} workspace)."
  echo "Incorporate now with pull --rebase? (y/n)"
  # Wait — user may not be ready for upstream changes
fi

PROJECT_BRANCH=$(git -C "$PROJECT" branch --show-current)
WORKSPACE_BRANCH=$(git -C "$WORKSPACE" branch --show-current)
[ "$PROJECT_BRANCH" = "$WORKSPACE_BRANCH" ] \
  || { echo "⚠️ Mismatch after switch. Manual alignment required."; exit 1; }
echo "✅ Both repos on: $PROJECT_BRANCH"
```

If helper fails (branch absent in one repo, network error): hard stop with
instructions. Do not loop.

---

## Detection

Resolve paths first. Then read:

```bash
META_BRANCH=$(grep "^branch:" "$WORKSPACE/design/.meta" 2>/dev/null | sed 's/branch: //')
CURRENT_WORKSPACE=$(git -C "$WORKSPACE" branch --show-current)
CURRENT_PROJECT=$(git -C "$PROJECT" branch --show-current)
```

Check in order — first match wins:

```
1. $WORKSPACE/design/.pause-stack exists and has entries, AND on main
   → Route to work skill for stack picker. Do not start a new branch until
     the user explicitly chooses "new" from the stack picker.
     (Stack depth 1: auto-route to work-resume. Stack depth 2+: show picker.)

2. $WORKSPACE/design/.meta exists, AND
   META_BRANCH == CURRENT_WORKSPACE == CURRENT_PROJECT (all three match)
   → Resume path.

3. $WORKSPACE/design/.meta exists, CURRENT_WORKSPACE == main
   (orphaned — .meta on main, regardless of project branch)
   → Hard stop. "Invoke work-end to complete or discard the abandoned branch."
   *** Checked BEFORE state 4 — orphaned also satisfies "branches misaligned"
   so state 4 would fire incorrectly and attempt to switch to a deleted branch. ***

4. $WORKSPACE/design/.meta exists, branches misaligned
   (META_BRANCH != CURRENT_WORKSPACE or CURRENT_PROJECT, and not orphaned)
   → Invoke Branch Switch Helper inline.
     If helper fails → hard stop with manual instructions (no loop).

5. CURRENT_WORKSPACE == main, no .meta, empty/absent .pause-stack
   → New branch path (Steps 0–12 below).

6. On non-main branch, no .meta
   → "You are on <branch> with no branch scaffold.
      Continue here (y) or switch to main (n)?"
      y → run Steps 0, 2, 3, 11 only. No scaffold created. Skip Step 4 —
            no .meta exists to record the issue. This path is for hotfixes or
            docs-only work that will not use work-end. If work-end is needed
            later, create .meta manually first.
      n → Branch Switch Helper to main, re-run detection.
```

---

## New Branch Path

### Step 0 — Resolve paths

Read `$PROJECT` and `$WORKSPACE` from CLAUDE.md (see Path Resolution above).

### Step 1 — Work description

Use the invocation argument if provided. Otherwise prompt:
> "Describe the work in one sentence."

### Step 2 — Platform coherence

Locate the platform doc:

```bash
ls "$PROJECT/docs/PLATFORM.md" 2>/dev/null || ls ~/claude/casehub/parent/docs/PLATFORM.md 2>/dev/null
```

Read it. Run the five coherence questions against the work description:

1. **Does this already exist?** Is this capability already implemented somewhere?
2. **Is this the right repo?** Would this work more naturally live elsewhere?
3. **Does this create a consolidation opportunity?** Should existing similar code be unified?
4. **Is it consistent with platform patterns?** Module tier structure, naming conventions, architectural rules?
5. **Does it need a platform-level doc update?** Will PLATFORM.md or docs/repos/ need updating?

Surface any concerns to the user before proceeding.

### Step 3 — Relevant protocols

```bash
ls "$PROJECT/docs/protocols/" 2>/dev/null || ls ~/claude/casehub/parent/docs/protocols/ 2>/dev/null
```

Read any protocols applicable to the described work. Surface violations before proceeding.

Common signals:
- Maven coordinate changes → `maven-coordinate-standard.md`, `artifact-rename-propagation.md`
- Flyway migrations → `flyway-migration-rules.md`, `flyway-version-range-allocation.md`
- SPI changes → `ledger-spi-propagation.md`, `spi-blocking-reactive-parity.md`
- Module structure → `module-tier-structure.md`, `maven-submodule-folder-naming.md`

### Step 3b — Garden search

Search the garden for GEs relevant to the domain being worked. This step surfaces existing knowledge before implementation begins — relevant gotchas, techniques, and undocumented behaviours often already exist for the domain.

Extract 2–4 keywords from the work description (domain name, library, framework, or key concept). Then:

```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} grep -i "<keyword1>\|<keyword2>" HEAD -- '*.md' \
  ':!GARDEN.md' ':!CHECKED.md' ':!DISCARDED.md' \
  | grep -i "^[^:]*:" | head -20
```

If matches found: surface the GE filenames and titles to the user. Ask which are relevant before proceeding. Do not read them unless the user confirms interest.

If no matches: proceed silently.

**Skip** if the garden path does not exist (`${HORTORA_GARDEN:-~/.hortora/garden}` is absent) or the work description has no searchable domain keywords (e.g., a pure docs or tooling task).

### Step 4 — Issue

If tracking disabled: skip silently. Set `ISSUE_N`, `ISSUE_TITLE`, `ISSUE_REPO_GITHUB` to blank. Proceed to Step 5.

If tracking enabled (CLAUDE.md `## Work Tracking` with `Issue tracking: enabled`):

Read the project's GitHub repo:
```bash
PROJECT_GITHUB_REPO=$(grep "GitHub repo:" "$PROJECT/CLAUDE.md" | head -1 | sed 's/.*GitHub repo: *//')
```

**Cross-repo detection (work-start owns this — workspace concern):**

If the work description or invocation argument contains a ref of the form `<repo-name>#N`
(e.g., `cc-praxis#94`) where `<repo-name>` does not match the project repo name:
- Extract `ISSUE_N = N`, `ISSUE_REPO_NAME = <repo-name>`
- Resolve: `ISSUE_REPO_GITHUB = "<org>/$ISSUE_REPO_NAME"` using the org from `$PROJECT_GITHUB_REPO`
- Confirm with the user: "Tracking cross-repo issue $ISSUE_REPO_GITHUB#$ISSUE_N — correct? (y/n)"
- Record `ISSUE_N`, `ISSUE_TITLE`, `ISSUE_REPO_GITHUB` and proceed to Step 5.

**Same-repo issue resolution — delegate to issue-workflow Phase 2:**

Do not search for or create issues here. Instead invoke `issue-workflow` Phase 2
(Task Intake), passing the work description as context. issue-workflow Phase 2 owns:
- Finding an existing open issue that covers this work
- Drafting and creating a new issue if none exists
- Cross-cutting detection across concerns
- Epic placement for ad-hoc issues

When Phase 2 completes, it returns the resolved `ISSUE_N` and `ISSUE_TITLE`.
Record these plus `ISSUE_REPO_GITHUB = $PROJECT_GITHUB_REPO` for Steps 5, 8, and 9.

Do not proceed without a resolved issue number (or explicit user skip from Phase 2).

> **Why delegation:** issue-workflow is the single owner of GitHub issue lifecycle.
> work-start owns branch + workspace lifecycle. Cross-repo detection stays here
> because it is a workspace routing concern, not an issue management concern.

### Step 5 — Branch name

Derive: `issue-NNN-<slug>` (title lowercased, special chars stripped, max 30 chars after prefix).

Show to user, allow override. Guards:
- Reject `main`, `$PROJECT_BASE_BRANCH`, `HEAD`, or any existing branch name in either repo.
- The issue number (NNN) is the stable key — the slug is a convenience only.

### Step 6 — Flyway V scan

```bash
git -C "$PROJECT" fetch --all 2>/dev/null || echo "⚠️ No network — scan incomplete"
```

If network available: scan `$PROJECT_BASE_BRANCH` + all remote branches for claimed V numbers. Compute
`next-safe-v = max + 1`. If conflict found: warn, show offending branches, block until acknowledged.

Only ask about Flyway if the user described migration work:
> "Will this branch include database migrations? (y/n)"
> - y → `FLYWAY_NEXT_V=<next-safe-v>`
> - explicit n → `FLYWAY_NEXT_V=none`
> - no answer (default) → `FLYWAY_NEXT_V=unknown`
### Step 7 — Create branches (atomic)

```bash
git -C "$PROJECT" checkout -b <branch-name>
# If fails → abort (nothing to clean up)
git -C "$WORKSPACE" checkout -b <branch-name>
# If fails → git -C "$PROJECT" branch -D <branch-name>, abort, report error
```

Confirm both commands succeeded before continuing.

### Step 8 — Resolve design routing and SHA baseline

**Layer 0 (cross-repo issue override — checked first):**

If `ISSUE_REPO_GITHUB` is non-blank and differs from `PROJECT_GITHUB_REPO`:
```bash
ISSUE_REPO_NAME=$(echo "$ISSUE_REPO_GITHUB" | sed 's|.*/||')
CANDIDATE="$(dirname "$PROJECT")/$ISSUE_REPO_NAME"
```
- If `$CANDIDATE/.git` exists:
  - `DESIGN_REPO="$CANDIDATE"`, `DESIGN_REPO_KEY="cross-repo:$ISSUE_REPO_NAME"`
  - Skip Layers 1–2 entirely.
- If not found: warn — *"Cross-repo issue ($ISSUE_REPO_GITHUB) — local path not found at
  $CANDIDATE. Falling through to routing config. Journal will target routing-config destination."*
  Continue to Layers 1–2.

Read routing config (3-layer cascade) for `design` artifact (only if Layer 0 did not match):

**Layer 1 (global default — `~/.claude/CLAUDE.md`):**
```bash
grep -A 5 "^## Routing$" "$HOME/.claude/CLAUDE.md" 2>/dev/null \
  | grep "^\*\*Default destination:\*\*" | sed 's/\*\*Default destination:\*\* *//'
```
Valid values: `workspace` or `project`. Anything else: warn, treat as absent.

**Layer 2 (workspace per-artifact — `$WORKSPACE/CLAUDE.md`):**
```bash
grep -A 30 "^## Routing$" "$WORKSPACE/CLAUDE.md" 2>/dev/null
```
Parse the markdown table for a `design` row. Valid values: `workspace`, `project`.

Layer 2 overrides Layer 1. If neither present: default is `project`.

Apply resolved routing:
- If `design → workspace`: `DESIGN_REPO="$WORKSPACE"`, baseline = `git -C "$WORKSPACE" rev-parse main`, `DESIGN_REPO_KEY=workspace`
- If `design → project` (default): `DESIGN_REPO="$PROJECT"`, baseline = `git -C "$PROJECT" rev-parse HEAD`, `DESIGN_REPO_KEY=project`

`DESIGN_REPO_KEY` is stored in `.meta` so work-end can recover it without re-deriving
from routing config — which may have changed between sessions.

Compute section hashes (single pipe-separated line):
```bash
HASHES=$(grep "^## " "$DESIGN_REPO/DESIGN.md" 2>/dev/null \
  | while read h; do printf "%s:%s|" "$(printf '%s' "$h" | shasum -a 256 | cut -c1-8)" "$h"; done)
```
Leave blank if `$DESIGN_REPO/DESIGN.md` does not exist yet.

### Step 9 — Scaffold

```bash
mkdir -p "$WORKSPACE/design"
```

Write `$WORKSPACE/design/JOURNAL.md`:
```markdown
# Design Journal — <branch-name>
```

Write `$WORKSPACE/design/.meta`:
```
branch: <branch-name>
project-sha: <baseline SHA from Step 8>
date: <YYYY-MM-DD>
issue: <N or blank>
issue-repo: <ISSUE_REPO_GITHUB | blank>
flyway-next-v: <N | none | unknown>
design-repo: <workspace | project | cross-repo:<repo-name>>
design-section-hashes: <pipe-separated hash:heading pairs, or blank>
```

### Step 10 — Commit and push scaffold

```bash
git -C "$WORKSPACE" add design/JOURNAL.md design/.meta
git -C "$WORKSPACE" commit -m "init(<branch-name>): scaffold workspace branch"
git -C "$WORKSPACE" push  # non-fatal if fails; warn and continue
```

### Step 11 — IntelliJ MCPs

Call `mcp__intellij-index__ide_index_status` and `mcp__intellij__get_project_modules`.

**If either is unavailable:**
- Stop immediately — tell the user which MCP is missing
- Do not proceed with any semantic operation
- Do not fall back to bash, grep, or sed as substitutes
- Wait for the user to reconnect via `/mcp`

IntelliJ can also drop mid-task. If a semantic operation fails because an MCP
is unavailable at any point, stop and tell the user rather than silently falling back.

### Step 12 — Offer brainstorming

> "Start a brainstorm? (y/n)"

If yes: invoke `superpowers:brainstorming`. Specs write to `$WORKSPACE/specs/<branch-name>/`.
Specs always route to `project` (`$PROJECT/docs/specs/`) at close — the three-layer
cascade covers blog/adr/snapshots/plans/design only.

---

## Resume Path (Detection state 2)

Surface `.meta`:
```
⚡ Resuming: <branch-name>  Issue: #<N>  Started: <date>
   Flyway V: <N | none | unknown>
   Project: <branch>  Workspace: <branch>
```

Run Steps 0, 2, 3, 3b, 11 only. Skip all branch creation steps.

---

## Done — Report

```
work-start complete.
Branch: <branch-name>  Issue: #<N>
Platform doc: [read / not found]
Coherence Protocol: [any concerns raised, or "clear"]
Protocols checked: [list any relevant ones read]
Garden search: [N GEs surfaced for <domain> / no matches / skipped]
IntelliJ: ✅ both connected / ⚠️ [missing — stopped]

Proceeding to brainstorming.  (or: Ready for work.)
```
