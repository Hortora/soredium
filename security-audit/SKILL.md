---
name: security-audit
description: >
  Use when user explicitly requests "security review", "audit security", "check
  for vulnerabilities", or "OWASP check", or when code-review identifies
  auth/payment/PII code needing a security pass. NOT automatic — must be
  explicitly requested or offered by code-review. Applies to Java/Quarkus,
  TypeScript, and Python projects.
---

# Security Audit

Reads project type, then loads the language-specific audit checklist.

## Step 0 — Load universal principles

**Load `~/.hortora/garden/approaches/security-audit.md`** before proceeding.

## Step 1 — Detect project type

```bash
python3 ~/.claude/skills/project/ctx.py
```

Read `PROJECT_TYPE` and `MATURITY_STAGE` from the output.

`PROJECT_TYPE` may be comma-separated (e.g. `java,ts`) for mixed-language repos.
`MATURITY_STAGE` is `pre-release` (default) or `released`.

If type is missing, `generic`, or the specific language is not in the type list,
inspect staged files and project structure to determine applicable languages.

## Step 2 — Load language-specific checklist(s)

If PROJECT_TYPE contains a single language, load that checklist.

If PROJECT_TYPE contains multiple languages (e.g., `java,ts`), determine which
languages appear in the audit scope:

| Language | Checklist | File extensions |
|---|---|---|
| `java` | `~/.claude/skills/security-audit/java.md` | `.java` |
| `ts` | `~/.claude/skills/security-audit/typescript.md` | `.ts`, `.tsx` |
| `python` | `~/.claude/skills/security-audit/python.md` | `.py` |

Load each applicable checklist and apply it to the relevant files. Present
findings grouped by language.

## Step 2b — Released-project constraints

If `MATURITY_STAGE=released`: read `~/.claude/skills/code-review/constraints-released.md`
(shared with code-review) and apply its checks to the audit scope.

If `MATURITY_STAGE=pre-release` (default): skip. Pre-release projects may rename,
delete, and restructure freely.

## Skill Chaining

**Invoked by:** [`code-review`] when auth/payment/PII code is identified; user explicit request

**Does NOT invoke:** other skills automatically — findings are reported only
