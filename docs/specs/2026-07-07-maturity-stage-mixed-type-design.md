# Project Maturity Stage + Mixed-Language Repos

**Date:** 2026-07-07
**Status:** Implemented (pending adversarial review)
**Focal issue:** Derived from skills ecosystem audit (C1, N11-N16, audit systemic patterns)

## Problem

Two gaps in the skills framework compound into a single constraint: projects
can only declare one language and get one set of behaviors, regardless of
their actual shape or maturity.

**1. No maturity signal.** Claude defaults to backward-compatibility
conservatism — suggesting deprecation shims, migration paths, and
compatibility layers. For a pre-release project with zero consumers, this
fights the developer. There is no per-project toggle; the conservatism is
baked into model behavior and reinforced by review skill prompts (particularly
design-review's final-review mode, which checks "production readiness"
unconditionally).

**2. Single-language assumption.** `PROJECT_TYPE` captures one token (`\S+`
regex). A Java+TypeScript project must pick one — the secondary language gets
generic fallback detection from file extensions rather than first-class
checklist coverage. Router skills (code-review, security-audit,
dependency-update, update-design, project-health) all do exact string matching
against a single value.

## Design

### Maturity Stage

A new field in CLAUDE.md's `## Project Type` section:

```markdown
## Project Type

**Type:** java
**Stage:** pre-release
```

**Values:**

| Stage | Meaning | Review behavior |
|-------|---------|-----------------|
| `pre-release` | No external consumers. Bold changes welcome. | No backward-compat checks. Rename, delete, restructure freely. No migration paths, no deprecation shims. |
| `released` | Has consumers depending on current behavior. | Breaking changes to public APIs, config keys, schemas, CLI flags, or serialization formats without a documented migration path are flagged. Public API removal without prior deprecation is CRITICAL. |

**Default:** `pre-release` when absent. Every existing project gets permissive
behavior without needing CLAUDE.md edits. Only projects that opt into `released`
get stricter checks.

**Why two values, not a gradient:** The constraint is binary — either someone
depends on your interfaces or they don't. A three-tier model (alpha/beta/stable)
creates ambiguity about which checks apply at each level. Two values means no
judgment calls: pre-release = no compat checks, released = compat checks.

### Constraint Content

When `MATURITY_STAGE=released`, review skills load a shared constraint file
(`code-review/constraints-released.md`) containing:

- **Backward compatibility checks** — API signatures, config keys, schemas,
  CLI flags, serialization formats, event contracts
- **Migration strategy requirements** — document the path, deprecate before
  removing, semver major bump for breaking changes
- **Deprecation rules** — mark with language-appropriate annotations, include
  replacement guidance, never remove in the same release

The file lives in `code-review/` because sync-local discovers skills by
SKILL.md presence. Other review skills reference the same installed path.

design-review's Python code (prompts.py) gets the stage via `--stage` flag
on review.py and injects backward-compat paragraphs into code-review and
final-review mode prompts when `released`. Pre-review and spec-review modes
do not use the stage — pre-review validates approach direction, spec-review
evaluates design quality, neither is concerned with backward compatibility
of the implementation. This is inline in the Python code, not loaded from
the constraint file — the Python orchestrator builds prompt strings directly.
This integration is already implemented: `_build_final_review_reviewer_prompt`
and `_build_code_review_reviewer_prompt` both accept `maturity_stage` and
conditionally include backward-compat checks.

### Mixed-Language Repos

The `Type:` field accepts comma-separated values:

```markdown
**Type:** java, ts
```

**Parsing (ctx.py):**

The regex changes from `(\S+)` (one token) to `(.+)` (full line). The
captured value is normalized: strip whitespace, remove spaces around commas.

- `type: java` → `PROJECT_TYPE=java` (unchanged)
- `type: java, ts` → `PROJECT_TYPE=java,ts`
- `**Type:** java,  ts` → `PROJECT_TYPE=java,ts`

**Router skill routing:**

All router skills change from exact-match (`PROJECT_TYPE == java`) to
contains-check (`java in PROJECT_TYPE`). The specific behavior per skill:

