# Decisions — Unified Review and Findings Persistence

## D1: New branch-audit skill

**Choice:** Create a new `branch-audit` skill for holistic branch-level review
**Alternatives:**
- Extend `code-review` with `--mode branch-audit` — mixes two different review approaches (line-level vs holistic) in one skill
- Extend `design-review` with `--type code` — design-review is adversarial spec review; wrong execution model (external sessions, watchdog crons, ~/reviews/ workspaces) and no ADR/debate needed for code
- Implement design-review's planned post-implementation lifecycle point (review-tiers.md line 14) — same execution model problem; the post-implementation point was marked "future" precisely because the adversarial model doesn't fit a pre-merge gate
**Rationale:** Branch-level audit is a genuinely different kind of review from per-line checklist (code-review) and adversarial spec review (design-review). Clean separation of concerns. Fills the gap that design-review's post-implementation lifecycle point was planned to fill, with a simpler execution model.
**Trade-offs:** One more skill in the review space. Mitigated by removing two deprecated skills (D2, D3). design-review's review-tiers.md must be updated to point post-implementation to branch-audit.
**Sources:** work-end/SKILL.md, code-review/SKILL.md, design-review/SKILL.md, design-review/review-tiers.md (line 14)
**Exploration:** quick
**Depends on:** D6 (shared dimensions)
**Status:** captured
**Review:** R1-01 raised duplication with review-tiers.md planned lifecycle point. Accepted — added as alternative and updated rationale. Post-implementation in review-tiers.md will reference branch-audit.

## D2: Remove requesting-code-review

**Choice:** Remove the deprecated `requesting-code-review` skill entirely
**Alternatives:**
- Un-deprecate and evolve into branch-audit — name doesn't convey holistic audit, implementation is narrowly scoped (subagent dispatch template)
- Keep as backward-compat shim — dead code that misleads
**Rationale:** Deprecated, superseded by design-review --mode final-review (itself a poor fit). Gap now properly filled by branch-audit (D1).
**Trade-offs:** Skills referencing it need cross-reference updates. receiving-code-review references it in Skill Chaining — must update.
**Sources:** requesting-code-review/SKILL.md (deprecated notice at line 10)
**Exploration:** quick
**Status:** captured
**Review:** R1-12 noted receiving-code-review chain broken. Accepted — added to trade-offs.

## D3: Retire verification-before-completion as standalone skill

**Choice:** Retire VBC as a standalone skill. Preserve the "evidence before claims" principle as a protocol in `docs/protocols/`. Git-commit and executing-plans reference the protocol. The forcing function (D4) is additive — it handles finding resolution at work-end, but does NOT replace VBC's per-boundary evidence gate.
**Alternatives:**
- Keep VBC as standalone skill — referenced by 25 files, but it's a behavioral discipline, not a review skill with steps or artifacts
- Fold entirely into forcing function — WRONG: VBC is "run the command before claiming success" at every commit boundary. The forcing function is "resolve all findings before close." Different scopes.
**Rationale:** VBC's principle is important but doesn't need a standalone skill. A protocol preserves the principle while removing the skill overhead. The principle applies at every completion boundary (commits, tasks, PRs). The forcing function applies only at work-end. Both are needed.
**Trade-offs:** 25 files reference VBC and need updating to reference the protocol. The principle must not be lost — the protocol is the preservation mechanism.
**Sources:** verification-before-completion/SKILL.md
**Exploration:** quick
**Depends on:** D4 (forcing function is additive, not replacement)
**Status:** revised
**Review:** R1-03 caught scope conflation between VBC and forcing function. Accepted — revised to preserve VBC as protocol rather than folding into forcing function.

## D4: Forcing function at work-end only

