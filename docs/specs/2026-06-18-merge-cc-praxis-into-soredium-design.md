# Design: Merge cc-praxis into soredium

**Status:** Approved (revised after third review)  
**Date:** 2026-06-18

---

## Goal

One project, one plugin. Merge cc-praxis into Hortora/soredium. Archive cc-praxis. 17 blog posts move to hortora.github.io.

## Decision summary

| Question | Answer |
|----------|--------|
| Target repo | Hortora/soredium (keeps name) |
| Merge method | Git history merge (`--allow-unrelated-histories`) |
| Root file conflicts | Semantic manual merge (not git auto-merge) |
| Plugin identity | One plugin called "soredium" |
| cc-praxis repo | Archive on GitHub after merge verified |
| Blog | 17 posts move to hortora.github.io; global renumbering |

## Skill inventory (exact)

**cc-praxis SKILL.md directories:** 30
**cc-praxis marketplace plugins:** 28

| Excluded from marketplace | Reason |
|---------------------------|--------|
| fix-ci | Dev-only — no marketplace entry |
| sync-local | Dev-only — requires cloned repo + scripts/claude-skill |

**soredium SKILL.md directories:** 3
**soredium marketplace plugins:** 2

| Excluded from marketplace | Reason |
|---------------------------|--------|
| protocol | Not listed — **decision: add to marketplace** (user-facing, invoked by handover wrap checklist) |

**Merged marketplace total: 31 plugins** (28 cc-praxis + 2 soredium + protocol)
**Merged SKILL.md total: 33 directories** (30 + 3, two dev-only)

## The polyglot problem

Soredium is not "3 garden skills and some tooling." It contains `engine/` — a full Quarkus/Java 21 application (52 Java files, LangChain4j, picocli CLI, its own pom.xml). After merging cc-praxis (pure Python/Markdown), the merged repo is:

- 33 Claude skills (Markdown)
- ~50 Python scripts + 5 utility modules + 19 validators
- ~95 test files (~1988 tests)
- A Quarkus/Java CLI application (52 Java files)

**Pre-existing gap:** soredium's current CLAUDE.md contains zero references to engine/. The engine exists, has a full Quarkus application with LangChain4j integrations, but no developer workflow guidance. The merge fixes this gap — the merged CLAUDE.md documents engine/ for the first time.

**Project type consequence:** `type: skills` in CLAUDE.md won't trigger `java-dev` for engine work. The merged CLAUDE.md must acknowledge this. Two options:

1. **Polyglot type declaration** — introduce a convention like `type: skills+java` or list both, so skill routing can load java-dev when working in `engine/`
2. **Subproject carve-out** — document engine/ as a subproject with its own conventions section in CLAUDE.md (Maven commands, Java version, Quarkus patterns) while the top-level type stays `skills`

**Decision: option 2 — subproject carve-out.** The engine is self-contained in one directory. Adding a new project type creates complexity across all router skills for a single subdirectory. A "Working in engine/" section in CLAUDE.md with Maven commands and a note that java-dev applies there is cleaner.

**CI consequence:** cc-praxis has two GitHub Actions workflows (pages.yml for Jekyll, skill-validation.yml for validators). Soredium has none. Post-merge:
- `pages.yml` is removed (blog moves to hortora.github.io)
- `skill-validation.yml` applies to the merged repo — keep it, update paths if needed

## 1. Backup

- Tag cc-praxis: `pre-hortora-merge` (push tag)
- Tag soredium: `pre-merge` (push tag)
- cc-praxis stays archived on GitHub as full recovery path
- Rollback: `git reset --hard pre-merge` on soredium

## 2. Git merge

```bash
# On soredium
git remote add cc-praxis https://github.com/mdproctor/cc-praxis.git
git fetch cc-praxis
git merge cc-praxis/main --allow-unrelated-histories --no-commit
```

### Merges cleanly (no overlap)

