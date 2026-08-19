---
name: code-review
description: >
  Use when the user says "review the code", "check these changes", "review
  this", "look at staged changes", or invokes /code-review. Also invoked
  automatically by git-commit skills if no review has been done this session.
  Applies to Java/Quarkus, TypeScript, and Python projects.
---

# Code Review

Reads the project type, then loads the appropriate language-specific
review checklist. Universal review principles apply to all types.

## Step 0 — Load universal principles

**Load `~/.hortora/garden/approaches/code-review.md`** before proceeding.
All review workflow steps and reporting formats are defined there.

## Severity Model

| Level | Meaning | Action |
|-------|---------|--------|
| **CRITICAL** | Will cause wrong behavior, data loss, or security vulnerability | Must fix before commit |
| **WARNING** | Could cause confusion, inconsistency, or maintenance burden | Should fix; defer to a GitHub issue if risky or out of scope |
| **NOTE** | Minor improvement, style preference, or best practice suggestion | Advisory — fix if straightforward, skip if not |

This model applies to code-review and security-audit consistently.

## Step 1 — Detect project type

```bash
python3 ~/.claude/skills/project/ctx.py
```

Read `PROJECT_TYPE` and `MATURITY_STAGE` from the output.

`PROJECT_TYPE` may be comma-separated (e.g. `java,ts`) for mixed-language repos.
`MATURITY_STAGE` is `pre-release` (default) or `released`.

If type is missing, `generic`, or the specific language is not in the type list,
inspect staged files:
- `.java` files or `pom.xml` changed → treat as containing `java`
- `.ts` / `.tsx` files changed → treat as containing `ts`
- `.py` files changed → treat as containing `python`

## Step 2 — Load language-specific checklist(s)

If PROJECT_TYPE contains a single language, load that checklist (current behavior).

If PROJECT_TYPE contains multiple languages (e.g., `java,ts`), determine which
languages appear in the staged files:

| Language | Checklist | File extensions |
|---|---|---|
| `java` | `~/.claude/skills/code-review/java.md` | `.java` |
| `ts` | `~/.claude/skills/code-review/typescript.md` | `.ts`, `.tsx` |
| `python` | `~/.claude/skills/code-review/python.md` | `.py` |

Load each applicable checklist and apply it to the relevant files. Present
findings grouped by language.

## Step 2b — Released-project constraints

If `MATURITY_STAGE=released`: read `~/.claude/skills/code-review/constraints-released.md`
and apply its checks to the staged diff.

If `MATURITY_STAGE=pre-release` (default): skip. Pre-release projects may rename,
delete, and restructure freely.

## Skill Chaining

**Invoked by:** `java-dev`, `ts-dev`, `python-dev` before committing;
`git-commit` (routes to java.md) when no review has been run this session;
`executing-plans` before final commit;
`work-end` — Step 3c, mandatory gate before artifact promotion

**Invokes:** `security-audit` for auth/payment/PII code (offered, not
automatic); `git-commit` after approval if user wants to commit

**Complements:**
- `branch-audit` — different scope. branch-audit is holistic branch-level
  review (four dimensions: conformance, coherence, structure, robustness).
  code-review is per-line checklist. Both run at work-end.
- `design-review` — different scope. design-review is multi-round adversarial
  review of design specs. This skill reviews code.

**Boundary with branch-audit:** code-review is a per-line checklist (safety,
types, async). branch-audit is holistic (did we build the right thing,
coherently, with good structure, robustly?).
