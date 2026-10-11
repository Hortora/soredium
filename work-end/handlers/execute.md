# Execute Phase Handlers

## trajectory

After artifacts are promoted and before the branch is pushed. Non-blocking —
if this step fails or the user declines, the orchestrator continues.

1. Draft a one-line trajectory note for each completed issue.
2. Propose enrichment updates — assess how completed work shifts the
   strategic landscape for 2-3 sibling/related issues.
3. Present table for user confirmation. On YES:
   ```bash
   python3 scripts/enrichment.py trajectory --issue <N> --repo <REPO> --text "<note>" --branch <BRANCH>
   python3 scripts/enrichment.py upsert --issue <N> --repo <REPO> --readiness ready
   ```
4. Failure is non-blocking.

## squash

For each repo listed in REPOS: classify commits and write
`.squash-plan-<repo>.json`. Repos with existing plan files are
skipped (restart safety).

**Slot mode marker:** If in_slot=yes, the orchestrator writes the
.phase-a-complete marker mechanically after squash completes — the
LLM does not need to handle this.

## verify_recover

Verify returned VERIFIED=no. FAILURES= contains per-check failures as
`FAILURE_N=check_name: message`. ATTEMPT= shows the current attempt
number (max 3).

**Recovery actions by check name:**

| Check failure | Recovery action |
|--------------|-----------------|
| `project_merged` | `git rebase main` in the project repo, then `git checkout main && git merge <branch>` |
| `project_stamped` | `git checkout <branch> && git commit --allow-empty -m "chore: branch closed — landed as <SHA> on main"` |
| `project_pushed` | `git push origin main` |
| `workspace_merged` | Same as project_merged, in workspace |
| `workspace_pushed` | `git push origin main` in workspace |
| `project_on_main` | `git checkout main` in project |
| `workspace_on_main` | `git checkout main` in workspace |
| `issues_closed` | `gh issue close <N> --repo <repo>` |
| `canonical_sync_*` | `git -C <canonical> push origin main` or `git -C <clone> push local <branch>:main` |

**Cross-session scenario:** If another session already performed
squash/land/stamp, some checks may fail because cleanup steps (push,
checkout main) weren't completed. Run the recovery action for each
failing check. The verify script checks actual git state, not
session-local progress — fixing the git state is sufficient.

After 3 failed attempts, the orchestrator escalates to user_input
with CONTEXT=final-gate-exhausted instead of looping. At that point,
manual resolution is required — fix the issue, then pass
force_done=verify to continue.
