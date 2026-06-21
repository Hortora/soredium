# Update Design Document — Python

Keeps `ARC42STORIES.MD` accurate as the Python codebase evolves. Focuses on
public API surface, module structure, and dependency changes.

## Core Rules

- **Never apply changes without explicit user confirmation.**
- Focus on **architectural impact** only: new/removed modules, changed public
  APIs, new dependencies, structural changes. Ignore implementation details.
- Keep prose concise. Prefer bullet points and tables over paragraphs.

## Workflow

### Step 1 — Locate ARC42STORIES.MD

```bash
ls ARC42STORIES.MD docs/ARC42STORIES.MD 2>/dev/null | head -1
```

If not found, offer to create a stub:
```markdown
# Design

## Overview
<brief description>

## Architecture
<package/module structure>

## Public API
<exported classes, functions, and CLI commands>

## Dependencies
<key dependencies and why>
```

### Step 2 — Collect changes to analyse

In priority order:
1. **Staged changes**: `git diff --staged`
2. **Recent commit**: `git diff HEAD~1 HEAD`
3. **User-provided description or diff**

### Step 3 — Identify architectural impact

Map changes to ARC42STORIES.MD sections:

| Change | Section to update |
|--------|------------------|
| New public class or function (no leading `_`) | Public API |
| New package directory with `__init__.py` | Architecture |
| Removed public symbol | Public API (mark removed) |
| New `pyproject.toml` / `requirements.txt` dependency | Dependencies |
| Removed dependency | Dependencies |
| New CLI command or entry point | Public API |
| New environment variable | Configuration (create if absent) |
| Python version requirement change | Architecture |

**Skip:** private functions/classes (leading `_`), test changes, docstring updates, formatting, internal refactors with no public impact.

### Step 4 — Propose updates

For each affected section, show the proposed change in diff format:

```
## Public API

+ ### `create_user(name: str, email: str) -> User`
+ Creates a new user. Raises `ValidationError` if email is malformed.
```

Then ask:
> "Does this look right? Reply YES to apply, or tell me what to adjust."

### Step 5 — Apply on YES

Write the updated ARC42STORIES.MD. Confirm:
> "✅ ARC42STORIES.MD updated."

## Common Pitfalls

| Mistake | Fix |
|---------|-----|
| Documenting private functions | Only document public API (no leading `_`) |
| Copying type hints verbatim | Write intent, not syntax — the code already has the types |
| Skipping removed exports | Deletions matter as much as additions |
| Updating ARC42STORIES.MD without reading it first | Always read the current state before proposing changes |

## Edge Cases

| Situation | Action |
|-----------|--------|
| No staged changes and no diff provided | Run `git log --oneline -5`, ask which to analyse |
| ARC42STORIES.MD has no matching section | Propose a new section rather than silently skipping |
| Large diffs (50+ files) | Summarise themes rather than file-by-file; confirm scope first |
| Multiple packages in monorepo | Ask which package's ARC42STORIES.MD to update, or update all if global change |
