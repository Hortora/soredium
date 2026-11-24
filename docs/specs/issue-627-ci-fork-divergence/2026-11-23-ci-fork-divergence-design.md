# CI Fork Divergence — mirror() Detection and CI Action Fix

**Issue:** Hortora/soredium#627
**Date:** 2026-11-23
**Status:** Design

## Problem

`canonical_sync.py mirror()` pushes canonical's base branch to the fork remote
after every publish. When the fork has commits that canonical doesn't (created by
a CI action running independently on both origin and fork), the push is
non-fast-forward. `mirror()` returns `"failed"` with no diagnosis, and the
publish flow logs a misleading warning: "catches up on the next publish." It
never catches up. The gap accumulates silently.

### Root Cause

GitHub Actions CI on both casehubio/* (origin) and mdproctor/* (fork) runs an
"API docs regeneration" action that commits directly to main. Because it runs
independently on both remotes, it creates parallel commits with the same content
but different SHAs, breaking the canonical-is-sync-point invariant.

### Current State (2026-11-23)

| Repo | Fork behind origin | Cause |
|------|--------------------|-------|
| engine | 27 commits | CI commit on fork diverged ~Nov 20 |
| eidos | 1 commit | Same CI pattern |
| agency | 0 | In sync |

## Architecture Invariant

Canonical (`~/claude/casehub/*`) is the single sync point. All work lands there
first. Canonical's base branch is then pushed to both origin (casehubio, the
blessed remote) and fork (mdproctor, the mirror). Since both remotes only ever
receive from canonical, pushes are always fast-forward when this model holds.

Force-push is never acceptable as normal operation — it is emergency behaviour
only. The `+` refspec in `_stage_on_fork()` is for the disposable
`publish/<base>` staging branch, not a precedent for force-pushing to fork/main.

## Design

Two fixes, both in this issue:

### Fix 1: CI Action — Prevent Divergence

Scope the "API docs regeneration" GitHub Action so it does not commit on forks.
The action runs on casehubio/* repos; on mdproctor/* repos it should either not
run at all or run without committing.

**Implementation:** Add a condition to the workflow that checks whether the repo
is a fork before committing:

```yaml
# In the regeneration step:
if: github.repository_owner == 'casehubio'
```

This gates the commit step, not the entire workflow — the action can still run
on forks for validation, it just doesn't push commits.

**Repos to update:** engine, eidos (agency is in sync, check if it has the same
action).

### Fix 2: mirror() — Fetch, Diagnose, Report

Change `mirror()` from a blind push to a fetch-then-push with failure diagnosis.

**Current mirror() (line 553-559):**
```python
def mirror(canon: Canonical) -> str:
    """Push canonical's base branch to the mirror. Returns the remote, 'none' or 'failed'."""
    if not canon.mirror:
        return "none"
    result = git(canon.repo, "push", "-q", canon.mirror,
                 f"refs/heads/{canon.base}:refs/heads/{canon.base}", timeout=_NETWORK_TIMEOUT)
    return canon.mirror if result.returncode == 0 else "failed"
```

**New mirror():**

1. If no mirror remote, return `"none"` (unchanged)
2. Fetch the mirror remote's base branch
3. Compare: is canonical/base an ancestor of mirror/base, vice versa, or neither?
4. If canonical is ahead or equal: plain push (fast-forward guaranteed)
5. If mirror is ahead: this shouldn't happen in the model — warn that the fork
   has commits canonical doesn't, list the specific commits
6. If diverged: warn with the fork's unique commits and canonical's unique
   commits since the merge base
7. If fetch fails: network/auth error, report as such (not "diverged")

**Return value change:** `mirror()` keeps returning `str`. Values expand from
`{remote, "none", "failed"}` to `{remote, "none", "diverged", "failed"}`.
`"diverged"` is a new value meaning the fork has commits canonical doesn't.
`PublishResult.mirrored` stays `str`. Diagnostic detail goes into
`PublishResult.warnings` (the existing pattern for mirror failures).

**Warning message changes:**

| Current | New |
|---------|-----|
| `"catches up on the next publish"` | `"fork has diverged: N commit(s) on fork/main not in canonical; manual resolution needed"` |

When status is `"diverged"`, the warning includes the first 5 divergent commit
subjects from the fork (one line each) so the user can see what they are without
running git commands.

### One-Time Manual Recovery

The existing divergence on engine and eidos is cleared by the user manually
force-pushing the fork to match origin. This is outside the tooling — a
deliberate, understood action.

```bash
git -C ~/claude/casehub/engine push fork +refs/remotes/origin/main:refs/heads/main
git -C ~/claude/casehub/eidos push fork +refs/remotes/origin/main:refs/heads/main
```

## Testing

1. **Existing test `test_mirror_failure_warns_and_the_publish_stands`** (line
   639): Update to verify `mirrored == "failed"` still works for unreachable
   remotes, and that publish still succeeds.

2. **New test: `test_mirror_diagnoses_divergence`**: Create a fork remote with
   an independent commit, verify `mirror()` returns `"diverged"` and
   `publish_base()` includes a warning naming the fork's unique commits.

3. **New test: `test_mirror_succeeds_when_canonical_is_ahead`**: Normal case —
   canonical has commits the fork doesn't, push is fast-forward, returns the
   remote name.

4. **New test: `test_mirror_reports_network_failure`**: Fork remote URL is
   unreachable, verify returns `"failed"` (not "diverged").

## Scope

| In scope | Out of scope |
|----------|-------------|
| `mirror()` fetch + diagnose | Auto-recovery (force-push, rebase) |
| Warning message accuracy | Changing `_stage_on_fork` behaviour |
| CI action gating on forks | Reworking the publish flow |
| One-time manual recovery docs | New dataclasses or return type changes |
| Tests for the new behaviour | |

## References

- project/canonical_sync.py:553 — current `mirror()` implementation
- project/canonical_sync.py:681 — `_stage_on_fork()` with `+` refspec
- project/canonical_sync.py:331 — `settle_base()` as fetch-then-diagnose pattern
- project/canonical_sync.py:134 — `locate()` remote convention
- project/canonical_sync.py:748-750 — misleading warning text
- tests/test_canonical_sync.py:639 — existing mirror failure test
- CLAUDE.md Landing Rules — canonical is the sync point, only canonical publishes
