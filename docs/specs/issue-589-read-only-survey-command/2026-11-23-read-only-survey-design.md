# Read-only Survey Command — Design Spec

**Issue:** Hortora/soredium#589
**Branch:** issue-589-read-only-survey-command
**Date:** 2026-11-23

## Purpose

A read-only command that surveys every area in a family root — canonical
repos, slots, clones, attic — and reports their state: branches, dirty
counts, remotes, ahead-of-canonical, queue status, legacy layout, blog
drift, closure status, and what `work end` would do if run there. One
row per area, attention items summarised at the end. Output is KEY=VALUE
for pipeline scripts and JSON Lines events for the TUI.

The hand-survey that motivated this found a diverged clone, queues
naming branches not checked out, a stale `.close-state`, and five
differing queues in one slot. It also found 33 blog promotion gaps of
which 32 were false positives — the files were on feature branches, not
the base branch. This command replaces that manual process with
repeatable, correct drift detection.

## Scope

- `project/areas.py` — discovery, inspection, reporting (new file)
- `commands/survey.py` — CLI/TUI event wrapper (new file)
- `commands/events.py` — `SurveyReady` event type (extend)
- `tests/test_areas.py` — comprehensive tests including read-only proof (new file)
- Promote `canonical_sync._in_progress()` and `._worktrees()` to public API

