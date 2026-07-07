# Skills Ecosystem Audit Prompt

Paste this into a new session to run a comprehensive audit. Requires `ultrathink`.

---

## The prompt

```
ultrathink

Run a comprehensive audit of the soredium skills ecosystem. The skills live in
~/claude/hortora/soredium/ — each skill has a SKILL.md and often supporting
content files. There are ~47 skills total plus CLAUDE.md, using-superpowers
(the master orchestrator), and Python scripts that skills invoke.

The previous audit (docs/audit/2026-07-07-skills-ecosystem-audit.md) found 13
CRITICALs, 32 WARNINGs, and 38 NOTEs. Read it first to understand what was
found and ensure no regressions.

Dispatch 12 parallel research agents (Opus), one per dimension below. Each
agent must read every file in its scope IN FULL — no skimming. Report findings
as CRITICAL / WARNING / NOTE with the specific skill(s), file(s), line(s),
what the issue is, and a concrete example of how it could go wrong.

### Dimension 1: Cross-skill contradictions
Read ALL skills. For every instruction in skill A, check if any other skill
gives a conflicting instruction for the same scenario. Focus on: ordering
conflicts, gate conflicts, severity model conflicts, naming conflicts.

### Dimension 2: Workflow completeness and handoff gaps
Read: work, work-start, work-end, work-pause, work-resume, project,
workspace-init, using-superpowers. Check all state transitions, all handoff
points, all error paths. Does every state have a documented exit? Are there
dead ends?

### Dimension 3: Implementation process coherence
Read: brainstorming, writing-plans, executing-plans, subagent-driven-development,
dispatching-parallel-agents, using-git-worktrees, test-driven-development,
systematic-debugging. Check the full chain brainstorming → plans → execution.
Are process gates enforced? Are handoffs clear? Could an LLM loop?

### Dimension 4: Review/quality skills consistency
Read: code-review (+ all content files), security-audit (+ all content files),
receiving-code-review, requesting-code-review, verification-before-completion,
design-review. Check severity models, triggering overlaps, language routing,
review gates, deprecated-skill handling.

### Dimension 5: Dev skills and IntelliJ-first consistency
Read: java-dev, ts-dev, python-dev, ide-tooling, dependency-update (+ all
content files), fix-ci. Check every code navigation instruction — does it use
IntelliJ MCPs first? Are dev skills symmetric across languages? Build/test
command consistency?

### Dimension 6: Content/knowledge skills coherence
Read: write-content (+ all forms/), publish-blog, forage (+ submission-formats),
harvest, protocol, handover (+ reference), adr, idea-log, design-review,
update-design (+ content files), implementation-doc-sync. Check boundary clarity,
taxonomy consistency, path accuracy, category completeness.

### Dimension 7: Git-commit and issue workflow
Read: git-commit (+ java.md, custom.md), git-squash, update-claude-md,
issue-workflow, retro-issues, project-health (+ content files), project-refine,
writing-skills. Check routing, issue enforcement, skip tokens, commit safety,
no-AI-attribution consistency.

### Dimension 8: CSO quality, cross-references, structural patterns
Read the frontmatter of ALL 47 skills. Then read full Skill Chaining sections
of ALL skills. Check: descriptions start with "Use when", under 500 chars, no
workflow summaries, no triggering overlaps. All cross-references bidirectional
and pointing to real skills. All artifact-producing skills have Success Criteria.
All complex skills have Common Pitfalls tables.

### Dimension 9: Scenario simulation (NEW)
Walk through these 8 user scenarios step by step, tracing the exact skill chain
that would fire. At each step, read the skill that would execute and check
whether the LLM would know what to do next:

1. "Fix this bug" (on a feature branch, workspace configured)
2. "Let's build a new feature" (from main, no issue exists)
3. "I'm done for today" (mid-feature, branch not ready to close)
4. "Ship this branch" (feature complete, ready to merge)
5. "Review this code" (staged changes, Java project)
6. "Update the dependencies" (Java project with pom.xml)
7. "Start working" (fresh session, no branch, no workspace)
8. "Resume the paused work" (multiple paused branches)

For each scenario, report: which skills fire in what order, where handoffs
are unclear, where the LLM might pick the wrong skill, where it might stall.

### Dimension 10: Token efficiency and context pressure (NEW)
Read ALL skills measuring approximate line counts. Identify:
- Skills over 500 lines (context pressure risk)
- Content that gets loaded but never used in common paths
- Duplicated blocks across skills that could be deduplicated
- Skills that load garden/approach files — are those files current?
- Instructions that repeat what CLAUDE.md already says (token waste)
- Conditional content that loads unconditionally

Report which skills are the worst offenders and what could be trimmed.

### Dimension 11: Script and tooling alignment (NEW)
Read all Python scripts that skills reference:
- project/ctx.py
- git-commit/commit_exec.py
- work-end/branch_cleanup.py (or equivalent)
- Any other scripts referenced by skills

For each: does the skill accurately describe what the script does? Are there
script behaviors the skill doesn't account for? Are there script outputs the
skill doesn't use? Are there race conditions or failure modes the skill
doesn't handle?

### Dimension 12: CLAUDE.md accuracy (NEW)
Read CLAUDE.md in full. For every claim it makes about skills, verify against
the actual skill files:
- Key Skills section: are all listed skills real? Are descriptions accurate?
- Project Types table: does it match docs/PROJECT-TYPES.md?
- Developer Workflow commands: do they all work?
- Pre-Commit Checklist: does it match what git-commit actually enforces?
- Skill Architecture section: do naming conventions match reality?
- Work Tracking section: does it match issue-workflow's behavior?
- Cross-reference every skill name mentioned in CLAUDE.md against the
  actual skill directories.

After all agents report, synthesize into a single deduplicated report ordered
by severity. Group related findings. Identify systemic patterns. Write the
full report to docs/audit/YYYY-MM-DD-skills-ecosystem-audit.md with a
recommended fix order.
```