**Choice:** Handover captures and persists findings; work-end forces resolution of all accumulated findings
**Alternatives:**
- Same forcing function at both gates — too strict for handover (session ending, work continues)
- No forcing function anywhere — findings accumulate indefinitely with no resolution pressure
**Rationale:** Handover is mid-work — forcing resolution would block session wrap for findings that can't be fixed yet. Work-end is branch close — all accumulated findings must be addressed before merging. "Fix, file as issue, or dismiss with reason" — no finding survives branch close unaddressed.
**Trade-offs:** Findings can accumulate across many sessions before being forced. Mitigated by work_health.py surfacing them at every session entry via check_prior_findings().
**Depends on:** D9 (findings.json as persistence format)
**Sources:** work-end/SKILL.md, handover/SKILL.md, blog 2026-08-17-mdp01, work-end/hygiene_scan.py, project/work_health.py
**Exploration:** quick
**Status:** captured

## D5: Move review early in work-end

**Choice:** Review becomes Step 2 (right after Context), before Sweep
**Alternatives:**
- Keep review in Step 3 (Execute) — current position; code review buried after forage, protocol, doc sync, write-content
**Rationale:** Finding bugs after spending 10+ minutes on knowledge capture and blog writing wastes time. Review first, then sweep. Bugs found early can be fixed before sweep captures the session narrative.
**Trade-offs:** Review operates without forage/protocol sweep context. For per-line code-review this is negligible (operates on git diff, not conversation context). For branch-audit's holistic dimensions, a gotcha surfaced by forage could explain unusual code patterns. Accepted trade-off: the cost of reviewing without sweep context is lower than the cost of sweeping before reviewing.
**Sources:** work-end/SKILL.md (current Step 3.1)
**Exploration:** quick
**Status:** revised
**Review:** R1-05 caught missing trade-off. Accepted — acknowledged sweep context loss.

## D6: Four shared review dimensions

**Choice:** Conformance, Coherence, Structure, Robustness — same vocabulary for design-review and branch-audit
**Alternatives:**
- Three dimensions (collapse Structure into Coherence) — loses decomposition as first-order concern for spec review
- Different dimensions per review type — vocabulary diverges, findings harder to compare across lifecycle
- Three shared + context-specific — avoids forcing Conformance where it doesn't fit, but breaks the "one vocabulary" benefit
**Rationale:** Structure asks "are boundaries right?" (decomposition). Coherence asks "does it hold together?" (composition). Opposite directions of the same concern — both deserve explicit attention. Conformance is always "did we build what we said we'd build?" — the reference document varies by context.
**Conformance by context:**
- Design-review post-implementation: code vs spec
- Branch-audit with spec: implementation vs spec
- Branch-audit with issue only: implementation vs issue description and acceptance criteria
- Branch-audit with neither: implementation vs stated intent (lightest — still checks "did we do what we said?")
**Trade-offs:** Four dimensions is more than three — slightly heavier per review. Structure will often have fewer findings for code reviews than spec reviews. Conformance varies in weight by context.
**Sources:** design-review/SKILL.md, design-review/review-tiers.md
**Exploration:** quick
**Status:** revised
**Review:** R1-06 caught Conformance undefined for code review. Accepted — added context-specific definitions.

## D7: Security-audit stays as deep-dive

**Choice:** Robustness dimension does surface-level security; escalates to security-audit for full OWASP pass
**Alternatives:**
- Fold security-audit into Robustness entirely — loses the deep OWASP checklist
- Keep security fully separate from Robustness — fragments the review
**Rationale:** Same pattern as current code-review ("offers security-audit for auth/PII code"). Surface-level security is part of every review. Full OWASP audit is opt-in when warranted.
**Trade-offs:** Two-tier security review could miss things if Robustness doesn't escalate when it should. Escalation triggers are LLM judgment (auth, PII, payment, user input code detected in diff), not structural gates.
**Sources:** security-audit/SKILL.md, code-review/SKILL.md
**Exploration:** quick
**Status:** captured

## D8: Loose ends sweep is first-class