Out of scope: writing closure refs (#618), modifying the close ceremony,
TUI view implementation.

## Architecture

Three layers, each independently testable:

```
discover_areas(family_root)  →  list[Area]
inspect_area(area, family)   →  AreaReport
survey(family_roots)         →  list[SurveyResult]
```

### Layer 1: Discovery

`discover_areas(family_root: Path) -> list[Area]`

Walks the filesystem to find every area. No git operations, no file
reads beyond `Path.exists()` / `Path.iterdir()` / `Path.is_dir()`.

**Area kinds:**

| Kind | Location | Marker |
|------|----------|--------|
| `canonical` | Top-level children of family root with `.git` and no `.workspace` marker, not under `slots/`/`clone/`/`attic/` | `.git` directory |
| `workspace` | Top-level children with `.git` and `.workspace` marker (or `wksp-` prefix, or contains `wksp` symlink) | `.workspace` or naming convention |
| `slot` | `slots/<N>/` | `.slot` file |
| `clone` | `clone/<repo>/` | `.permanent` file |
| `attic` | `slots/attic/<N>/` | `.slot` file |

Workspaces are not independent areas — they are paired with their
project. Discovery returns them as part of the `canonical` area via
a `workspace` field on `Area` (see Data Model).

**Repo enumeration within areas:**

Each area contains one or more git repos. Discovery identifies them:

| Area kind | Project repo(s) | Workspace repo |
|-----------|-----------------|----------------|
| `canonical` | The area directory itself | Resolved via `wksp` symlink or `wsp-<name>` naming convention in family root |
| `slot` | Subdirectories listed in `.slot` repos field (excluding `.workspace` entries) | Subdirectory with `.workspace` marker |
| `clone` | The `<repo>/` subdirectory | The workspace clone subdirectory |
| `attic` | Same as slot | Same as slot |

`repos_in_area(area: Area) -> list[RepoInfo]` returns all repos with
their role (`project` or `workspace`).

**Cross-area pairing for canonical repos:**

Canonical workspaces (e.g. `wsp-soredium`) must be paired with their
project (`soredium`) for drift detection. Pairing is resolved by:
1. The `proj` symlink in the workspace (points to the project)
2. Failing that, naming convention: `wsp-<name>` pairs with `<name>`
3. Failing both, the workspace is reported without drift comparison

**Ordering:** canonical first (alphabetical), then slots (by number),
then clones (alphabetical), then attic (by number).

### Layer 2: Inspection

`inspect_area(area: Area, family_root: Path) -> AreaReport`

For each discovered area, collects state using existing building blocks.
All git operations via `git_util.git()`. All reads via existing library
functions.

**Per-repo state** (every git repo in the area):

| Field | Source |
|-------|--------|
| Current branch | `git rev-parse --abbrev-ref HEAD` |
| Dirty file count | `git status --porcelain` line count |
| Remotes | `git remote` |
| Ahead-of-canonical | Inline `ahead_readonly()` (see below) |
| Follow state | Inline `follow_state_readonly()` (see below) |
| In-progress operation | `canonical_sync.in_progress()` (promoted to public) |
| Worktrees | `canonical_sync.worktrees()` (promoted to public) |

**Read-only inlines (functions that must NOT use their canonical_sync equivalents):**

Three `canonical_sync` functions mutate and cannot be called by the survey:

| Function | Mutation | Survey replacement |
|----------|----------|--------------------|
| `follow()` | `git fetch` + `git merge --ff-only` | `follow_state_readonly()` |
| `ahead_of_canonical()` | calls `_onto()` which does `git fetch` for clones | `ahead_readonly()` |
| `reference()` | `git fetch` for non-same-store repos | Not used — survey reads canonical directly |

```python
def follow_state_readonly(clone_repo: Path, canon_repo: Path, base: str) -> str:
    """Compare base branch SHAs without fetching or merging."""
    clone_sha = git(clone_repo, "rev-parse", f"refs/heads/{base}").stdout.strip()
    canon_sha = git(canon_repo, "rev-parse", f"refs/heads/{base}").stdout.strip()
    if not clone_sha or not canon_sha:
        return "unknown"  # base branch missing in one or both repos
    if clone_sha == canon_sha:
        return "current"
    merge_base = git(clone_repo, "merge-base", clone_sha, canon_sha).stdout.strip()
    if not merge_base:
        return "diverged"  # no common ancestor
    if merge_base == clone_sha:
        return "fast-forward"   # clone is behind canonical
    if merge_base == canon_sha:
        return "ahead"          # clone has commits canonical lacks
    return "diverged"           # both have unique commits

def ahead_readonly(repo: Path, canon_repo: Path, base: str, branch: str) -> int:
    """Count commits on branch that canonical's base branch lacks, without fetching."""
    canon_sha = git(canon_repo, "rev-parse", f"refs/heads/{base}").stdout.strip()
    if not canon_sha:
        return 0
    result = git(repo, "rev-list", "--count", f"{canon_sha}..refs/heads/{branch}")
    count = result.stdout.strip()
    return int(count) if count.isdigit() else 0
```

Both work because clone repos use `--shared` / alternates and can see
canonical's objects. The survey documents this assumption and the
read-only test verifies it empirically.

**Queue state** (via `queue_home.candidates()`):

| Field | Source |
|-------|--------|
| Queue paths | `queue_home.candidates()` |
| Items / open items | Each candidate's `items` / `open_items` |
| Active issue | Each candidate's `active` |
| Queue status | Each candidate's `status` |
| Root queue marker | `queue_home.uses_root()` |

**Markers** (via `Path.exists()`):

`.slot`, `.permanent`, `.queue-root`, `.clone-enabled`, `.landed`,
`.close-state`, `.workspace`, `blog-routing.yaml`

**Slot metadata** (slot/attic only):

`slot_io.parse_slot()` — repos, primary, branch, title, state, slot number.

**Blog/artifact drift** (areas with `blog-routing.yaml`):

**IMPORTANT:** `blog_routing.plan()` reads the working tree (`.glob()`,
`.read_bytes()`), which produces false positives when the checkout is on
a feature branch older than a promotion. The survey enumerates entries
from `git ls-tree` on base refs, not from disk.

**Entry enumeration from refs:**

```python
def entries_on_ref(repo: Path, ref: str, blog_dir: str = "docs/blog") -> set[str]:
    """List blog entries present on a git ref (branch or commit)."""
    result = git(repo, "ls-tree", "-r", "--name-only", ref, "--", blog_dir)
    return {line for line in result.stdout.strip().splitlines() if line}

def entry_content_from_ref(repo: Path, ref: str, path: str) -> str:
    """Read file content from a git ref without touching the working tree."""
    result = git(repo, "show", f"{ref}:{path}")
    return result.stdout
```

**Routing resolution from refs (not disk):**

For unpublished detection, the survey needs each entry's routing
destinations. Since `blog_routing.plan()` reads from disk, the survey
reads frontmatter from refs and resolves routing directly:

1. Enumerate entries on workspace base branch via `entries_on_ref()`
2. For each entry, read content via `entry_content_from_ref()`
3. Parse frontmatter (YAML between `---` markers)
4. Resolve destinations using the routing config's category/project
   mapping (read `blog-routing.yaml` via `Path.read_text()`)
5. Check presence at each destination repo's base branch via
   `entries_on_ref(dest_repo, dest_base, dest_dir)`

**Destination-to-repo mapping:**

The routing config's destinations are filesystem paths (e.g.
`~/.hortora/blog/_posts/`). The survey resolves each to a git repo:
1. Walk up from the destination path to find the nearest `.git` parent
2. Determine its base branch (`git rev-parse --abbrev-ref HEAD` or
   configured default)
