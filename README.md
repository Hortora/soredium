# Soredium

Development workflow and knowledge garden skills for Claude Code.

> A soredium is a lichen's dispersal unit: a self-contained bundle that carries everything needed to establish a new colony wherever it lands.

## Install

```bash
/plugin marketplace add github.com/Hortora/soredium
```

## What's Included

33 skills across seven categories.

### Lifecycle

| Skill | What it does |
|-------|-------------|
| `work` | Unified entry point — detects branch state and routes to start/end/pause/resume |
| `work-start` | Creates issue branches, scaffolds metadata, runs pre-checks |
| `work-end` | Closes branch, promotes artifacts, merges to main |
| `work-pause` | Commits WIP, pushes to pause stack, switches to main |
| `work-resume` | Restores a paused branch, rebases onto current main |
| `workspace-init` | One-time companion workspace setup (prompted by project-init hook) |

### Development

| Skill | What it does |
|-------|-------------|
| `java-dev` | Java/Quarkus — safety, concurrency, Vert.x event loop awareness |
| `ts-dev` | TypeScript/Node.js — strict mode, async patterns, testing |
| `python-dev` | Python — type hints, async, pytest |

### Quality

| Skill | What it does |
|-------|-------------|
| `code-review` | Routes to Java/TS/Python review with OWASP-aware escalation |
| `security-audit` | OWASP Top 10 audit, triggered by code-review or on demand |
| `project-health` | Correctness, completeness, consistency checks by project type |
| `project-refine` | Improvement opportunities — duplication, bloat, doc quality |

### Commits & Docs

| Skill | What it does |
|-------|-------------|
| `git-commit` | Conventional commits with project-type routing and doc sync |
| `git-squash` | Branch history compaction with review gate and backup |
| `update-claude-md` | CLAUDE.md sync on convention changes |
| `update-design` | ARC42STORIES.MD sync on architecture changes |
| `implementation-doc-sync` | Session-scoped doc sweep after implementation |
| `adr` | Architecture Decision Records (MADR format) |
| `idea-log` | Lightweight parking lot for undecided possibilities |

### Garden

| Skill | What it does |
|-------|-------------|
| `forage` | Session-time capture, search, and retrieval of technical knowledge |
| `harvest` | Dedicated deduplication and staleness review sessions |
| `protocol` | Project-level rules and conventions in `docs/protocols/` |

### Content

| Skill | What it does |
|-------|-------------|
| `write-content` | Universal content creation — diary, article, brief, tutorial |
| `publish-blog` | Routes blog entries to external git destinations |
| `handover` | End-of-session context preservation for next session |
| `design-snapshot` | Freeze and record current design state |

### Infrastructure

| Skill | What it does |
|-------|-------------|
| `project-init` | Project setup verification at session start |
| `issue-workflow` | GitHub issue tracking, epic planning, split detection |
| `retro-issues` | Retrospective mapping of git history to GitHub issues |
| `dependency-update` | Maven/npm/pip dependency management |
| `fix-ci` | Reproduce CI failures locally, root-cause, verify green |
| `ide-tooling` | IntelliJ MCP routing — rename, find-references, diagnostics |

## Garden Engine

Soredium includes the garden engine — validators, CI scripts, and an autonomous agent for managing Hortora knowledge gardens.

| Script | Purpose |
|--------|---------|
| `scripts/validate_pr.py` | Entry validation — fields, score, Jaccard duplicates, injection |
| `scripts/validate_garden.py` | Full garden structural validation and index consistency |
| `scripts/integrate_entry.py` | Updates all garden indexes after entry submission |
| `scripts/dedupe_scanner.py` | Semantic similarity scan across entry pairs |
| `scripts/init_garden.py` | Initializes canonical/child/peer gardens |
| `scripts/garden-agent-install.sh` | Installs the autonomous garden agent into a local clone |

## Developer Setup

```bash
git clone https://github.com/Hortora/soredium.git ~/soredium

# Install all skills from local source
python3 scripts/claude-skill sync-local --all -y

# Run tests
python3 -m pytest tests/ -v

# Run commit-tier validators
python3 scripts/validate_all.py --tier commit
```

After editing any skill, run `scripts/claude-skill sync-local -y` to push changes into `~/.claude/skills/`.

## Links

- [hortora.github.io](https://hortora.github.io) — project site
- [Hortora on GitHub](https://github.com/Hortora) — organisation
- [Hortora/garden](https://github.com/Hortora/garden) — root canonical garden
- [Hortora/spec](https://github.com/Hortora/spec) — open protocol specification

## License

Apache License 2.0 — see [LICENSE](LICENSE).