**Choice:** Separate first-class concept — runs at every handover (capture + persist) and work-end (capture + force-resolve). Distinct from epic hygiene.
**Alternatives:**
- Fold into branch-audit as a dimension — loose ends are session state, not code quality; branch-audit reviews the diff, can't see "a review finding was deferred 3 hours ago"
- Fold into work-end only — misses capture at handover, losing accumulation across sessions
- Rename/extend epic hygiene — WRONG scope. Epic hygiene checks workspace/branch lifecycle state (branches closed, artifacts promoted, blogs published). Loose ends checks session/work state (deferred findings, skipped plan items, TODOs, unresolved items).
**Rationale:** Loose ends sweep and epic hygiene are different concerns sharing the same persistence mechanism (findings.json). Epic hygiene = are branches closed correctly? Loose ends = is work finished? Same pipe, different taps.
**Trade-offs:** One more concept to invoke at lifecycle gates. Mitigated by both handover and work-end orchestrating it as a standard step.
**Depends on:** D9 (findings.json as persistence format)
**Sources:** blog 2026-08-17-mdp01, blog 2026-08-17-mdp03, work-end/hygiene_scan.py, project/work_health.py, handover/SKILL.md (epic hygiene section)
**Exploration:** quick
**Status:** revised
**Review:** R1-08 claimed loose ends is a renaming of epic hygiene. Rejected — different scope (session state vs workspace state), same persistence mechanism.

## D9: findings.json as unified persistence format (implicit — now explicit)

**Choice:** Extend findings persistence to cover all categories (review, audit, loose ends, hygiene) using JSONL format at `$WORKSPACE/.audit/findings.jsonl`
**Alternatives:**
- GitHub issues — durable and visible, but heavy per-finding; better as a resolution mechanism ("file as issue") than a capture mechanism
- Entries in `.plan` — already read at session entry, but `.plan` is branch-scoped and removed at branch close
- Git-tracked markdown — human-readable and diffable, but harder to parse programmatically
- JSON array (`findings.json`) — current hygiene format; requires read-modify-write, creating race conditions across concurrent sessions
**Rationale:** JSONL (one JSON object per line) is append-only — each writer appends lines without reading the file first, eliminating the read-modify-write race condition that affects JSON array format. Issue #246 specified JSONL; this decision aligns with it. Machine-parseable for the forcing function. Not git-tracked (accumulates in workspace .audit/, not committed to project repo). Dedup by `(check, detail, branch)` ensures branch-scoped findings are independent.
**Trade-offs:** Invisible to GitHub. Not human-browsable without tooling. JSONL requires compaction (resolved findings archived after 30 days). Mitigated by work_health.py surfacing at session entry and forcing function presenting at work-end.
**Sources:** work-end/hygiene_scan.py, project/work_health.py, issue #246
**Exploration:** quick
**Status:** captured
**Review:** R1-10 noted this was implicit. Now explicit.

## D10: code-review and branch-audit coexist (implicit — now explicit)

**Choice:** Both code-review (per-line checklist) and branch-audit (holistic dimensions) run at work-end. code-review continues to run at every commit during development. branch-audit runs only at lifecycle gates.
**Alternatives:**
- branch-audit replaces code-review at work-end — loses the per-line checklist (safety, types, async patterns) that catches different bugs than holistic review
- Only branch-audit at lifecycle gates, code-review at commits only — misses per-line issues at the final gate
**Rationale:** Per-line checklist catches mutable defaults, unawaited coroutines, bare excepts. Holistic audit catches "you didn't implement requirement 3." Different concerns, both valuable at the final gate. During development, only code-review runs (per-commit) — branch-audit scope requires the full branch diff.
**Trade-offs:** Two review passes at work-end. Mitigated by code-review being fast (mechanical checklist) and branch-audit being single-pass.
**Sources:** code-review/SKILL.md, work-end/SKILL.md
**Exploration:** quick
**Status:** captured
**Review:** R1-11 noted this was implicit. Now explicit.
