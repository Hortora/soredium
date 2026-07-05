# Fit-Gap Analysis: obra/superpowers → soredium Integration

**Date:** 2026-07-05
**Issue:** Hortora/soredium#77
**Scope:** 13 skills (14th — finishing-a-development-branch — audited in #74)

## Verdict

**No unintentional drops.** All removed content is either a brand rename,
intentional simplification (moved to CLAUDE.md or folded into Skill Chaining),
or platform-specific content removed by design (Codex/Pi/Antigravity).

## Drop Classification

| Category | Count | Examples |
|----------|-------|---------|
| Brand rename | ~30 | `superpowers:` → bare names, `.superpowers/` → `.hortora/`, `docs/superpowers/` → `docs/` |
| Content → CLAUDE.md | ~8 | writing-skills SDO, naming, frontmatter, directory structure, flowchart conventions |
| Redundancy removal | ~6 | SDD example workflow, dispatching "Key Benefits"/"Real-World Impact", executing-plans "REQUIRED SUB-SKILL" labels |
| Platform removal | 4 | using-superpowers Codex/Pi/Antigravity references + 3 reference files |
| Folded into Skill Chaining | ~4 | SDD Integration section, executing-plans Integration section, requesting-code-review Integration subsections |

## Behavioral Additions (rewrite-only)

| Addition | Skills affected |
|----------|----------------|
| forage SEARCH/CAPTURE bookending | systematic-debugging, brainstorming |
| protocol SEARCH integration | receiving-code-review, brainstorming |
| IDE structural editing (ide_insert_member, ide_replace_member) | TDD, VBC, SDD, writing-plans, brainstorming, systematic-debugging |
| TDD + VBC quality gates in execution | SDD, executing-plans |
| Debugging toolkit concept (3 skills linked) | systematic-debugging, dispatching-parallel-agents, fix-ci |
| Process Skills and Their Gates table | using-superpowers |
| Lifecycle Integration (session hooks) | using-superpowers |
| Distinction sections (vs similar skills) | requesting-code-review (vs code-review), using-git-worktrees (vs workspace-init) |
| Focal issue / Issue group in plans | writing-plans |
| Automated validation (`validate_all.py`) | writing-skills |
| Graphviz DOT → Mermaid | all skills with diagrams |

## Behavioral Changes (intent shifted)

| Change | Skill | Original | Rewrite |
|--------|-------|----------|---------|
| Dispatch threshold | dispatching-parallel-agents | 3+ test files failing | 2+ independent problems |
| End-of-work skill | SDD, executing-plans | `finishing-a-development-branch` | `work-end` |
| Execution discipline | executing-plans | "Follow each step exactly" | Mandates TDD + ide-tooling + VBC per task |
| VBC gate | SDD | review-approved → task-done | review-approved → VBC → task-done |
| Context gathering | brainstorming | "check files, docs, commits" | forage SEARCH + protocol SEARCH + .meta |
| Deployment model | writing-skills | "push to fork, consider contributing" | "run sync-local" |
| Standalone vs DRY | writing-skills | Self-contained (all rules inline) | Pointers to CLAUDE.md (not standalone) |

## Per-Skill Summary

| Skill | Preserved | Simplified | Dropped | Added | Verdict |
|-------|-----------|------------|---------|-------|---------|
| brainstorming | 12 | 3 | 1 (elements-of-style ref) | 6 | clean |
| writing-plans | 8 | 1 | 2 (worktree ref, labels) | 5 | clean |
| using-superpowers | 4 | 0 | 4 (platform refs) | 3 | clean |
| writing-skills | 6 | 5 | 7 (all → CLAUDE.md) | 3 | clean |
| systematic-debugging | 7 | 1 | 0 | 6 | clean |
| dispatching-parallel-agents | 5 | 2 | 2 (benefits, impact) | 4 | clean |
| SDD | 8 | 1 | 3 (example, advantages, cost) | 5 | clean |
| executing-plans | 4 | 1 | 2 (platform pitch, worktree) | 4 | clean |
| fix-ci | — | — | — | entire skill | new (soredium-only) |
| TDD | 9 | 4 | 1 (TS examples) | 5 | clean |
| VBC | 7 | 0 | 0 | 4 | clean |
| receiving-code-review | 9 | 1 | 1 (real examples) | 5 | clean |
| requesting-code-review | 4 | 1 | 1 (integration section) | 4 | clean |
| using-git-worktrees | 6 | 2 | 1 (common mistakes) | 2 | clean |

## Supporting Files

All supporting files preserved:
- systematic-debugging: root-cause-tracing.md, defense-in-depth.md, condition-based-waiting.md, condition-based-waiting-example.ts, find-polluter.sh
- brainstorming: visual-companion.md, spec-document-reviewer-prompt.md, scripts/ (5 files)
- writing-plans: plan-document-reviewer-prompt.md
- SDD: implementer-prompt.md, task-reviewer-prompt.md, scripts/ (3 files)
- requesting-code-review: code-reviewer.md
- writing-skills: anthropic-best-practices.md, persuasion-principles.md, testing-skills-with-subagents.md, examples/

Format changes only: Graphviz DOT → Mermaid in root-cause-tracing.md and condition-based-waiting.md.
