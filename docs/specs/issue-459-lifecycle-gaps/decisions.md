# Decisions — #459 Lifecycle Gaps

## D1: Dangling plans — prevention + detection

**Choice:** Clear `branch:` field in `plan_manager.py advance()` AND add S15 corruption check in `corruption.py`
**Alternatives:**
- Clear only — no safety net for manual edits, crashes, or pre-fix plans
- Detection only — reactive, doesn't prevent the state from occurring
**Rationale:** Belt and suspenders. advance() prevents the common case; S15 catches anything that slips through.
**Trade-offs:** Two code paths to maintain instead of one, but both are small.
**Sources:** project/corruption.py (S5, S6 checks), work-slot/plan_manager.py advance(), issue #402
**Exploration:** quick
**Status:** captured

## D2: Zombie slots — relaxed skip + detection

**Choice:** Relax `_skip_multi_repo_partial_close` to not count current workspace's `.plan` AND add zombie slot detection in ctx.py
**Alternatives:**
- Skip relaxation only — doesn't catch zombies from other causes (user declining, mode filtering)
- Detection only — catches all zombies but doesn't fix the root ordering issue
**Rationale:** The `.plan` existence check fires before cleanup removes the plan — an ordering artifact, not real ongoing work. Detection catches edge cases.
**Trade-offs:** Skip relaxation changes a guard condition that protects against premature archival — must be scoped to only the current workspace's plan, not other repos' plans.
**Sources:** work-end/work_end_orchestrator.py:260 (_skip_multi_repo_partial_close), GE-20260821-e9c59e (worklog.db audit)
**Exploration:** quick
**Status:** captured

## D3: Publish parity — verification + pre-copy check

**Choice:** Add `verify-parity` subcommand to `blog_publish.py` AND pre-copy parity check
**Alternatives:**
- Verification only — catches drift but redundantly re-copies already-present entries
- Pre-copy only — prevents redundant work but doesn't verify post-publish state
**Rationale:** Per GE-20260813-556494, both write and read paths must verify. verify-parity is the correctness fix; pre-copy is the efficiency fix.
**Trade-offs:** Two new subcommands to maintain. verify-parity needs access to the routing config to know expected destinations per entry.
**Sources:** publish-blog/blog_publish.py, blog-routing.yaml, issue #452, GE-20260813-556494
**Exploration:** quick
**Status:** captured
