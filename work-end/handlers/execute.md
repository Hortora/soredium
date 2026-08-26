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

Verify returned VERIFIED=no. Present per-check failures from FAILURES=.
Offer recovery: re-run the failing Execute sub-step, then re-run verify.
