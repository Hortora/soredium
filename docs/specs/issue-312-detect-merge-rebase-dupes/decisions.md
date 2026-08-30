## D1: Scope

**Choice:** Full scope — pre-merge gate (abort, not warn), mechanical reconciliation, standalone audit script, project-health integration
**Alternatives:**
- Detect and warn only — too weak, warnings get ignored, duplicates still created
- Gate + audit only — no mechanical recovery, user left to figure out reconciliation manually
**Rationale:** Duplicate commits are created silently and discovered only post-hoc. A warning doesn't prevent anything. The fix needs teeth: abort the merge, fix it automatically, and provide ongoing audit.
**Trade-offs:** More implementation work than a simple warning
**Sources:** Issue #312 body, slot 163 audit showing 29 duplicate pairs across 13 repos
**Exploration:** quick
**Status:** captured

## D2: Detection method

**Choice:** Message pre-filter + patch-id confirmation
**Alternatives:**
- Patch-id only — more precise but slower, scans all commits even when messages don't match
- Message only — fast but fragile for generic messages like "fix typo"
**Rationale:** Message matching is fast O(n) scan. Patch-id is expensive but definitive. Using message as a pre-filter gives speed, patch-id confirmation eliminates false positives.
**Trade-offs:** Slightly more complex than pure patch-id
**Sources:** git-patch-id(1), git-log --format='%s'
**Exploration:** quick
**Status:** captured

## D3: Reconciliation strategy

**Choice:** Rebase --skip duplicates — rebase local onto blessed, auto-skip commits whose patch-id already exists on blessed
**Alternatives:**
- Fast-forward only — only works when blessed is strictly ahead, fails when local has unique commits
- Reset to blessed — destructive, loses any unpushed local work
**Rationale:** Rebase --skip preserves local-only commits while eliminating duplicates. The duplicates are identified by patch-id match, so skipping is safe. If non-duplicate conflicts arise, abort and escalate.
**Trade-offs:** Rebase rewrites SHAs of non-duplicate local commits. Acceptable since we push with --force-with-lease immediately after.
**Sources:** branch_create.py _sync_repo() line 185, git-rebase --skip
**Exploration:** quick
**Status:** captured

## D4: Automation level

**Choice:** Auto-execute with report — reconcile automatically, print what was skipped
**Alternatives:**
- Confirm first — requires human presence during sync-main
- Separate command — most friction, gate aborts and user must run reconcile manually
**Rationale:** The gate already verified duplicates are real (patch-id match). Auto-reconciliation with reporting is safe. If the rebase fails for non-duplicate reasons, it aborts and escalates.
**Trade-offs:** Automated action on main branch without confirmation. Mitigated by patch-id verification (no false positives) and abort-on-unexpected-conflict.
**Sources:** branch_create.py sync_main() — already runs git rebase/merge without confirmation
**Exploration:** quick
**Status:** captured
