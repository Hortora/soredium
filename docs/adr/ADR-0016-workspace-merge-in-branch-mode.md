# ADR-0016: Workspace Merge Strategy in Branch Mode

**Status:** proposed
**Date:** 2026-09-03
**Issue:** #326

## Context

When work-end closes a branch, `land_flow.py` merges the project repo to main but skips the workspace repo entirely (stamp only). This causes lifecycle files (`.plan`, `JOURNAL.md`, `.execute-progress`, etc.) to leak onto workspace main when the LLM manually merges to satisfy `verify_slot_close.py`, which expects `workspace_merged: pass`.

This bug has been fixed **four times** and keeps returning because each fix addressed a symptom, not the structural cause.

### History of Fix Attempts

| Commit | Approach | Outcome |
|--------|----------|---------|
| `1fc1b9f` | Strip scaffold during merge | Fragile timing |
| `12b7d89` | New commit instead of amend | Amend wasn't the issue |
| `fcaad94` | Strip before merge, not after | Race between strip and merge |
| `36afaf1` | Add HANDOFF.md to strip list | Whack-a-mole on file list |
| `a070ac8` | **Stop merging workspace entirely** | Introduced verify contradiction |

After four failed strip attempts, `a070ac8` ("selective promotion via worktree — workspace branch no longer merged") pivoted to stamp-only. This avoided scaffold stripping but created the current verify/LLM contradiction loop.

### The Structural Issue

`land_flow.py` has blanket `if desc.is_workspace: continue` guards in preflight, rebase, and merge+push. These were designed for **slot mode** (TWO_HOP transport) where workspace clones are destroyed after slot archive. But `build_branch_batch()` creates workspace descriptors with `transport=Transport.DIRECT` — a persistent repo. The skip guards don't distinguish transport type.

The verify → LLM manual merge → lifecycle file leak → corruption chain has been the dominant failure mode since `a070ac8`.

## Decision

Merge DIRECT workspace repos to main during `land_batch()`, with atomic post-merge lifecycle file cleanup. Keep stamp-only for TWO_HOP workspace repos (slot mode).

### Key Design Choices

1. **Cleanup is inside `land_flow.py`**, between merge and push — not in a separate script at a different lifecycle point. This is what all previous attempts got wrong.

2. **Definitive lifecycle file list** maintained in one place:
   ```
   .plan, JOURNAL.md, .execute-progress, .land-ledger.jsonl,
   .artifacts-promoted, .close-progress, .close-report.json,
   .close-log.jsonl, .wrap-log.jsonl
   ```

3. **Transport type distinguishes slot vs branch**: `TWO_HOP` = slot (stamp only), `DIRECT` = branch (merge + cleanup).

4. **Merge strategy**: try ff-only first; fall back to regular merge for workspace repos since they aren't rebased.

## Consequences

- Workspace main accumulates design history (specs, plans, decisions) — discoverable without knowing branch names
- Lifecycle files never reach workspace main — corruption detection doesn't fire spuriously
- `verify_slot_close.py` passes without LLM intervention
- `cleanup_scaffold` becomes a defensive second pass (idempotent, still useful)
- Slot mode behavior unchanged

## If This Breaks Again

Read this ADR. The failure pattern is always: lifecycle files on workspace main → `ctx.py` corruption detection → confused routing. Check:

1. Is the lifecycle file list in `land_flow.py` missing a new file? Add it.
2. Did someone add a new `if desc.is_workspace: continue` guard? It needs `and desc.transport == Transport.TWO_HOP`.
3. Is the cleanup running before push? If not, push delivered lifecycle files to remote.