- 30 skill directories (zero name collisions with soredium's 3)
- Most of `scripts/` (different scripts — cc-praxis has validators + utils; soredium has garden tooling)
- `scripts/utils/` and `scripts/validation/` (cc-praxis only)
- `docs/adr/`, `docs/specs/`, `docs/development/` (cc-praxis only)
- `docs/archive/` (cc-praxis only — legacy material: old implementation plans, known issues, archived marketplace v1, archived superpowers docs)
- `docs/superpowers/plans/` (soredium only)
- `docs/superpowers/specs/` — different files in each, no index file, no collision
- `adr/`, `bin/`, `hooks/` (cc-praxis only)
- `registry/`, `known_rejections.yaml` (soredium only)
- `.githooks/commit-msg` (cc-praxis only)
- `.githooks/pre-push` — **identical in both repos**, auto-merges
- `QUALITY.md` (cc-praxis only — QA framework; referenced 11× in CLAUDE.md; scope audit needed in merged CLAUDE.md to cover garden tooling alongside skill validators)
- `RELEASE.md` (cc-praxis only)
- `PHILOSOPHY.md`, `DESIGN.md`, `logo.svg` (cc-praxis only)

### Conflicts (semantic merge required)

| File | Nature of conflict | Resolution approach |
|------|--------------------|---------------------|
| `CLAUDE.md` | Completely different project identities, workflows, checklists | Write new unified version (see §3) |
| `README.md` | Different narratives | Write functional merged README (landing page redesign is out of scope) |
| `.claude-plugin/marketplace.json` | Different plugin lists + structure | Merge plugin arrays, update metadata (see §3) |
| `scripts/claude-skill` | cc-praxis is superset (74 lines hook management), different URLs | Semantic merge: take cc-praxis code + update all Hortora/soredium URLs (see §3) |
| `.gitignore` | Different entries | Union of both |
| `docs/protocols/INDEX.md` | Both have INDEX.md with different protocol entries | Merge: combine entries from both (cc-praxis: 4 protocols, soredium: 1) |
| `tests/test_base.py` | cc-praxis (69 lines) includes soredium's base classes plus cc-praxis-specific severity helpers that reference `ValidationIssue` from `scripts/validation/`. Soredium tests don't use these helpers. Compatibility is one-directional — cc-praxis version works for all tests; soredium version would not support cc-praxis validator tests. | Take cc-praxis version |
| `tests/test_claude_skill.py` | Different test suites for diverged scripts/claude-skill | Semantic merge: combine both test suites, update for merged claude-skill |
| `pytest.ini` | cc-praxis has one, soredium doesn't | Take cc-praxis version |
| `requirements.txt` | cc-praxis has one (requests, pytest, PyYAML), soredium doesn't | Take cc-praxis version, add soredium's deps (sentence-transformers, numpy, mcp) |

### Files to remove post-merge

cc-praxis's Jekyll site moves to hortora.github.io. These files are removed from the merged repo after blog posts are copied:

- `docs/_config.yml`
- `docs/_layouts/` (default.html, post.html)
- `docs/_posts/` (17 posts + INDEX.md — posts copied to hortora.github.io first; INDEX.md is redundant once posts are in the hortora Jekyll site and is not preserved)
- `docs/Gemfile`
- `docs/articles/` (index.html — Jekyll site page)
- `docs/blog/`
- `docs/guide.html`
- `docs/images/` (if blog-only)
- `docs/visuals/`
- `docs/web-installer-mockup.html`
- `.github/workflows/pages.yml`

## 3. Semantic merge details

### CLAUDE.md

The merged CLAUDE.md combines both projects' conventions. Soredium's current CLAUDE.md is the starting baseline but is incomplete — it lacks engine/ documentation entirely. cc-praxis's CLAUDE.md is substantially more detailed (skills architecture, checklists, quality framework). The merge is additive, not a union of equals.

- **Project identity** → Hortora/soredium, `type: skills`
- **Repository purpose** → workflow skills + garden skills + garden tooling + engine
- **Skills architecture** → cc-praxis's detailed frontmatter/CSO/chaining docs (superset of soredium's)
- **Developer workflow** → merge both command sets:
  - Skill commands: sync-local, validate_all, generate_commands, etc.
  - Garden commands: validate_pr, integrate_entry, run_pipeline, validate_schema, init_garden, validate_garden
  - Engine commands: Maven build, test, dev mode
  - Registry management: project_registry.py, rejection_registry.py, candidate_report.py, etc.
