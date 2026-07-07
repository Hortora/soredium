# soredium — Skills Architecture

> For installation and getting started: [README.md](../README.md) · For the full skill catalog: [skills-catalog.md](skills-catalog.md)

---

## Skills Architecture

This collection follows a **layered architecture** where foundation skills provide universal principles, and specialized skills extend them for specific languages, frameworks, and workflows.

### Layer 1: Commit Workflow (1 router skill)

**Pattern:** Router → Content Files

| Skill | Purpose | Project Types |
|-------|---------|---------------|
| **git-commit** | Entry point, routes to `java.md`, `blog.md`, `custom.md` based on project type | all |

### Layer 2: Documentation Sync (3 skills)

**Pattern:** Document Type Specialists

| Skill | Document | Project Types | Auto-Invoked By |
|-------|----------|---------------|-----------------|
| **update-claude-md** | CLAUDE.md (workflows) | all | git-commit |
| **update-design** | ARC42STORIES.MD (java) / User-configured doc (custom) | java, custom | git-commit |
| **readme-sync.md** | README.md (skill catalog) | skills | git-commit |

### Layer 3: Review (2 skills)

**Pattern:** Router → Language-Specific Content Files

| Skill | Reviews | Auto-Invoked By | Blocks On |
|-------|---------|-----------------|-----------|
| **code-review** | Code quality (routes to `java.md`, `typescript.md`, `python.md`) | git-commit | CRITICAL findings |
| **security-audit** | OWASP Top 10 (routes to `java.md`, `typescript.md`, `python.md`) | code-review | Security vulnerabilities |

**Note:** SKILL.md validation for type: skills repositories is handled by the skill-validation.md workflow (not a portable skill), automatically invoked by git-commit when SKILL.md files are staged.

### Layer 4: Principles (4 skills)

**Pattern:** Universal Foundations (Referenced, Not Invoked)

| Skill | Domain | Extended By |
|-------|--------|-------------|
| **code-review-principles** | Universal code review | code-review (java.md, typescript.md, python.md) |
| **security-audit-principles** | Universal OWASP Top 10 | security-audit (`java.md`, `typescript.md`, `python.md`) |
| **dependency-management-principles** | Universal BOM patterns | dependency-update (`maven.md`, `npm.md`, `pip.md`) |
| **observability-principles** | Universal logging/tracing/metrics | quarkus-observability |

### Layer 5: Java/Quarkus Development (4 skills)

**Pattern:** Layered Specialization

| Skill | Purpose | Builds On |
|-------|---------|-----------|
| **java-dev** | Java development foundation | (base layer) |
| **quarkus-flow-dev** | Quarkus Flow workflows | java-dev |
| **quarkus-flow-testing** | Workflow testing | java-dev, quarkus-flow-dev |
| **quarkus-observability** | Quarkus observability config | observability-principles |

### Layer 6: Utilities (9 skills)

| Skill | Purpose | Builds On |
|-------|---------|-----------|
| **dependency-update** | BOM management (routes to `maven.md`, `npm.md`, `pip.md`) | dependency-management-principles |
| **adr** | Architecture Decision Records | (standalone) |
| **design-snapshot** | Immutable dated design state record | (standalone) |
| **idea-log** | Living log for undecided possibilities | (standalone) |
| **write-blog** | Living project diary — decisions, pivots, and discoveries in the moment | (standalone) |
| **publish-blog** | Routes blog entries to external git destinations via blog-routing.yaml | write-blog |
| **forage** | Cross-project library of hard-won bugs, gotchas, and unexpected behaviours. Session-time: CAPTURE, SWEEP, SEARCH, REVISE. Dedup via harvest. | (standalone, writes to ~/.hortora/garden/) |

### Layer 7: Health & Quality (8 skills)

| Skill | Purpose | Builds On |
|-------|---------|-----------|
| **project-health** | Universal correctness and consistency checks | (standalone) |
| **project-refine** | Improvement opportunities and bloat reduction | (standalone) |
| **skills-project-health** | Skills repo health checks | project-health |
| **java-project-health** | Java project health checks | project-health |
| **blog-project-health** | Blog project health checks | project-health |
| **custom-project-health** | Custom project health checks | project-health |
| **project-health** | Routes to `typescript.md`, `python.md`, `java.md`, `skills-repo.md`, `blog.md`, `custom.md` | (standalone router) |

### Layer 8: TypeScript/Node.js Development (1 skill)

| Skill | Purpose | Builds On |
|-------|---------|-----------|
| **ts-dev** | TypeScript development guidance | (standalone) |

**Note:** TypeScript code review, security audit, and dependency management are handled by the `code-review`, `security-audit`, and `dependency-update` router skills via their `typescript.md`/`npm.md` content files.

### Layer 9: Python Development (1 skill)

| Skill | Purpose | Builds On |
|-------|---------|-----------|
| **python-dev** | Python development guidance | (standalone) |

**Note:** Python code review, security audit, dependency management, and health checks are handled by the `code-review`, `security-audit`, `dependency-update`, and `project-health` router skills via their `python.md`/`pip.md` content files.

