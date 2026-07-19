---
name: project
description: >
  Use when project setup needs to be verified or completed — invoked
  automatically at session start (via hook) and by work-start before
  any branch work begins. NOT invoked directly by users.
slash-command: false
---

# project

Normalised setup gateway. Both the session hook and `work-start` converge
here — so the entry point doesn't matter, every session hits the same
initialisation checks.

**Fast path:** if everything is already set up or previously declined, return
immediately with no output.

**Slow path:** detect what's missing, run setup steps in order, write decline
flags to CLAUDE.md when user says no so they are never asked again.

---

## IntelliJ MCP routing — always apply

Before any other check: if both `mcp__intellij-index__*` and `mcp__intellij__*` tools are
visible in this session, note this rule and apply it throughout the session:

- **`mcp__intellij-index__*`** — use for code navigation, file search, diagnostics, and
  opening projects. Pass `project_path` to auto-open any closed project. Never ask the user
  to open a project manually.
- **`mcp__intellij__*`** — use only for build/run, terminal, and formatting. Cannot open projects.

**When to use IntelliJ vs bash:**

| Activity | Use | Why |
|----------|-----|-----|
| Navigate code (find usages, trace calls, understand types) | IntelliJ (`ide_find_references`, `ide_search_text`, `ide_find_class`, `ide_call_hierarchy`) | Semantically correct — finds all usages, understands types, handles overloads |
| Edit code (add/replace methods, fields, properties) | IntelliJ (`ide_edit_member`, `ide_replace_member`, `ide_insert_member`) | Structural — works with members not line numbers, auto-reformats |
| Refactor (rename, move, delete) | IntelliJ (`ide_refactor_rename`, `ide_move_file`, `ide_refactor_safe_delete`) | Updates all references across the project — never use sed/Edit for renames |
| Verify (compile, diagnostics) | IntelliJ (`ide_build_project`, `ide_diagnostics`) | Catches errors immediately after edits |
| Code review | IntelliJ for navigation + Read/Edit for review notes | Semantic navigation to understand impact of changes |
| Quick exploratory lookup ("what does X do?") | Either — bash grep is fine for speed | No correctness requirement, just orientation |
| Config, markdown, non-code files | bash grep, Read, or Edit tool | IntelliJ indexes code, not all file types |

The default during implementation work is IntelliJ. Bash grep for source files during
implementation is a smell — if you reach for `grep` on `.java`/`.ts`/`.py` while building
or reviewing, switch to `ide_search_text` or `ide_find_references`.

**Subagent dispatch rule:** Subagents do not inherit skills or CLAUDE.md. When
dispatching subagents for code exploration or implementation, include IntelliJ
MCP tool instructions in the agent prompt explicitly — at minimum:
"Use `mcp__intellij-index__*` tools (`ide_find_references`, `ide_search_text`,
`ide_find_class`) for code navigation instead of bash grep/find."
Without this, subagents will always fall back to bash.

---

## Fast-path exit

Run this first. If all conditions are met, return immediately — do nothing else.

```bash
python3 ~/.claude/skills/project/ctx.py
```

If `CLAUDE_OK=yes` AND `WORKSPACE_OK=yes` AND `ISSUES_STATUS` is not `absent` → return silently.

---

## Checks (run in order when fast path does not exit)

### Check 1 — CLAUDE.md with project type

Read `CLAUDE_OK` and `PROJECT_TYPE` from the ctx.py output (already run in fast-path).

Also check whether the file exists at all:
```bash
[ -f "CLAUDE.md" ] && echo "exists" || echo "missing"
```

| State | Action |
|-------|--------|
| CLAUDE.md missing | Ask user for project type, create CLAUDE.md inline |
| CLAUDE.md exists, `CLAUDE_OK=no` | Ask user to choose type, insert `## Project Type` section |
| `CLAUDE_OK=yes` | ✅ Continue |

**Project type choices:** `skills` · `java` · `blog` · `custom` · `generic`

When creating: use the minimal template — project type declaration plus
build/test commands if detectable from the repo (pom.xml, package.json,
pyproject.toml). Do not pad with boilerplate.

After writing the type, ask:

