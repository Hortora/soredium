# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

---

## Project Identity

**Name:** soredium
**GitHub:** [Hortora/soredium](https://github.com/Hortora/soredium)
**Marketplace:** `/plugin marketplace add github.com/Hortora/soredium`
**Status:** Phase 4 complete — `forage`, `harvest` deployed; CI live; ecosystem mining pipeline (registry, extractor, clustering, delta analysis, validation gate) shipped.

## Repository Purpose

Soredium is the skills, validators, and tooling repository for the [Hortora](https://hortora.github.io) knowledge garden system. It delivers Claude skills that Claude Code users install to interact with their local garden.

Named after the lichen's dispersal unit: a self-contained bundle that carries everything needed to establish a new colony wherever it lands.

## Project Type

**Type:** skills

---

## Migration Status

**Migration complete** (2026-04-12). `forage` and `harvest` are deployed and replace the legacy `garden` skill.

- All project CLAUDE.md files updated to reference `forage`/`harvest`
- Garden path is `~/.hortora/garden/` (env var: `HORTORA_GARDEN`)
- Legacy `garden` skill at `~/.claude/skills/garden/` is deprecated — kept in place until the `handover` skill in cc-praxis is updated to call forage SWEEP instead of garden sweep
- `harvest` processes submissions from both `forage` and legacy `garden` format (formats are identical)

---

## Skills in This Repository

| Skill | Status | Purpose |
|-------|--------|---------|
| `forage` | ✅ deployed | CAPTURE (GitHub mode + local mode), SWEEP, SEARCH, REVISE |
| `harvest` | ✅ deployed | MERGE (via integrate_entry.py), DEDUPE |

---

## Developer Workflow

```bash
# Sync skills to ~/.claude/skills/ (after any skill change)
echo "Y" | python3 scripts/claude-skill sync-local

# List installed skills
python3 scripts/claude-skill list

# Run the test suite
python3 -m pytest tests/ -v   # 826 tests

# Validate a garden entry locally (same as CI)
python3 scripts/validate_pr.py <entry_file> ${HORTORA_GARDEN:-~/.hortora/garden}

# Integrate an entry locally (updates indexes, commits — same as CI)
python3 scripts/integrate_entry.py <entry_file> ${HORTORA_GARDEN:-~/.hortora/garden}

# First-time garden clone (sparse blobless)
bash scripts/garden-setup.sh

# Ecosystem mining pipeline
python3 scripts/run_pipeline.py          # orchestrate: registry → extract → cluster → delta → report
python3 scripts/validate_candidates.py   # human validation gate (accept/reject/skip candidates)

# Registry management
# scripts/project_registry.py    — CRUD for monitored projects (registry/projects.yaml)
# scripts/rejection_registry.py  — suppress re-surfacing of rejected candidates (known_rejections.yaml)
# scripts/candidate_report.py    — JSON serialization for pipeline output
# scripts/pattern_entry.py       — GP-ID skeleton generator for accepted patterns
# scripts/feature_extractor.py   — regex-based structural fingerprinting
# scripts/cluster_pipeline.py    — cosine similarity clustering
# scripts/delta_analysis.py      — new abstractions between git tags
```

**Skill directory structure** (one per skill at repo root):
```
forage/
  SKILL.md         ← main workflow
  [reference.md]   ← optional heavy reference material
harvest/
  SKILL.md
```

**Sync rule:** Always edit skills here in `~/claude/hortora/soredium/`, then run `sync-local` to propagate. Never edit `~/.claude/skills/` directly.

---

## Skill Architecture

### Frontmatter Requirements

Every `SKILL.md` requires YAML frontmatter:

```yaml
---
name: skill-name
description: >
  Use when [specific triggering conditions].
---
```

The `description` is the CSO trigger — describes *when* to use, not *how*. Keep under 500 characters. Start with "Use when...".

### Skill Chaining

Skills explicitly reference each other:
- `forage` is invoked during session work (CAPTURE, SWEEP, SEARCH, REVISE)
- `harvest` is invoked in dedicated maintenance sessions (MERGE, DEDUPE)
- Both are user-invocable; neither auto-triggers the other

### Supporting Files

Heavy reference material goes in sibling `.md` files, referenced from `SKILL.md`:

```
forage/
  SKILL.md                 ← lean workflow (loads always)
  submission-formats.md    ← heavy format reference (loaded on demand)
```

---

## Commit Style

Standard conventional commits. No AI attribution in commit messages.

```
feat(forage): add CAPTURE workflow
fix(harvest): handle missing GARDEN.md counter
docs: update migration constraint in CLAUDE.md
```

---

## Work Tracking

**Issue tracking:** enabled
**GitHub repo:** Hortora/soredium
**Changelog:** GitHub Releases (run `gh release create --generate-notes` at milestones)

**Automatic behaviours (Claude follows these at all times in this project):**
- **Before implementation begins** — when the user says "implement", "start coding",
  "execute the plan", "let's build", or similar: check if an active issue or epic
  exists. If not, run issue-workflow Phase 1 to create one **before writing any code**.
- **Before writing any code** — check if an issue exists for what's about to be
  implemented. If not, draft one and assess epic placement (issue-workflow Phase 2)
  before starting. Also check if the work spans multiple concerns.
- **Before any commit** — run issue-workflow Phase 3 (via git-commit) to confirm
  issue linkage and check for split candidates. This is a fallback — the issue
  should already exist from before implementation began.
- **All commits should reference an issue** — `Refs #N` (ongoing) or `Closes #N` (done).
  If the user explicitly says to skip ("commit as is", "no issue"), ask once to confirm
  before proceeding — it must be a deliberate choice, not a default.