- **"Working in engine/" section** — Maven commands, Java 21, Quarkus patterns, note that java-dev skill applies. Fills the pre-existing documentation gap in soredium's CLAUDE.md.
- **Work tracking** → Hortora/soredium
- **Pre-commit checklist** → cc-praxis's (more comprehensive)
- **Quality Assurance Framework** → cc-praxis's, with scope audit: QUALITY.md references need reviewing to cover garden tooling alongside skill validators
- **Garden-specific sections** → soredium's migration status, protocols, ecosystem pipeline
- **Registry and known_rejections.yaml** → documented in developer workflow
- **Drop** → all `mdproctor/cc-praxis` references, cc-praxis blog section, cc-praxis GitHub Pages references

### marketplace.json

```json
{
  "name": "soredium",
  "description": "Development workflow + knowledge garden skills for Claude Code",
  "owner": {
    "name": "Hortora",
    "url": "https://github.com/Hortora"
  },
  "plugins": [
    // 28 from cc-praxis (unchanged)
    // + forage, harvest (from soredium)
    // + protocol (newly added — was missing from soredium marketplace)
  ]
}
```

Drop the `bundles` concept. One flat plugin list.

### scripts/claude-skill

Semantic merge, not file swap:
- Take cc-praxis's code (superset: has hook management — 74 additional lines)
- Update `MARKETPLACE_URL` → `https://raw.githubusercontent.com/Hortora/soredium/main/.claude-plugin/marketplace.json`
- Update description string → Hortora/soredium
- Merge both `test_claude_skill.py` test suites — verify merged tests pass against merged script

### docs/protocols/INDEX.md

Merge entries from both repos:
- cc-praxis: 4 protocols (externalised-scripts-require-tests, taxonomy-rename-idempotent-script, taxonomy-values-reflect-content-character, write-content-three-layer-taxonomy)
- soredium: 1 protocol (validate-schema-vs-validate-pr)
- Individual protocol .md files have no collisions — only INDEX.md conflicts

## 4. Blog migration

**17 posts** from cc-praxis `docs/_posts/` → hortora.github.io `_posts/`.

(`docs/_posts/INDEX.md` is a navigation index, not a Jekyll post — it is not migrated.)

### Frontmatter compatibility

The two sites use different frontmatter schemas:

| Field | cc-praxis | hortora |
|-------|-----------|---------|
| `layout` | `post` | `post` (same) |
| `title` | ✅ | ✅ |
| `date` | ✅ | ✅ |
| `type` | ✅ (e.g. "day-zero") | ✅ (e.g. "origin") |
| `entry` | ❌ not used | sequential number |
| `entry_type` | ✅ (e.g. "note") | ❌ not used |
| `subtype` | ✅ (e.g. "diary") | ❌ not used |
| `projects` | ✅ (e.g. ["cc-praxis"]) | ❌ not used |
| `excerpt` | ❌ not used | ✅ |

### The entry number problem

The hortora blog listing page (`blog/index.html` line 84) renders `{{ post.entry }}` unconditionally inside a `div.entry-num` styled at `font-size: 2rem`. cc-praxis posts lack `entry:` in their frontmatter. This produces 17 blank 2rem-tall divs in the listing — visually broken, with discontinuous numbering.

The post layout (`_layouts/post.html`) has a `{% if page.entry %}` guard and handles missing entry gracefully. Only the listing page breaks.

**Decision: global renumbering.** All 41 posts (24 hortora + 17 cc-praxis) get sequential `entry:` numbers ordered by date. This is the right design because:

- The diary is one diary now, not two interleaved series
- Entry numbers are not in URLs (permalink uses title slug) — no external references break
- No end users to migrate (point 5 of design principles)
- Adding a `{% if %}` guard to the listing page would produce a visually incoherent mix of numbered and unnumbered entries — that's a workaround, not a design

Hortora's current state is worse than just gaps: entry 20 is missing, AND 3 of 24 hortora posts already lack `entry:` entirely (nits-and-a-design-call, engine-arrives, phase-2-unblocked). The renumbering fixes the gap, the missing entries, and the cc-praxis posts in one pass.

