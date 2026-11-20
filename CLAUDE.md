# CLAUDE.md

**FIRST, EVERY SESSION:** if your work touches the work lifecycle (start, continue, done, wrap, end, landing, publishing, queues, slots, clones, the worklog), read [docs/development/lifecycle-maintainer-guide.md](docs/development/lifecycle-maintainer-guide.md) before changing anything, and **update that file in the same change** whenever you make any part of it untrue or learn something a future session would need (a new rule, a new failure and its lesson, a new area to watch). A change to lifecycle code without the matching guide update is not finished.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Identity

**Name:** soredium
**GitHub:** [Hortora/soredium](https://github.com/Hortora/soredium)
**Marketplace:** `/plugin marketplace add github.com/Hortora/soredium`
**Status:** Post-merge. 51 skills (workflow + garden), Python tooling, Quarkus/Java engine. Active development on main.

@SOURCES.md

## Repository Purpose

Soredium is the skills, validators, tooling, and engine repository for professional software development workflows and the [Hortora](https://hortora.github.io) knowledge garden system. It delivers:

- **Workflow skills** -- development lifecycle (work-start/end/pause/resume), code review, commits, dependency management, design sync, health checks, content creation
- **Garden skills** -- `forage` (capture, sweep, search, revise) and `harvest` (merge, dedupe) for the Hortora knowledge garden
- **Garden tooling** -- ecosystem mining pipeline, schema validation, garden federation
- **Engine** -- Quarkus/Java 21 CLI application for garden deduplication and pattern detection (`engine/`)
- **TUI/CLI** -- Textual-based terminal UI and JSON Lines CLI for mechanical lifecycle operations without an LLM (`tui/`, `cli/`, `commands/`)
- **Protocol rules** -- standing conventions for taxonomy, validation boundaries, and script requirements

Named after the lichen's dispersal unit: a self-contained bundle that carries everything needed to establish a new colony wherever it lands.

Skills are markdown files with YAML frontmatter that Claude Code loads to execute specific development tasks.

## Project Type

**Type:** skills
**Stage:** pre-release

## Project Type Awareness

**CRITICAL: Skills must handle different project types with appropriate workflows.**

This repository follows the **type: skills** project model. All repositories using these skills declare their type in CLAUDE.md to enable appropriate commit workflows, documentation sync, and validation.

### Project Types

| Type | When to Use |
|------|-------------|
| **`skills`** | Claude Code skill repositories |
| **`java`** | Java/Maven/Gradle projects |
| **`blog`** | GitHub Pages / Jekyll blogs |
| **`custom`** | Working groups, research, docs with custom sync |
| **`generic`** | Everything else |

Comma-separate for mixed repos: `**Type:** java, ts`. Add `**Stage:** released` when the project has consumers.

This repository is **type: skills**. See [docs/PROJECT-TYPES.md](docs/PROJECT-TYPES.md) for full type definitions, routing logic, and when to use each.

The remainder of this document focuses on **type: skills** specific guidance, with the exception of the "Working in engine/" section which covers the Java subproject.

## Skill Architecture

### Frontmatter Requirements

Every `SKILL.md` requires YAML frontmatter with exactly two fields:

```yaml
---
name: skill-name-with-hyphens
description: >
  Use when [specific triggering conditions and symptoms]
---
```

**Critical: Claude Search Optimization (CSO)**

The `description` field determines when Claude loads the skill. Follow these rules:

- **Start with "Use when..."** to focus on triggering conditions
- **NEVER summarize the skill's workflow** in the description
- Describe the *problem* or *symptoms*, not the solution
- Keep under 500 characters if possible
- Third person only (no "I" or "you")

**Why this matters:** If the description summarizes the workflow, Claude may follow the description instead of reading the full skill content. Descriptions are for *when to use*, skill body is for *how to use*.

Bad: `description: Use when executing plans - dispatches subagent per task with code review between tasks`

Good: `description: Use when executing implementation plans with independent tasks in the current session`

### Naming Conventions

Skills follow a hierarchical naming pattern:

**Router skills** (language-agnostic entry points with lazy-loaded content files):
- `code-review` -- routes to `java.md`, `typescript.md`, or `python.md` based on project type
- `security-audit` -- same pattern
- `dependency-update` -- routes to `maven.md`, `npm.md`, or `pip.md`
- `git-commit` -- routes to `java.md`, `custom.md`, or generic
- `update-design` -- routes to `java.md`, `typescript.md`, or `python.md`
- `project-health` -- routes to `java.md`, `typescript.md`, `python.md`, `skills-repo.md`, `blog.md`, `custom.md`

**Language-specific dev skills** (one per language -- auto-trigger on file type):
- `java-dev` -- Java/Quarkus development
- `ts-dev` -- TypeScript development
- `python-dev` -- Python development

**Why this matters:** Language content lives in `.md` files inside the router skill's directory, not in separate skills. A Java developer only loads Java content -- Python/TS content files are never read. When adding a new language to an existing router, add a content file (e.g. `code-review/go.md`) and update the dispatch table in `SKILL.md`.

#### Extending to New Languages

When adding a new language, apply these principles consistently:

1. **Canonical names** -- `go-dev` not `golang-dev`, `ts-dev` not `javascript-dev`
2. **1-word base suffix** -- `*-dev`, `*-code-review`, `*-security-audit` (not `*-development`)
3. **Tool prefix for tools** -- `cargo-*`, `npm-*`, `pip-*`, `gomod-*`
4. **Framework prefix for frameworks** -- `react-*`, `vue-*`, `django-*`
5. **Consistency over brevity** -- match existing patterns

Quick check: `ls -d *-dev *-code-review *-security-audit 2>/dev/null` should show a consistent pattern.

### Skill Chaining

Skills explicitly reference each other to create workflows. The README documents the complete chaining matrix, but when editing skills:

1. **Add cross-references in "Skill Chaining" sections** (capitalized, not "Skill chaining")
2. **Make references bidirectional** when appropriate (e.g., `security-audit` <-> `code-review`)
3. **Use Prerequisites sections** for layered skills -- skills that extend a foundation reference it explicitly
4. **Generic principles skills are never invoked directly** -- they're referenced via Prerequisites by language/framework-specific skills

Example chaining patterns:
```
# Java repository:
java-dev -> code-review -> git-commit -> update-design + update-claude-md (automatic)

# Any repository:
git-commit -> update-claude-md (automatic)

# Garden skills:
forage is invoked during session work (CAPTURE, SWEEP, SEARCH, REVISE)
harvest is invoked in dedicated maintenance sessions (MERGE, DEDUPE)
Both are user-invocable; neither auto-triggers the other
```

### Canonical Path Resolution Block

Several workspace-aware skills (`work-start`, `work-end`, `work-pause`, `work-resume`,
`update-design`, `handover`, `adr`) resolve workspace and project paths via symlinks.
The canonical form -- identical across all of them -- is:

```bash
WORKSPACE=$(git rev-parse --show-toplevel 2>/dev/null)
PROJECT=$(readlink -f proj 2>/dev/null)
[ -z "$PROJECT" ] && { echo "No proj/ symlink found. Run workspace-init to set up."; exit 1; }
```

**Do not use CLAUDE.md parsing** (`grep "**Workspace:**"`, `grep "add-dir"`) for path
detection. The `proj/` -> project and `wksp/` -> workspace symlinks (created by `workspace-init`)
are the single source of truth. CLAUDE.md fields are human documentation only.

If you edit any of these skills, keep this block identical. Verify with:
```bash
grep -l "readlink -f proj" ~/claude/hortora/soredium/*/SKILL.md
```

There is no include mechanism -- this duplication is intentional and the block
is short enough to audit by eye.

### Supporting Files

When skill content exceeds ~200 words or includes heavy reference material:

- Extract to separate `.md` files (e.g., `funcDSL-reference.md`)
- Reference from main `SKILL.md`
- Keep skill body focused on workflow and principles

Pattern:
```
skill-name/
  SKILL.md              # Main workflow (required)
  reference-name.md     # Heavy API/reference docs
  defaults/             # Bundled defaults (optional) -- mandatory rules,
                        #   common voice, or other files the skill always loads
                        #   regardless of user configuration
```

### Skills-Repository-Specific Documentation

**This repository has modularized documentation for skills-specific workflows to avoid token waste in other projects.**

Skills-repository-specific logic (SKILL.md validation, README synchronization) is NOT implemented as portable skills. Instead, it lives in standalone documentation files at the repository root:

| File | Purpose | Used By |
|------|---------|---------|
| **docs/development/skill-validation.md** | SKILL.md validation workflow (frontmatter, CSO, flowcharts, cross-references) | `git-commit` when type: skills AND SKILL.md files staged |
| **docs/development/readme-sync.md** | README.md synchronization workflow (skill collection changes) | `git-commit` when type: skills AND skill changes detected |

**Why modularized (not skills):**
- These workflows only apply to THIS repository
- Loading them as skills wastes tokens in all other projects (java, custom, generic)
- They contain heavy reference material (checklists, tables, patterns)
- CLAUDE.md loads automatically in every conversation
- git-commit can reference these files when operating in type: skills mode

**When git-commit operates in type: skills mode:**
1. Check for staged SKILL.md files -> Follow docs/development/skill-validation.md workflow
2. Check for skill collection changes -> Follow docs/development/readme-sync.md workflow
3. Both workflows maintain the same confirmation pattern (propose -> user YES -> apply)

**These files are NOT:**
- Loaded in java/custom/generic projects (zero token cost)
- Duplicated in skills collection (single source of truth)
- Skills themselves (not in skills/ directory, not user-invocable via Skill tool)

### Flowcharts

Skills use Mermaid `flowchart TD` notation for decision flows. Add flowcharts when:

- Decision points are non-obvious
- Process has loops where you might stop too early
- "When to use A vs B" decisions exist

Never use flowcharts for:
- Reference material (use tables)
- Code examples (use markdown blocks)
- Linear instructions (use numbered lists)

Flowcharts must have semantic labels, not generic ones like `step1`, `helper2`.

### Success Criteria

Skills that produce artifacts (commits, ADRs, dependency updates) include explicit "Success Criteria" sections with checkboxes. This prevents premature completion claims.

Example pattern:
```markdown
## Success Criteria

Dependency update is complete when:

- User has confirmed changes with **YES**
- BOM alignment verified (no version drift)
- Compilation succeeds (`mvn compile` passes)
- pom.xml changes committed

**Not complete until** all criteria met and changes committed.
```

## Modular Documentation

**Note:** This repository does not use modular documentation. Skills use single `SKILL.md` files.

For projects that split large documents into linked modules (e.g., `ARC42STORIES.MD` -> `docs/design/architecture.md` + `api.md` + `data-model.md`), with automatic discovery, validation, and sync across all modules:

**See:** [QUALITY.md -- Modular Documentation Quality Assurance](QUALITY.md#modular-documentation-quality-assurance) and [README.md -- Modular Documentation](README.md#modular-documentation)

## Consistency Patterns

When editing skills, maintain these conventions:

### Section Naming

- "Skill Chaining" (capitalized C)
- "Prerequisites" (for layered skills)
- "Success Criteria" (for artifact-producing skills)
- "Common Pitfalls" (table format: Mistake | Why It's Wrong | Fix)

### Invoke vs Follow Convention

When skills reference other skills, use precise language:

- **"Invoke `skill-name`"** — call it via the Skill tool (explicit tool invocation)
- **"Follow `skill-name`"** — apply its methodology/rules without a Skill tool call
- **"Complements `skill-name`"** — used alongside, neither invokes nor follows

Example: EP says "every task follows TDD" (methodology), not "invoke TDD" (tool call).

### Cross-Reference Format

```markdown
## Prerequisites

**This skill builds on `skill-name`**. Apply all rules from:
- **skill-name**: [specific rules that apply]
```

or

```markdown
## Skill Chaining

**Triggered by skill-name:**
When [condition], it should invoke this skill for [reason].

**Chains to skill-name:**
After [milestone], invoke skill-name for [purpose].
```

### Common Mistakes Tables

All major skills include "Common Pitfalls" tables documenting real mistakes:

```markdown
| Mistake | Why It's Wrong | Fix |
|---------|----------------|-----|
| [Anti-pattern] | [Consequence] | [Correct approach] |
```

### Developer-Only Skills

Some skills in this repository are **developer-only** -- they require a cloned repository and are not available to marketplace plugin users.

**Rules:**
- **A directory at the repository root** -- auto-discovered and synced for developers
- **Not in `marketplace.json`** -- invisible to the web installer and not installable via plugin
- **Not in README.md** -- not documented as a user-facing skill
- **SKILL.md includes a prominent DEV-ONLY note** -- so Claude knows not to recommend it to marketplace users

**Current developer-only skills:**
- `sync-local` -- syncs installed skills from the cloned repo; requires `scripts/claude-skill`
- `fix-ci` -- dev-only CI debugging tool

**When adding a new developer-only skill:**
1. Create it in `<name>/` at the repository root as normal
2. Do NOT add it to `.claude-plugin/marketplace.json`
3. Do NOT add it to README.md
4. Add "DEV-ONLY" prominently in the SKILL.md and CSO description
5. Add it to the "Current developer-only skills" list above

---

### Third-Party Skill Exclusion

**CRITICAL: Only document skills authored by the repository owner.**

**Rules:**
- **Document only user-authored skills** in README.md and CLAUDE.md
- **Never document third-party skills** (skills from external repos, etc.)
- **Add third-party skills to .gitignore** immediately upon discovery
- **Never reference third-party skills** in documentation (chaining tables, workflows, repository structure)

**Rationale:**
- Third-party skills are maintained elsewhere and can change without notice
- Documenting them creates maintenance burden and stale references
- Users already see third-party skills in their skill list
- README/CLAUDE.md should reflect only what this repository provides

**Implementation:**
1. Add skill directory to .gitignore with comment: `# Third-party skill from [source]`
2. Remove all references from README.md (Skills section, Chaining table, Repository Structure)
3. Remove all references from CLAUDE.md (Key Skills section)
4. Verify removal with: `grep -r "skill-name" README.md CLAUDE.md`

**Note:** The original obra/superpowers skills were integrated as
first-party soredium citizens (committed to git, validated, maintained
here). They are no longer third-party. The `skill-creator` skill remains
third-party and excluded.

**Examples of third-party skills to exclude:**
- `skill-creator` (external skill authoring tool)
- `frontend-design:*` (third-party frontend skills)
- Any skill not in version control for this repository

**Quality check:** During deep analysis, verify no third-party skills are documented anywhere. *This is part of the `consistency` category in `project-health`.*

---

## Migration Status

**Migration complete** (2026-04-12). `forage` and `harvest` are deployed and replace the legacy `garden` skill.

- All project CLAUDE.md files updated to reference `forage`/`harvest`
- Garden path is `~/.hortora/garden/` (env var: `HORTORA_GARDEN`)
- Legacy `garden` skill at `~/.claude/skills/garden/` is deprecated
- `harvest` processes submissions from both `forage` and legacy `garden` format (formats are identical)

---

## Writing Style Guide -- Mandatory for Blog Content

**The writing style guide at `~/claude-workspace/writing-styles/blog-technical.md` is mandatory for all blog and diary entries. It is not a soft suggestion.**

When writing a diary or blog entry with `write-content`:
- Load the guide in full before drafting
- Complete the pre-draft voice classification before generating any prose
- Verify the draft against "What to Avoid" before showing it -- do not show a draft that fails

Do not produce a draft without completing these steps. The guide constrains vocabulary, register, heading style, and what to avoid. A Claude that reads the guide and then generates anyway without classification has not followed it.

---

## Developer Workflow

When working on this repository, use these commands:

```bash
# Sync all skills to ~/.claude/skills/ (do this after any skill change)
python3 scripts/claude-skill sync-local --all -y
# Or use the slash command: /sync-local

# Run all tests (~4500 tests; the slot and close suites use real git repos
# and take 10-15 minutes on their own -- run them in the background)
python3 -m pytest tests/ -v

# Run commit-tier validators
python3 scripts/validate_all.py --tier commit

# Run close ceremony and queue tests (real git repos)
python3 -m pytest tests/test_close.py tests/test_close_integration.py tests/test_close_batch.py -v

# Run landing and publishing tests (canonical, slot clone, two bare remotes)
python3 -m pytest tests/test_canonical_sync.py tests/test_landed_check.py -v
python3 -m pytest tests/test_queue_io.py tests/test_queue_file_roundtrip.py tests/test_queue_done_state.py tests/test_work_chain.py -v

# Run slot lifecycle tests
python3 -m pytest tests/test_slot_lifecycle.py tests/test_slot_metadata.py -v

# Run work-end close ceremony audit
python3 work-end/audit_work_end.py mode=check
python3 work-end/audit_work_end.py workspace=$WORKSPACE

# Reconcile slot DB/disk state (three-phase: audit → strategy → execute)
python3 scripts/reconcile_slots.py <family-root>              # audit — report divergences
python3 scripts/reconcile_slots.py <family-root> --strategy   # + propose actions
python3 scripts/reconcile_slots.py <family-root> --execute    # + apply approved actions
python3 scripts/reconcile_slots.py --purge-test-data          # remove pytest pollution from DB

# Run TUI tests (Textual widget + app integration)
python3 -m pytest tests/test_tui_project_view.py tests/test_tui_home_view.py tests/test_tui_app.py tests/test_session_spi.py -v

# Run CLI and command layer tests
python3 -m pytest tests/test_cli.py tests/test_events.py tests/test_commands.py tests/test_discover.py -v

# Launch TUI (requires textual)
python3 -m tui.python

# Run CLI command (JSON Lines output)
python3 -m cli status

# Generate missing slash command files after adding a new skill
python3 scripts/generate_commands.py

# Validate a specific document
python3 scripts/validate_document.py README.md

# Check project type list consistency
python3 scripts/validation/validate_project_types.py --verbose

# Check if a primary doc needs modularising
python3 scripts/validation/validate_doc_structure.py CLAUDE.md

# Validate a garden entry locally (same as CI)
python3 scripts/validate_pr.py <entry_file> ${HORTORA_GARDEN:-~/.hortora/garden}

# Integrate an entry locally (updates indexes, commits -- same as CI)
python3 scripts/integrate_entry.py <entry_file> ${HORTORA_GARDEN:-~/.hortora/garden}

# First-time garden clone (sparse blobless)
bash scripts/garden-setup.sh

# Slot workspace migration (#255)
python3 scripts/place_workspace_markers.py <family-root>         # bootstrap .workspace markers on all slots
python3 scripts/migrate_slot_workspace.py <slot-dir> <family-root>  # migrate old-structure slot to per-repo workspaces
python3 scripts/migrate_slot_workspace.py <slot-dir> <family-root> --dry-run  # preview migration

# Slot backup setup (#515): dry run unless --apply
python3 scripts/slot_backup_setup.py hooks <family-root>               # old push hook -> canonical backup hook
python3 scripts/slot_backup_setup.py remotes <root> owner=<github-user>  # backup remote for single-remote workspace repos
python3 scripts/slot_backup_setup.py detach <family-root>              # existing slot clones lose their GitHub remotes

# Slot state migration (backfill state: field in .slot files)
python3 scripts/migrate_slot_state.py <family-root>           # dry-run: shows what needs changing
python3 scripts/migrate_slot_state.py <family-root> --apply   # apply state field to .slot files

# Permanent clone management (#553)
python3 project/clone_manager.py create family_root=<path> repo=<name>  # create a permanent clone
python3 project/clone_manager.py status family_root=<path> repo=<name>  # check if clone exists
python3 project/clone_manager.py enable family_root=<path>              # enable clones for a family
python3 project/clone_manager.py enabled family_root=<path>             # check if clones enabled

# One queue per area (#577): list a slot's queues, switch one slot to its root queue
python3 project/queue_home.py show <slot-or-clone-dir>
python3 project/queue_home.py adopt <slot-or-clone-dir> from=<dir> [--apply]   # dry run unless --apply

# Lifecycle trace (#575): what the tools did, most recent last
python3 project/worktrace.py show limit=40                 # every recorded action
python3 project/worktrace.py show action=publish           # one kind of action
python3 -m pytest tests/test_worktrace.py -v

# Permanent clone tests
python3 -m pytest tests/test_clone_manager.py tests/test_clone_work_end.py tests/test_work_clone_guard.py -v

# Fix absolute wksp/proj/CLAUDE.md symlinks (one-time migration)
python3 scripts/fix_absolute_symlinks.py              # dry-run: shows what needs changing
python3 scripts/fix_absolute_symlinks.py --apply       # apply fixes

# Ecosystem mining pipeline
python3 scripts/run_pipeline.py          # orchestrate: registry -> extract -> cluster -> delta -> report
python3 scripts/validate_candidates.py   # human validation gate (accept/reject/skip candidates)

# Garden federation tooling
python3 scripts/validate_schema.py <garden_path>   # validate SCHEMA.md federation config
python3 scripts/init_garden.py <path> --name NAME --description DESC \
  --role canonical|child|peer --ge-prefix PREFIX --domains d1 d2 [--upstream URL]
python3 scripts/validate_garden.py <garden_path>   # now also checks SCHEMA.md when present
python3 scripts/validate_garden.py <garden_path> --freshness  # check entry staleness

# Registry management
# scripts/project_registry.py    -- CRUD for monitored projects (registry/projects.yaml)
# scripts/rejection_registry.py  -- suppress re-surfacing of rejected candidates (known_rejections.yaml)
# scripts/candidate_report.py    -- JSON serialization for pipeline output
# scripts/pattern_entry.py       -- GP-ID skeleton generator for accepted patterns
# scripts/feature_extractor.py   -- regex-based structural fingerprinting
# scripts/cluster_pipeline.py    -- cosine similarity clustering
# scripts/delta_analysis.py      -- new abstractions between git tags

# Enrichment + GitHub cache (worklog DB v2)
# scripts/enrichment.py upsert  -- write enrichment metadata for an issue
# scripts/enrichment.py get     -- read enrichment for a single issue
# scripts/enrichment.py list    -- list all enrichments for a repo
# scripts/enrichment.py trajectory -- append a trajectory note to an issue
# scripts/enrichment.py refresh -- refresh GitHub issue cache for a repo
# scripts/enrichment.py what-next -- query for what-next recommendations
```

**After editing any skill:** run `sync-local` so `~/.claude/skills/` has the latest version.
**After adding a new skill:** run `generate_commands.py` AND add to `marketplace.json` plugins list.
**Worktrees for feature development:** use `.worktrees/` (gitignored). Create with `git worktree add .worktrees/<name> -b <branch>`. Always use `--force` when removing after subagent use.

---

## Working in engine/

The `engine/` directory contains a **Quarkus/Java 21** CLI application for garden deduplication and pattern detection. It is a self-contained Maven subproject with its own `pom.xml`.

**Stack:** Quarkus 3.x, LangChain4j (jlama, ollama, anthropic providers), picocli, Jackson

**Build and test:**
```bash
/opt/homebrew/bin/mvn -f engine/pom.xml compile        # compile
/opt/homebrew/bin/mvn -f engine/pom.xml test            # run tests
/opt/homebrew/bin/mvn -f engine/pom.xml quarkus:dev     # dev mode with live reload
/opt/homebrew/bin/mvn -f engine/pom.xml package         # build jar
```

**Key conventions:**
- Java 21 -- use records, sealed interfaces, pattern matching where appropriate
- Package root: `io.hortora.garden.engine`
- The `java-dev` skill applies when working in `engine/` -- it provides Quarkus-specific patterns, CDI conventions, and testing guidance
- The top-level project type remains `skills` -- `java-dev` is invoked contextually when editing `.java` files under `engine/`

---

## How Claude Code Loads Skills

Skills live in `~/.claude/skills/<skill-name>/` and are **auto-discovered** -- no registration in `settings.json` or `installed_plugins.json` is needed.

**Skills must be real directories, not symlinks.** Claude Code does not follow symlinks in `~/.claude/skills/`. A symlink at `~/.claude/skills/java-dev` pointing elsewhere will be silently ignored -- the skill will not load. Always copy skill content into the directory.

**Skills need a `commands/` directory for slash commands.** A skill with only a `SKILL.md` is loadable by Claude via the Skill tool (triggered automatically by description matching) but does NOT create a `/skill-name` slash command in the UI. To register a slash command, the skill must have `commands/<skill-name>.md`. Use `python scripts/generate_commands.py` to create missing command files.

**`~/.claude/plugins/cache/` is the wrong location.** That directory is managed by Claude Code's marketplace package manager (`/plugin install`). Skills placed there work but require versioned subdirectories, `installed_plugins.json` registration, and `enabledPlugins` entries -- unnecessary complexity. Always use `~/.claude/skills/` instead.

## Editing Skills

When modifying existing skills:

1. **Check README first** -- the Skill Chaining Reference table shows the complete dependency graph
2. **Update cross-references** -- if you add chaining, update both skills (source and target)
3. **Preserve CSO descriptions** -- don't add workflow summaries to frontmatter
4. **Test flowcharts** -- invalid dot syntax breaks skill loading
5. **Maintain Prerequisites** -- layered skills must reference their foundations

## Pre-Commit Checklist for Skills

**CRITICAL: All items are MANDATORY by default unless explicitly marked (advisory).**

**This is NOT a judgment call. This is NOT optional. This is a DISCIPLINE.**

Failing to execute these checks before committing is a failure, not a decision. The bigger the change, the more critical the checklist becomes. Infrastructure changes especially require documentation sync.

### Mandatory Checks

Run these checks **before every commit** to this repository. *These map to `project-health` categories -- see [docs/project-health.md](docs/project-health.md). For a full pre-release health check: `/project-health --all`.*

- [ ] **New skill added?** -> Run `python scripts/generate_commands.py` to create its slash command file `[coverage]`
- [ ] **SKILL.md files modified?** -> Follow docs/development/readme-sync.md workflow (NEVER skip, let it decide if README needs updates) `[docs-sync]`
- [ ] **CLAUDE.md modified?** -> Follow relevant update workflow if applicable `[docs-sync]`
- [ ] **New validation/testing added?** -> Update README.md -- Skill Quality & Validation AND QUALITY.md -- Implementation Status `[infrastructure]`
- [ ] **New scripts/ files added?** -> Update README.md -- Repository Structure `[coverage]`
- [ ] **New chaining relationships?** -> Update README.md -- Skill Chaining Reference `[cross-refs]`
- [ ] **New features added to skills?** -> Update README.md -- Key Features `[docs-sync]`
- [ ] **Framework changes** (same pattern across multiple skills)? -> Document in README.md AND QUALITY.md if validation-related `[consistency]`
- [ ] **Infrastructure changes** (validators, test infrastructure, orchestrators)? -> Update README.md -- Repository Structure, QUALITY.md -- Implementation Status, and this file -- Validation Script Roadmap `[infrastructure]`

### When Work Tracking Is Configured

If a project's CLAUDE.md contains `## Work Tracking` with `Issue tracking: enabled`, Claude must:
- **Before any significant task**: check if the request spans multiple concerns; if so, help break it into separate GitHub issues before starting work
- **Before any commit**: check if staged changes span multiple issues; if so, suggest splitting with `git add -p`
- **In every commit message**: include `Refs #N` or `Closes #N` for the related issue
- **For changelogs**: use `gh release create --generate-notes` -- do NOT maintain a CHANGELOG.md manually

The `issue-workflow` skill handles setup of this configuration and the pre-commit analysis.

### Skill edits always go to this project first

**NEVER write skill edits directly to `~/.claude/skills/`.** Always edit in this
repository (`~/claude/hortora/soredium/`), then run `sync-local` to propagate. This keeps
git history, validation, and marketplace metadata in sync.

### When Adding a New Project Type

**Adding a new project type (e.g. `python`, `go`) requires updating ALL of these:**

- [ ] **`CLAUDE.md` -- Project Types table** -- add the new type row (this is the canonical source of truth)
- [ ] **`docs/PROJECT-TYPES.md`** -- full type documentation and routing logic
- [ ] **`git-commit/SKILL.md`** -- routing logic in Step 0 (adds new type branch)
- [ ] **`~/.claude/hooks/check_project_setup.sh`** -- live hook (`Choices:` line)
- [ ] **Run `python scripts/validation/validate_project_types.py --verbose`** -- confirms no hardcoded lists were missed

**The validator (`validate_project_types.py`) catches hardcoded lists automatically at commit time,
but this checklist ensures the new type is fully wired into all workflows.**

### Known Regressions (Learn From These)

**Regression 1:** Validation framework added to 4 sync workflows but README.md not updated. Root cause: Skipped docs/development/readme-sync.md workflow, rationalized "just internal changes". Result: Documentation drift. Fix: Never skip workflows when SKILL.md files change.

**Regression 2:** Created 14 validators + test infrastructure (17 new files, ~2,800 LOC), committed completion document, but didn't update README.md -- Repository Structure or QUALITY.md -- Implementation Status until user asked. Root cause: Tunnel vision on Options A/B/C, didn't check Pre-Commit Checklist, rationalized "completion doc is sufficient". Result: Primary documentation out of date. Fix: Infrastructure changes require MORE documentation sync, not less. Checklist is mandatory, not advisory.

---

## Maintaining the Work Lifecycle

Before changing anything in start, wrap, end, landing, publishing, queues, slots, clones or the worklog, read [docs/development/lifecycle-maintainer-guide.md](docs/development/lifecycle-maintainer-guide.md): the rules that are not negotiable, how each command and the ceremony work, how to change things safely, what has gone wrong before, areas to watch and the open improvements. Keep it current in the same change that makes a section untrue.

---

## Protocols

`docs/protocols/` holds standing rules for the codebase -- constraints and conventions that apply when working on scripts, validation, or skills. Read the index before filing issues that touch validation scripts.

| File | Rule |
|------|------|
| [validate-schema-vs-validate-pr.md](docs/protocols/validate-schema-vs-validate-pr.md) | GE frontmatter validation belongs in validate_pr.py, not validate_schema.py |
| [externalised-scripts-require-tests.md](docs/protocols/externalised-scripts-require-tests.md) | Every externalised .py script ships with meaningful unit tests |
| [evidence-before-claims.md](docs/protocols/evidence-before-claims.md) | Run the command, read the output, THEN claim the result — at every completion boundary |
| [taxonomy-rename-idempotent-script.md](docs/protocols/taxonomy-rename-idempotent-script.md) | Taxonomy rename operations must be idempotent |
| [taxonomy-values-reflect-content-character.md](docs/protocols/taxonomy-values-reflect-content-character.md) | Taxonomy values describe content character, not form |
| [write-content-three-layer-taxonomy.md](docs/protocols/write-content-three-layer-taxonomy.md) | Three-layer taxonomy for write-content |
| [a-read-never-writes.md](docs/protocols/a-read-never-writes.md) | Reading the queue, detecting state and resolving context change no file |
| [one-queue-per-area-never-synced.md](docs/protocols/one-queue-per-area-never-synced.md) | One queue per area of work, never synced; only `queue_io.queue_dir` decides where it is |
| [the-script-that-acts-records-it.md](docs/protocols/the-script-that-acts-records-it.md) | Lifecycle actions are recorded through `worktrace` by the script that performs them |
| [issue-references-are-always-qualified.md](docs/protocols/issue-references-are-always-qualified.md) | Issue references are `owner/repo#N` everywhere |
| [a-test-must-fail-with-the-rule-removed.md](docs/protocols/a-test-must-fail-with-the-rule-removed.md) | Break the rule on purpose and see the test fail |

---

## Key Skills

**Workspace:**
- `workspace-init` -- one-time setup; creates `~/claude/private/<project>/` or
  `~/claude/public/<project>/` with routing CLAUDE.md, gitignored project symlink
  via `.git/info/exclude`, and all subdirectories
- `work` -- **unified lifecycle entry point**; `work`, `work start` (without issue), `work continue` and `work next` are all spellings of one operation: `work.py continue`, which reads the queue via `work_route.py:route()` and decides what to run. `work start #N` runs `work.py start issue_n=N`. `work pause`, `work resume`, `work find` each run `work.py <command>`. `work end` and `work sync` use `work-end/close.py`. Routing decisions come from `project/work_route.py`, never from the LLM or `work_chain.py` for these commands
- `work.py` -- unified pipeline engine (`project/work.py`); Python-driven lifecycle for 6 commands (start, continue, done, pause, resume, find). Each command maps to a step list of `StepDef` objects. Mechanical steps run without LLM involvement; judgment steps yield `ACTION=` for LLM dispatch to handler files in `work/handlers/`. Uses `orchestrator_engine.run_loop`. Three-tier conflict resolution via `conflict_resolution.py`
- `.queue` -- the issue queue and its state, one per area of work and never synced between areas. `queue_io.queue_dir(workspace)` is the only rule for where it is: the root of a slot or clone that carries `.queue-root`; else a workspace's `.notes` worktree when that already holds the queue; else the workspace's own `.queue` or `.plan`; else `.notes` for a workspace with that worktree and no queue yet. In a marked slot the `.queue` a workspace clone inherited from its repo is never read, committed or removed. `project/queue_home.py show|adopt <slot>` lists a slot's queues and switches one slot to its root queue (dry run unless `--apply`); a new permanent clone is switched at creation. Read and written by `work-slot/plan_manager.py` and `project/queue_io.py`; never edited by hand. Queue status is one of `active`, `paused`, `drained`, `idle`. An item is unchecked, **done but not closed** (`- [ ] ref — title ← done on <branch>`, written by `plan_manager.py mark-done`), or checked (closed by the close ceremony). Items build on each other by default: `work start` stacks a new branch on the branch of the item just before it while that item is unclosed, in every repo, and records what each branch was cut from in `refs/soredium/base/<branch>` and `refs/soredium/parent/<branch>` (`project/branch_base.py`). An item marked `(from main)` (`plan_manager.py set-base` or `append ... base=main`) starts its code from the base branch; the workspace repo still continues from the previous branch because it holds the queue
- `worktrace.py` -- the one place lifecycle actions are recorded in the worklog (`project/worktrace.py`). The script that performs an action records it: `work.py` records each command's begin, every step, completion and every stop with its reason; `canonical_sync.py` records `land`, `publish` and `publish-failed`; `close.py` records `stamp`, `issue-close`, `close-ceremony` and ends the work item; `artifact_promote.py` records `promote`; blog publishing records `blog-publish` and `blog-held`. Slot create, merge and archive are recorded by `work-slot/slot_state.py`. Recording never fails the action: an error is one `WARN=worklog_not_recorded` line. A new script that lands, publishes, promotes, closes or archives must record through it
- `clone` -- a permanent per-repo clone at `<family>/clone/<repo>/` holding a project clone (`<repo>/`), its workspace clone, `.slot` and `.permanent` marker. Its only remote is `local`, pointing to its canonical repo. Enabled per family by `<family>/.clone-enabled` (created by `clone_manager.py enable`). `work-end/close.py` lands a permanent clone's branches through canonical and never archives it: when the queue drains the clone stays as-is. `work.py` (`apply_clone_guard`) stops new work in a canonical repo of an enabled family, returning `ACTION=stop` with `STOP_REASON=canonical_repo_of_clone_family` and directing the user to the clone. Managed by `project/clone_manager.py` (create, status, enable, enabled commands)
- `lifecycle.py` -- older state machine (`project/lifecycle.py`) with a transition table that includes `closing:*` states. The close ceremony no longer uses it, and the pre-push gate that read it is gone
- `work_chain.py` -- legacy chaining engine (`project/work_chain.py`); no skill runs it as a script any more. `ctx.py` imports `done_fields` from it. Its `evaluate` function is exercised only by tests (`test_work_chain.py`, `test_sync_chain.py`, `test_done_wiring.py`). Retirement tracked separately
- `work start` -- for `work start #N`, runs `project/work.py start issue_n=N` (the start pipeline): sync main, resolve issue (judgment), branch name (judgment), create branches, scaffold, brainstorm offer (judgment). For `work start` without an issue, runs `work.py continue` which routes through `work_route.py:route()` to either start the next open item or resume paused work. Mechanical steps delegate to `branch_create.py`, `scaffold.py`, `flyway_scan.py`
- `work wrap` / `work end` (pipelines) -- `project/work.py wrap|end`: review, diary, issues filed and queued, "is the item finished?" (never skipped), mark done, commit queue, then for `end` only: land what is marked done, promote, publish the covered repos and their blog entries; then handoff. `SCOPE=` is printed first and `work-end/scope.py` limits publishing to it. A failed mechanical step stops the sequence and is never skipped; a retry resumes at that step. Typing `work end` is the go-ahead to publish exactly that scope
- `work end` -- closes work via the `work-end/close.py` ceremony; resolves targets, runs preflight, lands branches in the canonical repo on disk through `project/canonical_sync.py` (rebase + fast-forward; it never squashes and never pushes, see Landing Rules), stamps, advances queue. Publishing is a separate step the ceremony offers: `canonical_sync.py publish <repo>`. One ceremony lands every done-not-closed item and the active one, in an order it derives from what each branch was cut from (queue order only breaks ties); a stacked branch lands after its parent and contributes only its own commits. Pre-close advisory checklist (code review, branch audit, sweeps, diary), run once per batch. Post-close closes GitHub issues. In a slot it never archives: when the queue drains it marks the slot landed and reports it ready for archive
- `work pause` -- pipeline-driven (`project/work.py pause`); entirely mechanical (3 steps: WIP commit project, WIP commit workspace, push-and-stack). Despite the step's name nothing is pushed, pulled or stashed: the canonical repo backs the branch up and, in a slot, the stack entry is landed through `canonical_sync`. Delegates to `pause_exec.py`
- `work resume` -- pipeline-driven (`project/work.py resume`); 6 steps: stack pick (judgment), pop stack, checkout branches, rebase, reset WIP, context resume (judgment). Delegates to `resume_exec.py`
- `brief` -- orientation summary; composes ctx.resolve(), work_router.detect_state(), work_health.run_checks() into structured KEY=VALUE output showing branch, issue, plan progress, recent commits, health status

**Garden skills:**
- `forage` -- CAPTURE (GitHub mode + local mode), SWEEP, SEARCH, REVISE -- session-time garden operations
- `harvest` -- MERGE (via integrate_entry.py), DEDUPE, REVIEW -- dedicated maintenance sessions
- `protocol` -- CAPTURE, SWEEP, SEARCH, HEALTH -- project-level protocol management

**Branch-level review:**
- `branch-audit` -- holistic branch-level review across four dimensions (Conformance, Coherence, Structure, Robustness); runs in the work-end pre-close checklist (Step 2); fills the post-implementation lifecycle point in review-tiers.md

**Router skills** (dispatch to per-language content files -- never load cross-language content):
- `code-review` -- Java/TS/Python per-line checklist via `java.md`, `typescript.md`, `python.md`
- `security-audit` -- Java/TS/Python OWASP audit, same pattern; escalated by branch-audit Robustness dimension
- `dependency-update` -- Maven/npm/pip management via `maven.md`, `npm.md`, `pip.md`
- `git-commit` -- routes to `java.md`, `custom.md`, or generic
- `quick-fix` -- commits a small change on the base branch and lands it on disk through `project/canonical_sync.py`; never stashes, resets or pushes; used by fix-ci
- `update-design` -- ARC42STORIES.MD sync via `java.md`, `typescript.md`, `python.md`
- `project-health` -- universal checks + per-type content files

**Language dev skills** (auto-trigger on file type):
- `java-dev` -- Java/Quarkus development
- `ts-dev` -- TypeScript development
- `python-dev` -- Python development

**Workflow integrators:**
- `git-commit` -- entry point for all commits; routes by project type
- `issue-workflow` -- GitHub issue tracking; invoked automatically when Work Tracking is enabled
- `retro-issues` -- on-demand retrospective mapping of git history to epics and issues
- `update-claude-md` -- CLAUDE.md sync, invoked by all commit skills
- `docs/development/readme-sync.md` -- README.md sync, invoked by `git-commit` for type: skills only
- `adr` -- Architecture Decision Records in MADR format
- `idea-log` -- lightweight living log for undecided possibilities; park ideas before they evaporate, promote to ADR when ready
- `write-content` -- universal content creation skill; determines content type (Note/log/musing/idea, Article/explanation/commentary/essay/tutorial/how-to, Brief, News), applies structure principles, anti-slop guidance, and form-specific rules; also the skill for the project diary (diary type): decisions, pivots, and discoveries captured in diary voice as they happen
- `publish-blog` -- routes blog entries to external git destinations via blog-routing.yaml; Level 2 blog routing (per-entry cross-posting), independent of epic Level 1 routing
- `handover` -- end-of-session HANDOFF.md generator; lazy references to blog and CLAUDE.md rather than loading them; invokes write-content and update-claude-md via user-confirmed wrap checklist

**TypeScript/Node.js:**
- `ts-dev` -- TypeScript development; strict mode, async patterns, error handling, testing
- Router skill content files for TypeScript/Node.js:
  - `code-review` routes to `typescript.md` -- TypeScript/Node.js review rules
  - `security-audit` routes to `typescript.md` -- OWASP Top 10 for TypeScript/Node.js
  - `dependency-update` routes to `npm.md` -- npm/yarn/pnpm dependency management
  - `project-health` routes to `typescript.md` -- TypeScript-specific health checks

**Python:**
- `python-dev` -- Python development; type hints, async patterns, safety, testing with pytest
- Router skill content files for Python:
  - `code-review` routes to `python.md` -- Python review rules
  - `security-audit` routes to `python.md` -- OWASP Top 10 for Python
  - `dependency-update` routes to `pip.md` -- pip/poetry/pipenv dependency management
  - `project-health` routes to `python.md` -- Python-specific health checks

**Health & quality skills** (correctness and improvement):
- `project-health` -- universal health check; answers "is the project correct, complete, and consistent?"; loads the content file for the project type (`java.md`, `typescript.md`, `python.md`, `skills-repo.md`, `blog.md`, `custom.md`) rather than chaining to a separate skill
- `project-refine` -- companion to project-health for improvement opportunities; never blocks work

## Quality Assurance Framework

**Comprehensive validation ensures skills maintain structural integrity, logical soundness, and documentation accuracy.**

Skills are infrastructure code guiding AI behavior across millions of invocations. Quality issues compound exponentially. This framework provides automated checks (scripts), semantic analysis (Claude), and functional testing.

### Quality Assurance Philosophy

**Scripts handle mechanical checks (syntax, structure, format).**
**Claude handles semantic analysis (logic, contradictions, completeness).**

For complete details on the division of labor, validation tiers, what gets checked, and integration patterns:
[QUALITY.md -- The Architecture: Scripts + Claude](QUALITY.md#the-architecture-scripts--claude)

### Automated Validation

**19 validators across 3 tiers (COMMIT/PUSH/CI):**

For complete validator specifications, tier assignments, and implementation details:
[QUALITY.md -- Implementation Status](QUALITY.md#implementation-status)

**Pre-Commit Checklist integration:** See Pre-Commit Checklist for Skills above for mandatory validation hooks.

### Deep Analysis Procedures

When user requests deep analysis of skills ("/skill-review", "do a deep analysis", "comprehensive review"):

*These checks map to the `project-health` skill. Invoke as `/project-health --deep` for a full deep analysis, or with specific categories.*

[QUALITY.md -- Deep Analysis Validation](QUALITY.md#deep-analysis-validation-level-2)

**Mandatory checklist:**
- [ ] Run all automated checks (`python scripts/validate_all.py --tier commit`)
- [ ] Perform all manual analysis procedures (reference accuracy, logical soundness, completeness, etc.)
- [ ] Document findings by severity (CRITICAL/WARNING/NOTE)
- [ ] Create action items for CRITICAL/WARNING findings

### Validation Infrastructure

For complete inventory of validation scripts by tier:
[QUALITY.md -- Validation Script Roadmap](QUALITY.md#validation-script-roadmap)

**Quick reference (19 validators total):**
- **COMMIT tier (<2s)**: frontmatter, CSO, references, naming, sections, structure, project-types, blog-frontmatter, plan-bypass
- **PUSH tier (<30s)**: flowcharts, cross-document, temporal, usability, edge-cases, behavior, readme-sync, external-links, code-examples
- **CI tier (<5min)**: Python quality (mypy, flake8, bandit) + functional tests
- **On disk, not yet registered**: validate_blog_commit.py (git hook only -- needs commit message), validate_doc_structure.py (on-demand -- needs target path)

### Success Criteria

Validation framework is working when:
- Zero CRITICAL findings pass pre-commit
- All skills have functional tests
- All known issues have regression tests
- Deep analysis finds <=5 WARNING issues per 40 skills
- No duplicate issues across releases
- CI blocks PRs with validation failures

For complete success criteria and implementation status:
[QUALITY.md -- Success Criteria for QA Framework](QUALITY.md#success-criteria-for-qa-framework)

---

## Document Sync Quality Assurance

**Universal validation prevents document corruption during sync operations across all project types.**

For complete details on validation rules, integration points, corruption patterns, and regression prevention:
[QUALITY.md -- Document Sync Quality Assurance](QUALITY.md#document-sync-quality-assurance)

### Running Validators Locally

```bash
# Validate a specific document
python scripts/validate_document.py README.md
python scripts/validate_document.py CLAUDE.md

# Validate all staged .md files
git diff --staged --name-only | grep '\.md$' | xargs -I{} python scripts/validate_document.py {}

# Run full commit-tier validation suite
python scripts/validate_all.py --tier commit
```

Exit codes: `0` = clean, `1` = CRITICAL (blocks commit), `2` = WARNING (review recommended), `3` = NOTE

Local validation is optional but recommended -- pre-commit validation runs automatically and is mandatory.

---

## Landing Rules

Every script and skill that merges, pushes or squashes must obey these. They are
being enforced in stages; the design, the landing flow and the stage order are in
Hortora/soredium#515, and the slot-layout follow-on is #512.

1. **Linear history.** No merge commits on a base branch, in project or workspace repos.
2. **Canonical is the sync point.** The repos directly under `~/claude/<family>/` are
   canonical. Work reaches canonical before it reaches anything else.
3. **Only canonical publishes.** Slots, clones and feature branches never push to GitHub.
   A slot clone's only remote is `local`, its canonical repo: it has no `origin` or
   `upstream`, so there is nowhere for a push to go. Checks measure a slot against
   canonical and a canonical repo against its remote (`canonical_sync.reference`).
   A canonical repo ahead of its remote is landed work awaiting publish: normal, not an error.
   Landing and publishing are separate: `work end` lands on disk, and
   `project/canonical_sync.py publish <repo>` pushes canonical's base branch when asked.
4. **No direct squashes.** Squashing happens only through the `git-squash` skill, which
   records the tip it reviewed in `refs/squash-reviewed/<branch>`. `work-end/close.py`
   never squashes, and lands a multi-commit branch only when that record equals the
   branch tip; otherwise it returns `ACTION=squash_review_needed`.

`git-squash/hooks/pre-push` is the git-level hook: a push to a base branch must not add
a merge commit, rewrite the branch or delete it. It judges nothing else; history is
reviewed before landing, not at push time.

`hooks/push-guard.py` (a PreToolUse hook installed by `sync-local`) blocks `git push`
from a slot clone and of any working branch, and names `work end` and
`canonical_sync.py publish` instead. A hook blocks only with exit code 2 and the
reason on stderr; `tests/test_push_guard_hook.py` attempts the push to prove it.

Canonical may be mid-work: never stash, reset or check out in a canonical repo, and
never run `git rebase --abort` or `git merge --abort` on an operation you did not
start — commits made while it was stopped belong to no branch and are discarded.

Claims about git or script behaviour must be observed, not assumed.
`tests/test_git_landing_behaviour.py` pins the git behaviours the design relies on.

---

## Workspace Model

Skills write methodology artifacts to a companion workspace, not the project repo.

- **soredium workspace:** `~/claude/public/cc-praxis/` (repurposed from cc-praxis)
- Claude opens in the workspace; project loaded via `add-dir` in workspace CLAUDE.md
- Navigation: `proj/` in workspace -> project; `wksp/` in project -> workspace

---

## Work Tracking

**Issue tracking:** enabled
**GitHub repo:** Hortora/soredium
**Changelog:** GitHub Releases (run `gh release create --generate-notes` at milestones)

**Automatic behaviours (Claude follows these at all times in this project):**
- **Before implementation begins** -- when the user says "implement", "start coding",
  "execute the plan", "let's build", or similar: check if an active issue or epic
  exists. If not, run issue-workflow Phase 1 to create one **before writing any code**.
- **Before writing any code** -- check if an issue exists for what's about to be
  implemented. If not, draft one and assess epic placement (issue-workflow Phase 2)
  before starting. Also check if the work spans multiple concerns.
- **Before any commit** -- run issue-workflow Phase 3 (via git-commit) to confirm
  issue linkage and check for split candidates. This is a fallback -- the issue
  should already exist from before implementation began.
- **All commits should reference an issue** -- `Refs #N` (ongoing) or `Closes #N` (done).
  If the user explicitly says to skip ("commit as is", "no issue"), ask once to confirm
  before proceeding -- it must be a deliberate choice, not a default.

## Project Artifacts

Paths that are project content (not workspace noise). Skills use this to avoid
filtering or dropping commits that touch these paths.

| Path | What it is |
|------|------------|
| `CLAUDE.md` | Project conventions (build, test, naming) |
| `docs/adr/` | Architecture decision records |
| `docs/blog/` | Project diary / blog entries |
| `docs/specs/` | Design specifications |
| `docs/protocols/` | Standing rules for taxonomy and conventions |
| `engine/` | Quarkus/Java garden engine |
| `tui/` | Textual TUI application |
| `cli/` | CLI entry point (JSON Lines) |
| `commands/` | Portable command layer (events, registry, command modules) |
| `registry/` | Ecosystem mining project registry |
| `verification/` | Shared verification library for lifecycle postconditions |

---

## Meta-Rule: Checklists Are Mandatory

All checklists in this file and in skills are **MANDATORY** unless explicitly marked `(advisory)`, `Optional:`, or `Consider:`. If not marked, do it.

If a checklist item seems inapplicable: re-read it, check for rationalization, execute it anyway if uncertain. If it truly doesn't apply, document why in the commit message. Never skip silently.

---

## Meta-Rule: Consider Universality First

**CRITICAL: Before applying any fix, ask "Should this be universal?"**

**The principle:**
When you identify a problem and prepare a solution, STOP and consider:
1. **Is this problem specific to one context** (skills repo only, Java only, this file only)?
2. **Or is this a universal problem** (could happen in any project type, any AI assistant, any workflow)?

**If uncertain whether to make it universal -> ASK THE USER.**

**Examples:**

| Situation | Narrow Fix | Universal Fix | Correct Choice |
|-----------|------------|---------------|----------------|
| README.md sync missing | Add check to docs/development/readme-sync.md only | Add framework change detection to ALL sync workflows | Universal (ADR-0001) |
| Java-specific BOM issue | Fix in maven-dependency-update | Make dependency management universal | Narrow (Java-specific) |
| Rationalization bypass | Strengthen git-commit Step 2b | Add mandatory checks to all workflows | Universal |
| Quarkus event loop bug | Fix in quarkus-flow-dev | Make concurrency universal | Already universal (code-review-principles) |

**Why this matters:**
- **Prevents repeated regressions** - fix once, applies everywhere
- **Scales to future project types** - type: python, type: rust get the fix automatically
- **Reduces user burden** - don't re-discover same problem per project
- **Forces better design** - universal solutions are often cleaner

**When to stay narrow:**
- Domain-specific knowledge (Java annotations, Quarkus configuration)
- Language syntax (Java vs Python vs Go)
- Tool-specific features (Maven BOM vs npm package.json)
- Framework patterns (Quarkus vs Spring)

**When to go universal:**
- Process failures (rationalization, skipping workflows)
- Quality gates (validation, testing, documentation)
- Human behavior patterns (cognitive biases, shortcuts)
- Infrastructure (scripts, automation, validation)

**The test:** If the problem could plausibly occur in a different project type with different technologies, it's probably universal.

**See:** ADR-0001: Documentation Completeness Must Be Universal, Not Project-Specific
