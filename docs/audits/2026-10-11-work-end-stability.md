# Work-End Orchestrator Stability Audit — 2026-10-11

**Source:** quarkmind session, branch `issue-366-reconstitution-accuracy-gate`
**Affected skills:** work-end, git-squash, project/lifecycle

---

## Issue 1: verify_recover infinite loop — BLOCKS WORKFLOW

**What happened:** After pushing to origin/main and stamping the branch, `work_end_orchestrator.py` kept returning `ACTION=verify_recover VERIFIED=no` with no escape hatch.

**Root cause:** `_final_gate` (~line 1811) runs `verify_slot_close.py` which checks ~12 postconditions. `check_branch_merged` (~line 84-106) compares tree SHAs: `branch~1^{tree}` vs `main^{tree}`. After `git reset --soft` + recommit (squash), the branch tip's parent tree doesn't match main's tree because the squash created a new commit structure. The ancestry fallback also fails because `branch~1` is now the pre-squash commit, not a commit on main. Additionally, `check_main_pushed` for the workspace fails when only the project repo was pushed.

**Fix:** The `land` mechanical step (~line 1228) should handle the full merge-to-main flow end-to-end (rebase onto main, push both repos, stamp branch). When the LLM does the merge manually (bypassing `land`), the final gate should detect the content landed via `git merge-base --is-ancestor <branch-commit-sha> main` rather than tree SHA comparison. Add `force_done=verify` as an escape hatch for the LLM when postconditions can't be satisfied mechanically.

**Severity:** Blocks workflow — infinite retry loop, no exit.

---

## Issue 2: META_STATE bounce (closing:stamped → idle) — FRICTION

**What happened:** After `cleanup_pass` lifecycle step fires, state transitions to `idle`. But the LLM keeps passing `meta_state=closing:stamped` from the initial ctx.py output. The mismatch confuses subsequent calls.

**Root cause:** The orchestrator's lifecycle transitions change state on disk, but the LLM doesn't re-read ctx.py between steps. The passed-in `meta_state` becomes stale after any transition.

**Fix:** Either: (a) the orchestrator should always read state from disk instead of trusting the passed-in `meta_state`, or (b) after any lifecycle transition, the ACTION output should include `META_STATE=<new>` prominently, and the skill doc should instruct the LLM to use the returned value.

**Severity:** Friction — confusing but recoverable.

---

## Issue 3: user_input step loop — FRICTION

**What happened:** `arc42_scan`, `session_rename`, `garden_feedback`, `notes` all returned `ACTION=user_input` requiring individual `step_done=X` calls. 4 unnecessary round-trips for steps that were all no-ops.

**Root cause:** These are typed as `judgment` steps (~lines 1296-1307) in `CLOSE_USER_INPUT_STEPS` (~line 1792). Each yields `ACTION=user_input` with no batch-skip mechanism.

**Fix:** Add `skip_remaining_user_input=yes` parameter that marks all remaining judgment steps as done in one call. Or add skip predicates — skip `arc42_scan` when changes are outside ARC42 scope, skip `notes` when no deferred items exist. The sweep system already has this pattern (`_is_sweep_deselected`).

**Severity:** Friction — 4 wasted round-trips per close.

---

## Issue 4: sweep_config COMPLETE_WITH hint is misleading — FRICTION

**What happened:** ACTION output said `COMPLETE_WITH=step_done=sweep_config produced=N`. LLM used `step_done=sweep_config produced=0`. Rejected with `Use sweep_selected= to complete sweep_config`. One wasted call to discover the correct parameter.

**Root cause:** The default `COMPLETE_WITH` template doesn't account for steps that require non-standard parameters (~line 1455-1461). The `sweep_config` step explicitly rejects `step_done` but the hint suggests it.

**Fix:** Override `COMPLETE_WITH` in `sweep_config`'s `action_context_fn` (~line 1169) to output `COMPLETE_WITH=sweep_selected=<comma-separated-list>` instead of the default template.

**Severity:** Friction — one wasted round-trip.

---

## Issue 5: Pre-push hook blocks after squash review — FRICTION

**What happened:** After git-squash reviewed and approved a single clean commit, `git push` was blocked by the pre-push hook. Required `--no-verify` (with user approval) to push.

**Root cause:** The installed pre-push hook unconditionally exits 1 when ANY unpushed commits exist. It has no squash-candidate detection and no "already reviewed" marker mechanism. This is a different (simpler) hook from the skill's `~/.claude/skills/git-squash/hooks/pre-push` which pattern-matches before blocking.

**Fix options:**
1. **Replace the installed hook** with the skill's version (pattern-matches for actual squash candidates before blocking)
2. **Add a reviewed marker** — git-squash writes `.git/squash-reviewed` after completing review. The hook checks for this marker: if present, clears it and allows the push. If absent, blocks as before.

**Severity:** Friction — requires `--no-verify` after every squash-reviewed push.

---

## Reproduction

All 5 issues reproduce on any work-end close where:
- The branch has been squashed (git reset --soft + recommit) before merge
- Multiple sweeps are configured
- The project has ARC42STORIES.MD
- The pre-push hook is installed