3. Cache the mapping per survey run

Rules from #589 comment:

1. **Promotion gap** = entry present on workspace **base branch** (`git
   ls-tree -r <base> -- docs/blog/`) AND absent from project **base
   branch** (`git ls-tree -r <base> -- docs/blog/`). Never compare files
   on disk — always base refs.
2. **Waiting for landing** = entry only on a workspace working branch
   (present on HEAD but not on base). Reported separately, not a gap.
3. **Unpublished** = absent from every destination the routing plan names.
   Entry list from `entries_on_ref()` on workspace base branch.
   Frontmatter from `entry_content_from_ref()`. Destinations from
   routing config. Presence checked via `entries_on_ref()` on each
   destination repo's base branch.
4. **Idempotent** = consecutive runs with no changes between produce
   identical numbers. Tested.
5. **Entries with bare `projects:` values** (not `owner/repo` format) are
   flagged with their paths. Detected during frontmatter parsing: if
   `projects:` value doesn't contain `/`, it's a bare name.

**Closure status** (D8 — dual-path):

For each branch in the workspace repo:
- If `refs/soredium/closed/<branch>` exists: read the ref and
  `refs/soredium/closed-meta/<branch>` blob for structured status
  (landed SHA, promoted files, published destinations, timestamp).
- If no closure ref: check for a stamp commit (`chore: branch closed`)
  on the branch tip; parse the landing SHA from the message.
- Classify: stamped-and-landed, stamped-but-not-verified, unstamped,
  no-closure-record.