> **Project maturity?**
> - **pre-release** (default) — bold changes welcome, no backward compat
> - **released** — has consumers, review skills check backward compat
>
> Enter choice (default: pre-release):

Write the stage into CLAUDE.md under the type:
```markdown
**Stage:** pre-release
```

CLAUDE.md creation is required. If the user refuses, hard stop — no other
check can run without a project type.

---

### Check 2 — Workspace

Read `WORKSPACE_OK` and `WORKSPACE_DECLINED` from the ctx.py output (already run in fast-path).

| State | Action |
|-------|--------|
| `WORKSPACE_OK=yes` (symlinks present or declined) | ✅ Continue |
| `WORKSPACE_DECLINED=yes` | ✅ Skip silently |
| `WORKSPACE_OK=no` and `WORKSPACE_DECLINED=no` | Offer (see below) |

**Offer:**

> **No workspace configured for this project.**
>
> A workspace keeps methodology artifacts (plans, specs, handovers, blog
> entries) separate from the project repo. Set one up now? **(YES / n)**

- **YES** → invoke `workspace-init`. It handles git hooks, ARC42STORIES.MD stub,
  work tracking as part of its own flow. Once complete,
  skip Check 3 — workspace-init already offered it.
- **n** → write `workspace: declined` to CLAUDE.md (see below), continue.

**Writing the decline flag:**

Add to CLAUDE.md under `## Project Type` (or append if section not found):

```
workspace: declined
```

This is a single-line property, not a section header. Place it directly
below the project type line:

```markdown
## Project Type

type: java
**Stage:** pre-release
workspace: declined
```

---

### Check 3 — Work Tracking

Skip if: workspace was just set up this session (workspace-init offered it),
or `Issue tracking: declined` is already in CLAUDE.md.

Read `ISSUES_STATUS` from the ctx.py output (already run in fast-path). Values: `enabled` | `declined` | `absent`.

| State | Action |
|-------|--------|
| `enabled` | ✅ Continue |
| `declined` | ✅ Skip silently |
| `absent` | Offer (see below) |

**Offer:**

> **No issue tracking configured.**
>
> Links every commit to a GitHub issue — enforces issue creation before
> coding, enables commit split detection, generates release notes.
> Set it up now? **(YES / n)**

- **YES** → invoke `issue-workflow` (Phase 0 runs automatically)
- **n** → write `Issue tracking: declined` into `## Work Tracking` in CLAUDE.md:

```markdown
## Work Tracking

Issue tracking: declined
```

---

## Return states

| Outcome | What happens next |
|---------|-------------------|
| Fast path — all set up or declined | Return silently |
| Setup completed | Return silently |
| Workspace declined — flag written | Return, caller continues without workspace |
| Issue tracking declined — flag written | Return silently |
| CLAUDE.md creation refused | Hard stop |

---

## Resetting a decline

If a user changes their mind:
- **Workspace:** remove `workspace: declined` from CLAUDE.md — project
  will offer again next session, or they can say "set up workspace"
- **Issue tracking:** change `Issue tracking: declined` to `Issue tracking: enabled`
  in `## Work Tracking`, or say "set up issue tracking" to invoke the skill directly

---

## Integration points

### Session hook (`check_project_setup.sh`)

Output at session start:

```
🔧 Invoke the project skill to verify this project is set up before proceeding.
```

### work-start

Invoke project as Step 0 before path resolution. Only continue once
project returns. If workspace was declined, proceed in single-repo mode.

---

## Common Pitfalls

| Mistake | Why It's Wrong | Fix |
|---------|----------------|-----|
| Skipping fast-path check | Runs prompts on every session even when set up | Always check all three conditions first |
| Not writing decline flag | User gets asked every session forever | Write to CLAUDE.md on every decline |
| Running Checks 3+4 after workspace-init | workspace-init already offered them | Skip if workspace-init ran this session |

---

## Skill Chaining

**Invoked by:**
- Session hook (`check_project_setup.sh`) — every session start
- `work-start` — Step 0, before path resolution

**Invokes:**
- `workspace-init` — if workspace missing and user accepts
- `issue-workflow` (Phase 0) — if issue tracking missing and user accepts

**Does not invoke:**
- Any branch or commit skill — setup only
