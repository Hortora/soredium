## D1: Recovery strategy for mirror divergence

**Choice:** Maintain the canonical-is-sync-point invariant; never force-push
**Alternatives:**
- Force-push to fork on divergence — violates the linear-history model; force-push is emergency behaviour, not normal operation
- Rebase fork onto canonical — mathematically impossible without force-push (rebased commits have new SHAs, still non-fast-forward)
- Incorporate fork commits into canonical — pollutes the blessed remote with CI noise
**Rationale:** The canonical repo is the single sync point. Both origin (casehubio) and fork (mdproctor) only receive from canonical. When this model holds, pushes are always fast-forward. The fix is to restore and maintain the invariant (CI action fix), not to work around its violation.
**Trade-offs:** Existing divergence requires a one-time manual force-push by the user to clear. The tooling does not auto-recover — it detects and reports.
**Sources:** project/canonical_sync.py:553 (mirror()), project/canonical_sync.py:134 (locate()), CLAUDE.md Landing Rules
**Exploration:** quick
**Status:** captured

## D2: Scope — CI fix and mirror() improvements in one issue

**Choice:** Both the soredium mirror() detection improvements and the casehub CI action fix are covered by this issue
**Alternatives:**
- Separate issues — splits a cohesive fix across repos, risks one half being done without the other
**Rationale:** One without the other leaves the problem half-solved. The CI fix prevents recurrence; mirror() detection is defense-in-depth.
**Trade-offs:** Cross-repo work in a single issue; CI changes are in casehub GitHub Actions config, not soredium code
**Sources:** GitHub issue #627
**Exploration:** quick
**Status:** captured

## D3: Mirror failure diagnosis depth

**Choice:** Fetch fork/main before pushing; on failure, compare refs to classify diverged vs network/auth error; report specific divergent commits in warning
**Alternatives:**
- Classify from stderr only — no fetch, just parse `non-fast-forward` from git output. Cheaper but no commit-level detail
- Minimal warning fix — only change the misleading text, no classification at all
**Rationale:** When the invariant is violated, the user needs actionable information: which commits diverged and from where. A fetch to a remote we're already talking to (via _stage_on_fork) is cheap.
**Trade-offs:** One extra network roundtrip per mirror call. Negligible given _stage_on_fork already hits the same remote.
**Sources:** project/canonical_sync.py:553 (mirror()), project/canonical_sync.py:331 (settle_base() as pattern for fetch-then-diagnose)
**Exploration:** quick
**Status:** captured
