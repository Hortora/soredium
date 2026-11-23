## D1: Scope — explicit family roots only

**Choice:** Only survey family roots passed as arguments; no auto-discovery.
**Alternatives:**
- Auto-discover + explicit — scans ~/claude/*/ by default; couples tool to directory layout
- Single family only — no multi-family in one invocation; too restrictive
**Rationale:** The filesystem layout is a convention, not a contract. Explicit args keep the tool portable and predictable.
**Trade-offs:** User must know their family roots. Mitigated by discoverability in other tools.
**Sources:** Issue #589 description (`[family-root ...]` syntax)
**Exploration:** quick
**Status:** captured

## D2: Output format — dual internal + CLI

**Choice:** Python dataclasses internally; KEY=VALUE as script; JSON Lines events via commands/survey.py for TUI.
**Alternatives:**
- JSON Lines only — simpler but breaks KEY=VALUE convention for pipeline scripts
- KEY=VALUE only — no TUI integration; defers the work
**Rationale:** Matches the established pattern (ctx.py returns dict, prints KEY=VALUE; commands/status.py wraps into StatusReady events).
**Trade-offs:** Two output paths to maintain. Mitigated by the dataclass being the single source.
**Sources:** commands/events.py (RepoSlotInfo, StatusReady patterns), project/ctx.py
**Exploration:** quick
**Status:** captured

## D3: Blog drift detection — included in initial survey

**Choice:** Include blog/artifact drift detection from the start, following the rules in the issue comment.
**Alternatives:**
- Defer to follow-up — ship structural survey first, add drift later
- Stub only — wire routing but don't compare ls-tree yet
**Rationale:** The hand-survey found false positives precisely because it didn't follow the base-ref comparison rules. Getting drift right is the stated purpose.
**Trade-offs:** Adds complexity (routing resolution, cross-repo ls-tree). Justified by the false-positive history.
**Sources:** Issue #589 comment (drift rules 1-6), publish-blog/blog_routing.py (plan function)
**Exploration:** quick
**Status:** captured

## D4: Severity model — reuse verification.Finding

**Choice:** Use the existing verification.Finding NamedTuple (severity: error/warning/info, category, message).
**Alternatives:**
- Custom severity levels — survey-specific (action-needed, drift, stale); more descriptive but adds vocabulary
- No severity — flat list; simpler but harder to triage
**Rationale:** One severity vocabulary across the codebase. Survey attention items are findings.
**Trade-offs:** Finding's three-level severity may be coarser than ideal. Sufficient for triage.
**Sources:** verification/__init__.py, verification/repo_checks.py
**Exploration:** quick
**Status:** captured

## D5: Discovery mechanism — filesystem walk

**Choice:** Walk the directory tree to discover areas. Canonical repos = top-level dirs with .git (not under slots/clone/attic/). Slots = slots/N/. Clones = clone/repo/. Attic = slots/attic/N/.
**Alternatives:**
- DB-first with filesystem fallback — queries worklog DB, verifies on disk; misses unregistered areas
- Both and compare — most thorough but doubles work
**Rationale:** The filesystem IS truth. The DB can be stale (reconcile_slots.py exists for this reason). The survey should report what exists, not what the DB says.
**Trade-offs:** Slower than a DB query for large families. Acceptable for a survey tool.
**Sources:** project/topology.py (_detect_* functions), scripts/reconcile_slots.py
**Exploration:** quick
**Status:** captured

## D6: Architecture — three-layer (discover, inspect, report)

**Choice:** Three distinct layers: discover_areas() -> inspect_area() -> SurveyResult with attention findings.
**Alternatives:**
- Flat single-pass — one loop walks and inspects; simpler but tangled
- Strategy per type — per-type strategy classes; over-engineered for 3-4 types
**Rationale:** Each layer independently testable. Discovery is purely filesystem. Inspection reuses existing functions. Read-only property is structural.
**Trade-offs:** More code than flat single-pass. Justified by testability.
**Sources:** project/canonical_sync.py, project/queue_home.py, verification/ library
**Exploration:** quick
**Status:** captured

## D7: Area kinds — five types

**Choice:** canonical, slot, clone, attic, standalone-workspace.
**Alternatives:**
- Add agent sessions — broader scope, may be out of scope for lifecycle
- Fewer (merge attic into slot) — attic is just archived state; loses visibility into the distinction
**Rationale:** These five cover everything the lifecycle touches. Each has distinct markers and inspection concerns.
**Trade-offs:** standalone-workspace may be rare. Including it prevents silent omissions.
**Sources:** project/topology.py, project/clone_manager.py, project/slot_io.py
**Exploration:** quick
**Status:** captured

## D8: Closure refs awareness — read when present, fall back to stamp parsing

**Choice:** The survey reads `refs/soredium/closed/` and `refs/soredium/closed-meta/<branch>` from workspace repos when present. For branches without closure refs (pre-#618), fall back to parsing stamp commit messages (`chore: branch closed — landed as <SHA>`).
**Alternatives:**
- Require closure refs — would miss all existing closed branches
- Ignore closure refs entirely — misses the opportunity to consume structured data when available
**Rationale:** #618 will add closure refs to the close ceremony, but the survey ships first. Dual-path reading ensures it works now and improves automatically when #618 lands.
**Trade-offs:** Two code paths for reading closure status. The stamp-parsing path becomes dead code once all branches have refs, but that's a long tail.
**Depends on:** D5 (filesystem walk discovers areas), D6 (inspect layer reads refs)
**Sources:** Hortora/soredium#618, work-end/close.py (stamp logic), project/branch_base.py (refs/soredium/base/ pattern)
**Exploration:** quick
**Status:** captured

## D9: Work-end preview — in scope

**Choice:** Include a `WorkEndPreview` section in each AreaReport showing what `work end` would attempt: branches that would land, artifacts needing promotion, gates that would refuse.
**Alternatives:**
- Defer to follow-up — ship without predictive reporting
**Rationale:** The issue title explicitly asks for "what work end would do there." The data is derivable from already-collected inspection data (queue done items, branch state, ref state) with no additional git operations.
**Trade-offs:** Adds complexity to the report. The preview is advisory — gate predictions may differ from actual ceremony results if state changes between survey and execution.
**Sources:** Issue #589 title, work-end/scope.py, work-end/close.py
**Exploration:** quick
**Status:** captured

## D10: Blog unpublished detection — full implementation from refs

**Choice:** Fully implement rule 3 (unpublished = absent from every routing destination). Read frontmatter from git refs via `git show`, resolve routing from blog-routing.yaml, check destination repos via `git ls-tree`.
**Alternatives:**
- Defer rule 3 — ship rules 1-2 only
- Stub — wire routing but report "not yet implemented"
**Rationale:** The false-positive history (32/33 false gaps) is precisely about incorrect entry enumeration. Doing this right from refs, not disk, is the whole point.
**Trade-offs:** More complex than promotion gap detection alone. Requires frontmatter parsing from git objects, destination-to-repo resolution, and cross-repo ls-tree.
**Depends on:** D3 (blog drift included)
**Sources:** Issue #589 comment rules 1-6, publish-blog/blog_routing.py
**Exploration:** quick
**Status:** captured

## D11: Three canonical_sync functions are unsafe — all inlined

**Choice:** `follow()`, `ahead_of_canonical()`, and `reference()` all fetch for clone repos. None are called. Survey inlines read-only replacements for follow and ahead; reference is not needed.
**Alternatives:**
- Call them and accept the mutation — violates a-read-never-writes
- Promote read-only variants to canonical_sync — out of scope for this issue
**Rationale:** Design review (R1-01, R1-03) confirmed all three mutate. The read-only inlines use rev-parse, merge-base, and rev-list which work via alternates in --shared clones.
**Trade-offs:** Duplicates logic that could be in canonical_sync. Acceptable — adding read-only variants to canonical_sync is a separate concern.
**Sources:** canonical_sync.py lines 362, 504, 522 (fetch calls)
**Exploration:** quick
**Status:** captured
