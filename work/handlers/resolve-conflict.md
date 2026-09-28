# Handler: resolve_conflict

Rebase produced conflicts that couldn't be auto-resolved. Tier 2 — LLM semantic resolution.

1. Read `FILES` (comma-separated conflicted source files) and `AUTO_RESOLVED` from the ACTION output
2. If `AUTO_RESOLVED` is non-empty, report: "Auto-resolved lifecycle files: <list>"
3. For each remaining file in `FILES`:
   - Read the conflicted file
   - Resolve the conflict (imports, non-overlapping edits, obvious merges)
   - Stage the resolution: `git add <file>`
4. If all resolved, continue the rebase: `git rebase --continue`
5. Call the orchestrator with:
   ```
   step_done=resolve_conflict conflict_resolved=yes
   ```
6. If unable to resolve:
   - Inform the user which files need manual resolution
   - The pipeline will yield `ACTION=user_input` (Tier 3)