Until #618 ships, `promoted` and `published` fields in `ClosureRecord`
are always empty lists (stamp messages don't carry this data). The
closure section's value pre-#618 is: identifying unstamped branches,
verifying landing SHAs, and distinguishing active from orphaned branches.

**Unstamped branch classification** (issue comment rule 4):

Unstamped branches are split by area status:

| Area state | Branch classification | Finding severity |
|------------|----------------------|------------------|
| Active slot/clone with open queue items | `active` — expected, work in progress | None (normal) |
| Archived attic slot | `orphaned` — should have been stamped | WARN |
| Landed slot (`.landed` marker, no archive) | `landed-not-stamped` — the real problem | WARN |
| Canonical with no open queue items | `stale` — leftover from completed work | INFO |

Each orphaned/landed-not-stamped branch is named individually in the
findings, not counted.

### Layer 2.5: Work-End Preview

`work_end_preview(area: Area, repos: list[RepoInfo], queues: list[QueueInfo]) -> WorkEndPreview`

For each area, predict what `work end` would do if run there. This is
purely derived from already-collected inspection data — no additional
git operations.

| Prediction | Source |
|------------|--------|
| Branches that would land | Queue items marked done (done but not closed) |
| Artifacts needing promotion | Entries on workspace working branch not on base |
| Blog entries to publish | Promotion gaps (workspace base → project base) |
| Gates that would refuse | Squash review needed (no `refs/squash-reviewed/<branch>`), promotion check failures |
| Close ceremony would skip | No done items, area already on main |

The preview is advisory — it shows what the ceremony would *attempt*,
not what would succeed. Gate refusals are predictions based on current
ref state.

### Layer 3: Reporting

`survey(family_roots: list[Path]) -> list[SurveyResult]`

Orchestrates discovery and inspection for each family root. Rolls up
per-area findings into a summary attention list.

**Error handling:**

Each area is inspected independently. A failure in one area (corrupted
repo, malformed `.slot`, git timeout) produces a finding with severity
ERROR and category `inspection-failed`, and the survey continues to the
next area. The `AreaReport` for a failed area has `error` set with the
exception message; all other fields are empty/default.

`git_util.git()` has a 30-second default timeout and never raises — it
returns a `CompletedProcess` with non-zero returncode. The survey checks
returncode before using stdout.

**Finding generation:**

| Condition | Severity | Category |
|-----------|----------|----------|
| Area inspection failed | ERROR | `inspection-failed` |
| Clone diverged from canonical | ERROR | `drift` |
| Rebase/merge/cherry-pick in progress | ERROR | `stuck-operation` |
| Queue names a branch not checked out | WARN | `queue-mismatch` |
| Multiple queues, no `.queue-root` | WARN | `queue-ambiguity` |
| Stale `.close-state` file | WARN | `stale-state` |
| Dirty working tree on base branch | WARN | `dirty-base` |
| Blog promotion gap (base ref comparison) | WARN | `promotion-gap` |
| Orphaned unstamped branch (attic/landed area) | WARN | `unstamped-orphaned` |
| Entry with bare `projects:` value | WARN | `bare-project-ref` |
| Unpublished entries (routing plan) | INFO | `unpublished` |
| Ahead of canonical (normal during work) | INFO | `ahead` |
| Legacy layout detected | INFO | `legacy-layout` |
| Landed but not archived slot | INFO | `landed-not-archived` |

Findings use `verification.Finding(severity, category, message)`.

## Data Model

```python
@dataclass
class RepoInfo:
    name: str
    path: Path
    role: str             # "project" | "workspace"

@dataclass
class Area:
    kind: str             # "canonical"|"slot"|"clone"|"attic"
    path: Path
    slot_number: int | None
    repo_name: str | None
    repos: list[RepoInfo]
    project_repo: RepoInfo | None
    workspace_repo: RepoInfo | None

@dataclass
class RepoState:
    name: str
    path: Path
    role: str
    branch: str
    dirty_count: int
    remotes: list[str]
    ahead_of_canonical: int
    follow_state: str | None
    in_progress: str | None
    worktrees: list[tuple[str, str]]

@dataclass
class QueueInfo:
    path: Path
    items: int
    open_items: int
    active_issue: str | None
    status: str
    is_root: bool

@dataclass
class DriftEntry:
    file: str
    source_repo: str
    dest_repo: str
    status: str           # "gap"|"waiting"|"unpublished"
    bare_project: bool    # True if projects: value is not owner/repo

@dataclass
class ClosureRecord:
    branch: str
    source: str           # "ref"|"stamp"|"none"
    classification: str   # "active"|"orphaned"|"landed-not-stamped"|"stale"
    landed_sha: str | None
    landed_on: str | None
    promoted: list[str]   # empty until #618
    published: list[str]  # empty until #618
    closed_at: str | None

@dataclass
class WorkEndPreview:
    would_land: list[str]           # branch names
    needs_promotion: list[str]      # artifact paths
    would_publish: list[str]        # blog entry paths
    gates_refusing: list[str]       # gate names with reasons
    would_skip: bool                # nothing to do

@dataclass
class AreaReport:
    area: Area
    markers: list[str]
    repos: list[RepoState]
    queues: list[QueueInfo]
    closures: list[ClosureRecord]
    work_end_preview: WorkEndPreview | None
    legacy_layout: bool
    findings: list[Finding]
    drift: list[DriftEntry]
    slot_info: SlotInfo | None
    error: str | None             # set if inspection failed

@dataclass
class SurveyResult:
    family_root: Path
    areas: list[AreaReport]
    attention: list[Finding]
    summary: dict[str, int]
```

## Output Formats

### Script mode (KEY=VALUE)

```
FAMILY=/path/to/family
AREA_COUNT=8
CANONICAL_COUNT=2
SLOT_COUNT=4
CLONE_COUNT=1
ATTIC_COUNT=1
ATTENTION_COUNT=3
AREA_1_KIND=canonical
AREA_1_PATH=/path/to/family/soredium
AREA_1_PROJECT=soredium
AREA_1_WORKSPACE=wsp-soredium
AREA_1_BRANCH=main
AREA_1_DIRTY=0
AREA_1_AHEAD=0
AREA_1_QUEUES=1
AREA_1_QUEUE_1_STATUS=active
AREA_1_QUEUE_1_ITEMS=81
AREA_1_QUEUE_1_OPEN=30
AREA_1_WORK_END_WOULD_LAND=issue-589-survey,issue-586-budget
AREA_1_WORK_END_GATES=squash_review_needed:issue-589-survey
...
FINDING_1=ERROR:drift:clone soredium diverged from canonical
FINDING_2=WARN:queue-mismatch:slot 3 queue names issue-500 but branch is main
FINDING_3=WARN:unstamped-orphaned:attic/7 branch issue-200-old-feature has no stamp
FINDING_4=WARN:bare-project-ref:wsp-soredium/docs/blog/entry.md projects: engine (not owner/repo)
FINDING_5=INFO:landed-not-archived:slot 7 landed, ready for archive
```

### CLI/TUI mode (JSON Lines events)

New event in `commands/events.py`:

```python
@dataclass
class SurveyAreaInfo:
    kind: str
    path: str
    slot_number: int | None
    project: str | None
    workspace: str | None
    repos: list[dict]        # serialised RepoState
    queues: list[dict]        # serialised QueueInfo
    closures: list[dict]      # serialised ClosureRecord
    work_end_preview: dict | None  # serialised WorkEndPreview
    markers: list[str]
    findings: list[dict]      # serialised Finding
    drift: list[dict]         # serialised DriftEntry
    error: str | None

@dataclass
class SurveyReady:
    family_root: str
    areas: list[SurveyAreaInfo]
    attention: list[dict]
    summary: dict[str, int]
```

New command module `commands/survey.py` with
`execute(family_root: str) -> SurveyReady`.

## Read-Only Guarantee

**Structural enforcement:**
- `discover_areas`: only `Path.exists()`, `Path.iterdir()`, `Path.is_dir()`,
  `Path.is_symlink()`, `Path.resolve()`
- `inspect_area`: only `git_util.git()` with read-only git subcommands
  (`status`, `rev-parse`, `for-each-ref`, `ls-tree`, `log`, `remote`,
  `branch`, `show`, `merge-base`, `rev-list`), `Path.read_text()`, and
  existing read-only functions (`queue_home.candidates()`,
  `canonical_sync.in_progress()`, `canonical_sync.worktrees()`,
  `slot_io.parse_slot()`)
- **NOT called:** `canonical_sync.follow()`, `canonical_sync.ahead_of_canonical()`,
  `canonical_sync.reference()` — all three fetch for clone repos
- No `open(path, 'w')`, no `Path.write_text()`, no mutating git commands
- No worktrace recording — the survey observes, it does not act

**Test enforcement:**
Following `test_ctx_reads_only.py` pattern:

```python
def tree(directory: Path) -> dict[str, bytes]:
    return {str(p.relative_to(directory)): p.read_bytes()
            for p in sorted(directory.rglob("*"))
            if p.is_file() and ".git" not in p.parts}

def test_survey_read_only(tmp_path):
    family = build_family(tmp_path, ...)
    before = {str(d): tree(d) for d in family.rglob("*") if d.is_dir()}
    result = survey([family])
    after = {str(d): tree(d) for d in family.rglob("*") if d.is_dir()}
    assert before == after
    for repo in all_repos(family):
        assert git(repo, "status", "--porcelain").stdout.strip() == ""
```

**Idempotency test:**
```python
def test_survey_idempotent(tmp_path):
    family = build_family(tmp_path, ...)
    result1 = survey([family])
    result2 = survey([family])
    assert result1 == result2
```

**Feature-branch drift false-positive test** (from issue comment rule 6):
```python
def test_no_false_promotion_gap_on_feature_branch(tmp_path):
    """A project on a feature branch cut before promotion shows zero gaps."""
    family = build_family(tmp_path, ...)
    # promote entry to project main, then check out older feature branch
    promote_entry(project, "docs/blog/entry.md")
    git(project, "checkout", "-b", "feature-old", "HEAD~2")
    result = survey([family])
    assert count_findings(result, category="promotion-gap") == 0
```

## File Layout

```
project/
  areas.py           # discover_areas, inspect_area, survey (new)
commands/
  survey.py           # execute() -> SurveyReady (new)
  events.py           # SurveyAreaInfo, SurveyReady (extend)
tests/
  test_areas.py       # discovery, inspection, read-only, idempotency (new)
```

## Dependencies

Imports from existing modules (all read-only usage):

- `project.git_util` — `git()`
- `project.canonical_sync` — `locate()`, `in_progress()`, `worktrees()`
  (**NOT `follow()`, `ahead_of_canonical()`, or `reference()`** — all
  three fetch for clone repos; inlined as `follow_state_readonly()` and
  `ahead_readonly()`)
- `project.queue_home` — `candidates()`, `uses_root()`
- `project.queue_io` — `queue_dir()`, `read_queue()`
- `project.slot_io` — `parse_slot()`
- `project.clone_manager` — `is_permanent()`, `is_enabled()`
- `project.branch_base` — `parent_of()`, `base_of()`
- `verification` — `Finding` (severities: ERROR, WARN, INFO)

**Not imported** (read working tree, not refs):
- `publish-blog.blog_routing` — routing config is read directly from
  `blog-routing.yaml` via `Path.read_text()` + YAML parse; entry
  enumeration and frontmatter reading done via git refs

## Protocol Compliance

| Protocol | How complied |
|----------|--------------|
| a-read-never-writes | Structural: no write calls, no mutating imports. Test: tree snapshot before/after |
| one-queue-per-area | Uses `queue_home.candidates()`, never builds queue paths |
| git-util-single-source | All git via `git_util.git()` |
| externalised-scripts-require-tests | `test_areas.py` ships with `areas.py` |
| the-script-that-acts-records-it | N/A — the survey does not act |

## Future: #618 Closure Refs

When #618 ships, `inspect_area` will read structured closure refs from
`refs/soredium/closed/` and `refs/soredium/closed-meta/` in workspace
repos, populating `ClosureRecord.promoted` and `.published`. Until then,
these fields are empty lists — closure status provides value through
branch classification (active vs orphaned vs landed-not-stamped) and
landing SHA verification.

## References

- Hortora/soredium#589 — issue and drift rules comment
- Hortora/soredium#618 — structured closure refs (created during this brainstorm)
- `project/ctx.py` — KEY=VALUE output pattern
- `commands/events.py` — JSON Lines event pattern
- `tests/test_ctx_reads_only.py` — read-only test pattern
- `project/canonical_sync.py` — drift measurement functions (follow, ahead_of_canonical, reference all mutate for clones)
- `project/queue_home.py` — queue discovery
- `publish-blog/blog_routing.py` — routing config format (plan() reads disk, not safe for survey)
- `docs/protocols/a-read-never-writes.md` — read-only protocol
- `docs/protocols/one-queue-per-area-never-synced.md` — queue location protocol
- `docs/protocols/git-util-single-source.md` — git wrapper protocol
- `docs/protocols/externalised-scripts-require-tests.md` — test requirement
- `docs/development/lifecycle-maintainer-guide.md` — lifecycle architecture and vocabulary
