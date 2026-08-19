# Soredium

Development workflow and knowledge garden skills for Claude Code.

> A soredium is a lichen's dispersal unit: a self-contained bundle that carries everything needed to establish a new colony wherever it lands.

## Install

```bash
/plugin marketplace add github.com/Hortora/soredium
```

## What's Included

45 skills across nine categories.

### Lifecycle

| Skill | What it does |
|-------|-------------|
| `work` | Unified entry point — detects branch state, routes to start/continue/end/pause/resume/next |
| `work start` | Begins work — accepts 1..n issues or free text, auto-detects epics, builds `.plan` queue, scaffolds metadata |
| `work continue` | Keeps working on current branch — auto-loads HANDOFF.md, specs, plan state. Done-detection suggests next/end |
| `work end` | Closes branch — one command regardless of context (branch or slot). Promotes artifacts, merges to main |
| `work pause` | Commits WIP, pushes to pause stack, switches to main |
| `work resume` | Restores a paused branch from the pause stack, rebases onto current main |
| `brief` | Orientation summary — branch, issue, plan progress, recent commits, health status |
| `work-slot` | Parallel clone-based slots for multi-repo work — create, list, status, add-repo, remove-repo, archive |

### Design & Planning

| Skill | What it does |
|-------|-------------|
| `brainstorming` | Explores problem space before implementation — intent, requirements, design |
| `writing-plans` | Creates detailed implementation plans from specs |
| `executing-plans` | Executes plans in a separate session with review checkpoints |
| `subagent-driven-development` | Dispatches independent plan tasks to subagents |
| `dispatching-parallel-agents` | Concurrent investigation of 2+ independent tasks |

### Development

| Skill | What it does |
|-------|-------------|
| `java-dev` | Java/Quarkus — safety, concurrency, Vert.x event loop awareness |
| `ts-dev` | TypeScript/Node.js — strict mode, async patterns, testing |
| `python-dev` | Python — type hints, async, pytest |
| `test-driven-development` | Red-green-refactor discipline before implementation code |
| `systematic-debugging` | Root-cause investigation before proposing fixes |
| `fix-ci` | Reproduce CI failures locally, root-cause, verify green |

### Quality

| Skill | What it does |
|-------|-------------|
| `code-review` | Routes to Java/TS/Python review with OWASP-aware escalation |
| `branch-audit` | Holistic branch-level review — conformance, coherence, structure, robustness |
| `receiving-code-review` | Technical rigor when receiving review feedback |
| `security-audit` | OWASP Top 10 audit, triggered by branch-audit Robustness or on demand |
| `project-health` | Correctness, completeness, consistency checks by project type |
| `project-refine` | Improvement opportunities — duplication, bloat, doc quality |
| `design-review` | Multi-round adversarial review — spec-review, pre-review modes |

### Commits & Docs

| Skill | What it does |
|-------|-------------|
| `git-commit` | Conventional commits with project-type routing and doc sync |
| `git-squash` | Branch history compaction with review gate and backup |
| `quick-fix` | Land small changes on main via ephemeral branch — rescue for unpushed commits |
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
| `writing-skills` | Skill authoring, editing, evaluation, and optimization |

### Infrastructure

| Skill | What it does |
|-------|-------------|
| `project` | Project setup verification at session start |
| `using-superpowers` | Session-start skill routing and discipline enforcement |
| `issue-workflow` | GitHub issue tracking, epic planning, split detection |
| `retro-issues` | Retrospective mapping of git history to GitHub issues |
| `dependency-update` | Maven/npm/pip dependency management |
| `ide-tooling` | IntelliJ MCP routing — rename, find-references, diagnostics |
| `sync-local` | Sync installed skills from cloned repository (dev-only) |

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

## Worklog & Enrichment

Local work lifecycle tracking and enriched backlog for what-next recommendations.

| Script | Purpose |
|--------|---------|
| `scripts/worklog.py` | Cross-repo work lifecycle tracking (SQLite) |
| `scripts/enrichment.py` | Issue enrichment, GitHub cache, what-next queries (CLI) |
| `scripts/worklog_mcp_server.py` | MCP server exposing worklog queries |
| `scripts/query_worklog.py` | Audit tool for inspecting worklog state |

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