**Same-date tiebreaker:** Posts heavily interleave chronologically — 4 dates have entries from both projects (2026-04-07: 4 posts, 2026-04-09: 2, 2026-04-14: 4, 2026-05-21: 3). Since `date:` in frontmatter has no time component, the renumbering script needs a deterministic rule. **Tiebreaker: sort by filename (alphabetical).** This is stable, reproducible, and requires no judgment calls. On same-date collisions, the `mdpNN-` prefix in filenames provides natural ordering.

**Mechanical operation:** sort all 41 posts by `date:` then filename, assign `entry: "01"` through `entry: "41"`, update frontmatter. One-time script.

### Other frontmatter fields

- `entry_type`, `subtype`, `projects` — cc-praxis-only metadata not rendered by the hortora layout. Keep as-is. Harmless, historically accurate.
- `projects: ["cc-praxis"]` stays as historical fact. Future entries will use whatever convention evolves.

### URL and baseurl

- cc-praxis used `baseurl: "/cc-praxis"`. hortora uses `baseurl: ""`.
- 1 of 17 posts contains a hardcoded `/cc-praxis/` URL reference → fix it.
- Permalink structure is identical: `/blog/:year/:month/:day/:title/`

### Body text references

All 17 cc-praxis posts reference "cc-praxis" in their body text — headings like "# cc-praxis — Day Zero" and prose like "cc-praxis had 285 commits." These are historical diary entries written when the project had that name. They are not rewritten. This is intentional: the posts are a record of what happened, not a living document. An implementer encountering "cc-praxis" in migrated post bodies should not flag them as missed references.

### Layout

The hortora post layout is a superset of cc-praxis's (same structure, more polished CSS with CSS variables, handles both schemas). No layout changes needed.

## 5. Reference sweep strategy

70 files in cc-praxis reference "cc-praxis". Post-merge, these need triaging:

### Category 1: Must change (14 files) — GitHub URL `mdproctor/cc-praxis`
These affect install instructions, marketplace fetches, link resolution. All become `Hortora/soredium`.

**Silent-failure callout: config-architecture.md fetch.** Three files contain `raw.githubusercontent.com/mdproctor/cc-praxis/main/docs/config-architecture.md`:
1. `update-claude-md/SKILL.md` line 52 — `GENERIC_URL` constant used for daily refresh of `~/.claude/config-architecture.md`
2. `tests/test_config_architecture_refresh.py` line 18 — test constant
3. `docs/config-architecture.md` line 3 — source self-reference

The update-claude-md skill fetches this URL daily. Archived repos still serve raw content on GitHub, so this won't break immediately. But if the repo is ever deleted, the daily refresh silently stops working with no error — unlike a broken install command which fails visibly. These are Category 1 (must-change) but warrant priority treatment during the sweep.

### Category 2: Should change — project identity references
CLAUDE.md, README.md, marketplace.json (handled in semantic merges above). SKILL.md files that reference "this repository" or "cc-praxis" as the project name.

### Category 3: Leave as-is — historical references in the merged repo
- Specs in `docs/specs/` — historical design documents
- ADRs in `docs/adr/` — decisions made in the cc-praxis context
- Old plans in `docs/superpowers/`
- `docs/archive/` — explicitly archived legacy material

### Category 4: Leave as-is — migrated content (not in merged repo)
The 17 blog posts migrated to hortora.github.io contain "cc-praxis" throughout their body text and titles. These are not in the merged soredium repo — the reference sweep on soredium won't find them, and they should not be flagged as missed. See §4 "Body text references."

**Strategy:** Mechanical `grep -rl "cc-praxis"` sweep post-merge on the soredium repo. For each file, categorise as 1 (must-change), 2 (should-change), or 3 (historical-leave). Apply changes in a single commit. Category 4 lives in a different repo and is documented, not swept.

## 6. Workspace transition

### Current state
- `~/claude/public/cc-praxis/` — workspace for cc-praxis (specs, plans, blog staging, handover)
- `~/claude/public/hortora/` — family workspace for the Hortora org (engine, spec, soredium, garden, hortora.github.io)

### Both workspaces need updating

**cc-praxis workspace (`~/claude/public/cc-praxis/`):**

Repurpose for soredium. This workspace has all the session history — specs, plans, handover, blog staging. Renaming is simpler than migrating artifacts.
- Update CLAUDE.md: `add-dir` → `~/claude/hortora/soredium`
- Update `proj/` symlink → `~/claude/hortora/soredium/`
- Update project identity references

