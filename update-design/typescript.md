# Update Design Document — TypeScript / Node.js

Keeps `DESIGN.md` accurate as the TypeScript codebase evolves. Focuses on
API surface, module structure, and dependency changes — the things most likely
to drift from the document over time.

## Core Rules

- **Never apply changes without explicit user confirmation.**
- Focus on **architectural impact** only: new/removed modules, changed public
  APIs, new dependencies, refactored structure. Ignore implementation details.
- Keep prose concise. Prefer bullet points and tables over paragraphs.

## Workflow

### Step 1 — Locate DESIGN.md

```bash
ls DESIGN.md docs/DESIGN.md 2>/dev/null | head -1
```

If not found, offer to create a stub:
```markdown
# Design

## Overview
<brief description>

## Architecture
<module structure>

## Public API
<exported interfaces and functions>

## Dependencies
<key dependencies and why>
```

### Step 2 — Collect changes to analyse

In priority order:
1. **Staged changes**: `git diff --staged`
2. **Recent commit**: `git diff HEAD~1 HEAD`
3. **User-provided description or diff**

### Step 3 — Identify architectural impact

Map changes to DESIGN.md sections:

| Change | Section to update |
|--------|------------------|
| New exported function/class/interface | Public API |
| New `src/` module or directory | Architecture |
| Removed export | Public API (mark removed) |
| New `package.json` dependency | Dependencies |
| Removed dependency | Dependencies |
| `tsconfig.json` target/lib change | Architecture |
| New environment variable | Configuration (create if absent) |

**Skip:** internal refactors, test changes, formatting, comment updates, implementation details that don't affect public contracts.

### Step 4 — Propose updates

For each affected section, show the proposed change in diff format:

```
## Public API

+ ### `createUser(input: UserInput): Promise<User>`
+ Creates a new user record. Throws `ValidationError` if input is invalid.
```

Then ask:
> "Does this look right? Reply YES to apply, or tell me what to adjust."

### Step 5 — Apply on YES

Write the updated DESIGN.md. Confirm:
> "✅ DESIGN.md updated."

## Common Pitfalls

| Mistake | Fix |
|---------|-----|
| Documenting internal helpers | Only document exported symbols |
| Copying type signatures verbatim | Write intent, not syntax — the code already has the types |
| Skipping removed exports | Deletions matter as much as additions |
| Updating DESIGN.md without reading it first | Always read the current state before proposing changes |

## Edge Cases

| Situation | Action |
|-----------|--------|
| No staged changes and no diff provided | Run `git log --oneline -5`, ask which to analyse |
| DESIGN.md has no matching section | Propose a new section rather than silently skipping |
| Large diffs (50+ files) | Summarise themes rather than file-by-file; confirm scope first |