| Skill | Single type | Multiple types |
|-------|-------------|----------------|
| `code-review` | Load that language's checklist (unchanged) | Partition staged files by extension, load each applicable checklist, present findings grouped by language |
| `security-audit` | Same as code-review | Same partitioning pattern |
| `git-commit` | Route to language-specific workflow (e.g. java.md) | Use generic workflow — no single-language route dominates. Code-review is invoked by the generic workflow when user requests review, handling multi-type natively via partitioning. |
| `update-design` | Load that language's workflow | Load each applicable workflow in sequence. Each workflow sees predecessor changes (sequential execution means current file state). |
| `dependency-update` | Load that package manager's workflow | Load each applicable workflow (already works via file-marker fallback) |
| `project-health` | Load type-specific checks | Load and run checks for each type |

**Review partitioning (code-review, security-audit):**

When PROJECT_TYPE contains multiple languages and staged files span both:

1. Inspect staged file extensions
2. Partition: `.java` files get java.md checklist, `.ts`/`.tsx` files get
   typescript.md checklist
3. Run both checklists in a single pass
4. Present findings grouped by language

This is a single invocation, not two separate reviews. The checklists are
independent — no cross-language interaction in the review logic.

**git-commit special case:**

Mixed-type projects always use the generic commit workflow. The
language-specific commit workflows (java.md, custom.md) assume a single
dominant language and make assumptions about architecture docs, design
journal routing, and build verification that don't generalize to mixed
repos. The generic workflow delegates language-specific concerns to the
router skills (code-review, dependency-update) which handle multiple
languages natively.

### ctx.py Contract

ctx.py outputs two new/modified fields:

```
PROJECT_TYPE=java,ts    # comma-separated, no spaces; single value unchanged
MATURITY_STAGE=pre-release  # pre-release (default) or released
```

Both fields are gated behind `## Project Type` section presence. If the
section is absent, `PROJECT_TYPE=` (empty) and `MATURITY_STAGE=pre-release`.

### Setup Flow

**project skill (Check 1):** After type selection, prompts for stage.
Default is pre-release; user must explicitly choose `released`.

**git-commit/project-type-setup.md:** All templates include
`**Stage:** pre-release` after the Type line.

### What This Design Does NOT Do

- **No per-language stage.** Stage applies to the whole project, not
  per-language. A Java+TS project is either pre-release or released as a
  unit. Per-language staging (Java API released, TS frontend pre-release)
  is a future extension if needed.

- **No auto-detection of maturity.** The stage is declarative — the user
  sets it. No heuristic (npm publish history, Maven Central presence)
  determines it automatically. Auto-detection would be fragile and
  surprising.

- **Unknown stage values are treated as pre-release.** The parser accepts
  any string; consumer skills check `== "released"`. This is intentional
  fail-safe behavior — an invalid value never triggers backward-compat
  checks. No validation error is raised because the field is declarative
  and user-provided values should not be rejected at parse time.

- **project-health reads stage but does not gate checks on it.**
  project-health's Step 0 reads `MATURITY_STAGE` for consistency with other
  router skills, but no check category currently varies by stage. Future
  checks (CHANGELOG presence, deprecation annotation completeness) could
  consume it. Removing the read would create churn when those checks arrive.

- **No language auto-detection for the Type field.** The user declares
  which languages the project uses. File-extension detection remains as
  a fallback for `generic` projects, not as a replacement for explicit
  declaration.

- **No new project types.** `ts` and `python` are not added to the
  canonical five-type table (skills, java, blog, custom, generic). They
  remain valid values for router skill routing but are not commit-workflow
  project types. A TypeScript project declares `type: generic` or
  `type: ts` — both work because router skills accept them.

## Verification

- ctx.py tests: 73 total tests across 12 test classes, including:
  - `TestProjectType`: 8 tests covering single, multi-value, bold format, triple types
  - `TestMaturityStage`: 5 tests covering default, pre-release, released, bold format, no section
- ctx.py manual: `type: java, ts` → `PROJECT_TYPE=java,ts`, `MATURITY_STAGE=pre-release`
- sync-local: 46 skills sync (requesting-code-review deleted)
- commit-tier validators: `python3 scripts/validate_all.py --tier commit`