**Hortora family workspace (`~/claude/public/hortora/`):**

This workspace's CLAUDE.md lists soredium as a member repo with `add-dir /Users/mdproctor/claude/hortora/soredium`. The path doesn't change, but soredium is now fundamentally different (33 skills + engine instead of 3 skills + engine). Update the member table description to reflect the merged scope.

### Other workspace changes
- `wksp/` symlink in soredium → updated to point at the workspace
- Pause stack (`.pause-stack`) → check for any paused branches referencing cc-praxis paths; fix if found
- Global `~/.claude/CLAUDE.md` and included files → update path references:
  - `~/.claude/working-style.md` lines 106–112: "Skill Edits — cc-praxis is the source of truth" section references `~/claude/cc-praxis/<skill>/SKILL.md`. Update to `~/claude/hortora/soredium/`
  - Any other `@`-included files referencing cc-praxis paths
- Memory files → update paths referencing cc-praxis

### Blog routing

No project-level or workspace-level `blog-routing.yaml` exists for soredium or hortora blog routing. The global `~/.claude/blog-routing.yaml` routes to `mdproctor.github.io` with rules for notes/articles — no hortora diary routing exists.

**Create** a soredium workspace-level `blog-routing.yaml`:

```yaml
version: 1

destinations:
  hortora-diary:
    type: git
    path: ~/claude/hortora/hortora.github.io/
    subdir: _posts/

defaults:
  destinations: [hortora-diary]

rules:
  - match:
      entry_type: note
      subtype: diary
    destinations: [hortora-diary]
```

This routes diary entries from the soredium workspace to hortora.github.io. The write-content skill's blog directory config also needs updating to point at the workspace's blog staging area.

## 7. Test suite integration

### Colliding files
- `test_base.py` — cc-praxis version (69 lines) includes soredium's two base classes (`TempDirTestCase`, `DualTempDirTestCase`) plus severity helpers (`is_critical`, `is_warning`, `is_note`) that reference `ValidationIssue` from `scripts/validation/`. Soredium tests don't use these helpers — compatibility is one-directional. The validator framework survives the merge (it's in `scripts/validation/`), so nothing breaks. **Take cc-praxis version.**
- `test_claude_skill.py` — different test suites for diverged claude-skill scripts. **Semantic merge:** combine both suites, update assertions for the merged script.

### Path compatibility
- `scripts/utils/` (5 modules) and `scripts/validation/` (19 validators) are cc-praxis-only. Tests import from `scripts.utils.common` etc. These paths survive the merge unchanged since the directory structure is preserved.
- No test imports reference `cc-praxis` by name in import paths.

### Combined requirements
Merged `requirements.txt`:
```
requests
pytest
PyYAML
sentence-transformers
numpy
mcp
```

`pytest.ini` → take cc-praxis version (soredium has none).

### Post-merge verification
Run `python3 -m pytest tests/ -v` on the merged repo. If any tests fail due to path assumptions or conflicting fixtures, fix in the merge commit.

## 8. Post-merge cleanup

1. Remove cc-praxis Jekyll site files from merged repo (listed in §2)
2. Remove `.github/workflows/pages.yml` (blog no longer in this repo)
3. Archive cc-praxis on GitHub
4. Update cc-praxis workspace CLAUDE.md (`add-dir` → soredium, project identity)
5. Update hortora family workspace CLAUDE.md (member table description)
6. Update `proj/` and `wksp/` symlinks
7. Run `sync-local` from soredium
8. Create soredium workspace `blog-routing.yaml` (see §6 — creation, not update)
9. Update write-content blog directory config
10. Update hooks (check_project_setup.sh)
11. Update global `~/.claude/CLAUDE.md` and included files — specifically `~/.claude/working-style.md` § "Skill Edits" which references `~/claude/cc-praxis/`
12. Update memory files referencing cc-praxis
13. Run reference sweep (§5)

## 9. Out of scope

- README landing page redesign (separate issue, post-merge)
- Renaming soredium
- Reorganising Hortora org repos
- Changing skill names
- Migrating external users (no external users — point 5 of design principles)
