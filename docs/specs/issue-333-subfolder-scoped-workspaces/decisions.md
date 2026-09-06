## D1: Normalized pipeline (no subfolder mode)

**Choice:** No "subfolder mode" switch. Topology always resolves both `project` (scope) and `git_root`. The pipeline processes both paths uniformly — when they're equal (single-repo), the merge is a no-op.
**Alternatives:**
- Add `IN_SUBFOLDER` flag and conditional paths — consumers branch on mode
- Keep `PROJECT` as git root, add `PROJECT_SCOPE` for subfolder-aware consumers only
**Rationale:** Normalizing at the boundary (topology.py) and running one pipeline eliminates scattered conditionals. No consumer needs to know whether it's a subfolder or not — it uses `PROJECT` for project things and `GIT_ROOT` for git things.
**Trade-offs:** Every consumer must use the correct field (`PROJECT` vs `GIT_ROOT`). Consumers that run `git add .`, `git diff -- .`, or `git status .` via `git -C $PROJECT` will scope-limit results to the app folder — this is a correctness bug, not cosmetic. Migration to `$GIT_ROOT` for staging/diff/status consumers is mandatory, not gradual. Branch/checkout/log commands (without `-- .`) are safe from subdirectories.
**Sources:** Brainstorming conversation, existing topology.py (flat dataclass pattern from D3 of issue-220)
**Exploration:** deep-analysis
**Status:** captured

## D2: Topology.project = scope, new Topology.git_root

**Choice:** `Topology.project` means "the project scope" (what `proj/` points to, or CWD). New `Topology.git_root` holds the git repository root. For single-repo: `project == git_root`.
**Alternatives:**
- Keep `project` as git root, add `scope` as new field — backward compat but misleading name
- Rename to `project_dir` and `git_root` — clean but breaks all consumers by name change
**Rationale:** "Project" should mean "what you're working on." The git root is infrastructure. Preserving the name with refined semantics avoids a mass rename. Single-repo behavior is unchanged because the values are equal.
**Trade-offs:** Semantic change to `project` — but only visible in subfolder mode, which is new.
**Depends on:** D1 (normalized pipeline)
**Sources:** topology.py line 142, _resolve_symlink_target (already preserves subfolder targets)
**Exploration:** deep-analysis
**Status:** captured

## D3: Symlink search starts at CWD, not git root

**Choice:** topology.py checks for `wksp/` and `proj/` at CWD first, then falls back to git root, then main worktree. Priority chain, not a conditional.
**Alternatives:**
- Only check git root (existing behavior) — breaks subfolder mode
- Check both without priority — ambiguous when root and subfolder both have symlinks
**Rationale:** CWD is where the user is. If they're in an app folder with `wksp/`, that's their project context. Walk-up from CWD toward git root (not just CWD itself) handles cases where the user is nested deeper than the app root (e.g., `apps/foo/src/main/java/`).
**Trade-offs:** Walk-up loop is slightly more complex than a single check. Bounded by directory depth to git root — typically 2-4 iterations.
**Depends on:** D2 (project = scope)
**Sources:** topology.py lines 114-121 (current git-root-only search), GE-20260529-182916 (CWD subdirectory bug)
**Exploration:** deep-analysis
**Status:** captured

## D4: CLAUDE.md merge — scope wins, root fills gaps

**Choice:** ctx.py always reads two CLAUDE.md files: `topo.project / "CLAUDE.md"` and `topo.git_root / "CLAUDE.md"`. Scope wins. Root fills gaps. For single-repo: same file, merge is a no-op.
**Alternatives:**
- Read scope only, explicit fallback table per field — more code, conditionals
- Read root only, ignore app-level CLAUDE.md — loses app-specific config
**Rationale:** Universal merge eliminates per-field conditionals. The `or` fallback pattern is the same for all fields. No field-specific routing needed.
**Trade-offs:** Reads the same file twice for single-repo. Negligible cost.
**Depends on:** D2 (project = scope)
**Sources:** ctx.py lines 98-101 (current single-read), user requirement for app-level type/build overrides
**Exploration:** quick
**Status:** captured

## D5: CWD-based subfolder detection in workspace-init

**Choice:** workspace-init detects subfolder mode by comparing CWD with `git rev-parse --show-toplevel`. If CWD is inside a git repo but not the root, offer subfolder-scoped workspace.
**Alternatives:**
- Explicit flag (--scope=apps/foo) — requires user to know the flag
- CLAUDE.md declaration (scope: subfolder) — requires pre-existing config
**Rationale:** CWD detection is zero-friction. The user is already in the directory they want to scope to. After setup, symlinks encode the decision — the pipeline is uniform.
**Trade-offs:** Only detects when user is physically in the subfolder. By design — the user chooses scope by where they open Claude.
**Sources:** User preference for CWD-based detection
**Exploration:** quick
**Status:** captured

## D6: One workspace per app, independent

**Choice:** Each app folder gets its own workspace directory: `~/claude/public/<repo>-<app>/`. Completely independent — same model as separate repos.
**Alternatives:**
- Shared workspace with app subdirectories — couples lifecycle
- Nested workspace repos under a parent — new directory convention
**Rationale:** Matches the existing single-repo workspace model. No new conventions. Each session is independent.
**Trade-offs:** More workspace directories. Acceptable — workspaces are lightweight.
**Sources:** User preference for independent workspaces
**Exploration:** quick
**Status:** captured

## D7: Standard branching, no app prefix

**Choice:** Standard `issue-NNN-slug` branches. No app prefix needed.
**Alternatives:**
- App-prefixed branches (app-foo/issue-42-feature) — aids disambiguation
- Worktrees per app — git isolation for concurrent branches
**Rationale:** One session per app, one branch at a time per repo. The session context knows the scope. Branch names don't need to encode it.
**Trade-offs:** Can't work on two app branches simultaneously in the same repo. Acceptable for the one-session-per-app model.
**Sources:** User preference
**Exploration:** quick
**Status:** captured

## D8: Session entry from app folder

**Choice:** User runs `claude` from the app folder (e.g., `quarkmind/apps/foo/`). Claude Code loads both app and root CLAUDE.md naturally via parent-directory loading.
**Alternatives:**
- Open from workspace with add-dir to app — workspace-first entry
- Support both — more complexity
**Rationale:** App-first is natural. Claude Code's CLAUDE.md loading handles the layering automatically. No custom mechanism needed.
**Trade-offs:** User must cd to the app folder. Natural workflow.
**Sources:** User preference
**Exploration:** quick
**Status:** captured
