# /issue-workflow

**Aliases:** none

Configure GitHub issue tracking with automatic behaviors throughout the development lifecycle.

## Usage

```
/issue-workflow
```

## What it does

Runs Phase 0: Setup — creates labels, installs commit-msg hook, writes Work Tracking section to CLAUDE.md, and optionally maps past git history to issues via /retro-issues.

## When to use

- Setting up a new project for issue tracking
- Adding issue tracking to an existing project
- Re-creating labels after they were deleted from GitHub
- Installing the commit-msg hook on a new machine

## Automatic invocation

Once Work Tracking is enabled in CLAUDE.md, Claude automatically:
- Creates epics and child issues before implementation (Phase 1)
- Drafts issues for significant tasks before code is written (Phase 2)
- Confirms issue linkage before commits and detects split candidates (Phase 3)

## Examples

```
/issue-workflow
```

Then follow the interactive prompts to configure issue tracking.

## Related commands

- `/retro-issues` — map git history to epics and issues retrospectively
