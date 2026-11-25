# ADR-0018: Kill Promotion — Workspace Is Ephemeral

- **Status:** Accepted
- **Date:** 2026-11-25

## Context

The workspace was designed as a companion git repo holding methodology
artifacts (blogs, specs, plans, journal, handoff) separate from the
project repo. Durable artifacts (blogs, specs) were written to the
workspace first, then "promoted" to the project repo during the close
ceremony via `artifact_promote.py`.

After six months of production use, promotion has proven too fragile:

- Blog entries and specs are routinely lost or left unpromoted
- `sweep-gaps` was added as a post-ceremony catch-all — itself evidence
  of systemic fragility
- The close ceremony gates on unpromoted artifacts, blocking work-end
  when promotion state is inconsistent
- Users regularly have to manually check whether artifacts were promoted

Cloning the workspace into slots compounds the problem: inherited
lifecycle files (`.queue`, `.plan`, `HANDOFF.md`, `JOURNAL.md`) conflict
on rebase, requiring `_strip_inherited_lifecycle`, `.queue-root` markers,
and alignment checks between workspace and project branches.

## Decision

**Promotion is eliminated.** Two principles replace it:

1. **Durable artifacts route directly to the project repo at write time.**
   Blogs go to `docs/blog/`, specs to `docs/specs/`, ADRs to `docs/adr/`
   — on the working branch, committed immediately. `resolve_artifact_dir.py`
   returns the project-side path. There is no intermediate copy.

2. **Everything in the workspace is ephemeral.** Plans, scratch specs,
   journal entries, handoff notes — none of it survives beyond the work
   item. If it matters permanently, it was written to the project repo
   in the first place. The workspace is a scratchpad, not an archive.

**Publishing is unchanged.** `blog-routing.yaml` and `publish-blog`
push committed content to external repos (GitHub Pages, etc.). Publishing
operates on content already in the project repo. It is orthogonal to
where content was initially written.

## Consequences

### What dies

- `artifact_promote.py` — all subcommands (`to-project`, `to-workspace-main`, `sweep-gaps`, `archive-plans`)
- Close ceremony promotion gate (`unpromoted_artifacts()`, `promotion_backlog()`)
- `_copromote_images()` at promotion time (images commit alongside their document at write time)
- Workspace directories for durable content (`blog/`, `specs/`, `adr/` created by `workspace-init`)
- Workspace cloning into slots (ephemeral content doesn't need git history)
- `_strip_inherited_lifecycle` and `.queue-root` routing (nothing to inherit)
- Workspace alignment checks (no workspace branch to align)
- Workspace landing in close ceremony

### What changes

- `resolve_artifact_dir.py` — returns project-side paths (`docs/blog/`, `docs/specs/`)
- `write-content` — writes blogs to project repo directly
- `brainstorming` — writes specs to project repo directly
- `workspace-init` — creates only ephemeral directories (plans)
- Slots — no workspace clone needed; ephemeral state can be a plain directory

### What stays

- Publishing routing (`blog-routing.yaml`, `publish-blog`, `canonical_sync.py publish`)
- The queue at the slot/canonical root (already moved out of workspace by #577)
- Project repo as the single source of truth for all durable artifacts

### Risks

- Specs written to the project branch create noise in diffs during code
  review. Mitigated: specs are already reviewed separately via
  `design-review`, and reviewers can filter by path.
- Workspace-optional users who want specs in a throwaway location can
  still use the workspace — but those specs are explicitly ephemeral.
