"""Prompt template generation for adversarial design review sessions."""

from __future__ import annotations


def build_reviewer_prompt(
    round_num: int,
    focus_items: list[str],
    handover_path: str | None,
    convergence_override_ids: list[str] | None = None,
    source_dirs: list[str] | None = None,
    workspace_root: str = "",
    spec_path: str = "",
    mode: str = "spec-review",
    depth: str | None = None,
    maturity_stage: str = "pre-release",
) -> str:
    if mode == "pre-review":
        return _build_pre_review_reviewer_prompt(
            round_num, focus_items, handover_path, convergence_override_ids,
            source_dirs, workspace_root, spec_path,
        )
    if mode == "code-review":
        return _build_code_review_reviewer_prompt(
            round_num, focus_items, handover_path, convergence_override_ids,
            source_dirs, workspace_root, spec_path,
            maturity_stage=maturity_stage,
        )
    if mode == "final-review":
        return _build_final_review_reviewer_prompt(
            round_num, focus_items, handover_path,
            convergence_override_ids, source_dirs,
            workspace_root, spec_path, depth,
            maturity_stage=maturity_stage)
    ws = workspace_root
    parts: list[str] = []

    parts.append("ultrathink")
    parts.append("")
    parts.append(f"This is round {round_num} of an adversarial design review.")
    parts.append("")
    parts.append(f"Read the current spec at {spec_path or ws + '/spec.md'}.")
    if round_num > 1:
        parts.append(f"Read the tracker at {ws}/tracker.md for issue status and focus items.")
    parts.append("")
    if source_dirs:
        parts.append("Project directories (full read access):")
        for sd in source_dirs:
            parts.append(f"  - {sd}")
        parts.append("")
    parts.append(
        f"Write your review to {ws}/responses/reviewer-{round_num}.md following the structured "
        "output format described in the review context appended to your system prompt."
    )
    parts.append("")
    parts.append("Do NOT update the spec. Do NOT implement anything. Review only.")

    if handover_path:
        parts.append("")
        parts.append(
            f"Read the prior reviewer's handover at {ws}/{handover_path} for accumulated "
            f"insights from previous rounds."
        )

    if round_num >= 2:
        parts.append("")
        parts.append(
            "CALIBRATION: Apply the same severity threshold you would if seeing this "
            "spec for the first time. Do not assume remaining issues are marginal. "
            "Look for issues you may have missed in earlier rounds — different angles, "
            "interactions between components, failure modes under edge conditions."
        )
        parts.append("")
        parts.append(
            "Do NOT approve prematurely. A thorough review typically takes 3-5 rounds. "
            "If you have not found new issues or deeply contested existing resolutions, "
            "consider whether you have looked hard enough."
        )

    if focus_items:
        parts.append("")
        parts.append(
            f"The tracker shows {len(focus_items)} open/contested items. Focus on these: "
            + ", ".join(focus_items)
        )

    if round_num >= 2:
        parts.append("")
        parts.append(
            "EVIDENCE REQUIRED for confirmations — bare assertions are not accepted:\n"
            "- For each ADDRESSED item you confirm as resolved: cite the specific "
            "section (§N.N) that addresses it and state what the section now says "
            "that resolves the concern.\n"
            "- For each REJECTED item you accept: state why the implementor's "
            "reasoning is correct, with specific evidence.\n"
            "- SIGNAL: APPROVED will only be accepted when ALL items are in terminal "
            "state (VERIFIED or ACCEPTED). If any item is still OPEN, ADDRESSED, or "
            "REJECTED, the tracker will override your APPROVED and send you back."
        )

    if convergence_override_ids:
        parts.append("")
        parts.append(
            "The following items are NOT in terminal state. You MUST provide evidence "
            "for each — cite the section that addresses it and explain how it resolves "
            "the concern — before APPROVED can be accepted: "
            + ", ".join(convergence_override_ids)
        )

    if maturity_stage == "released":
        parts.append("")
        parts.append(
            "**This project is RELEASED — it has external consumers.** "
            "When reviewing the spec, flag any proposed change that would break "
            "public APIs, config keys, serialization formats, database schemas, "
            "or CLI flags without a documented migration path."
        )

    return "\n".join(parts)


def build_implementor_prompt(
    round_num: int,
    focus_items: list[str],
    source_dirs: list[str] | None = None,
    workspace_root: str = "",
    spec_path: str = "",
    mode: str = "spec-review",
    depth: str | None = None,
) -> str:
    if mode == "pre-review":
        return _build_pre_review_implementor_prompt(
            round_num, focus_items, source_dirs, workspace_root, spec_path,
        )
    if mode == "code-review":
        return _build_code_review_implementor_prompt(
            round_num, focus_items, source_dirs, workspace_root, spec_path,
        )
    if mode == "final-review":
        return _build_final_review_implementor_prompt(
            round_num, focus_items, source_dirs,
            workspace_root, spec_path, depth)
    ws = workspace_root
    parts: list[str] = []

    parts.append(f"This is round {round_num} of an adversarial design review.")
    parts.append("")
    parts.append(f"Read the reviewer's critique at {ws}/responses/reviewer-{round_num}.md.")
    parts.append(f"Read the tracker at {ws}/tracker.md for focus items and issue statuses.")
    if source_dirs:
        parts.append("")
        parts.append("Project directories (full read access):")
        for sd in source_dirs:
            parts.append(f"  - {sd}")
    parts.append("")
    sp = spec_path or f"{ws}/spec.md"
    parts.append(
        f"Address each open item from the tracker. Where the reviewer has a point, "
        f"improve the design — update {sp}. Where they don't, push back with "
        "specific reasoning. Do not capitulate on sound design choices just because "
        "they are contested."
    )
    parts.append("")
    parts.append(f"Update {sp} where you make changes.")
    parts.append(
        f"Write your response to {ws}/responses/implementor-{round_num}.md following the "
        "structured output format described in the review context appended to your system prompt."
    )

    if focus_items:
        parts.append("")
        parts.append(f"Focus items: {', '.join(focus_items)}")

    return "\n".join(parts)


def build_sweep_prompt(role: str, round_num: int, workspace_root: str = "") -> str:
    ws = workspace_root
    if role == "reviewer":
        return (
            f"This session is about to reset. Before it does, capture your cumulative "
            f"understanding in {ws}/handovers/reviewer-handover-{round_num}.md:\n"
            f"\n"
            f"1. Overall assessment — is the design improving, stalling, or degrading?\n"
            f"2. Patterns across issues not captured in individual tracker entries\n"
            f"3. Concerns below threshold individually but potentially accumulating\n"
            f"4. Areas of the spec you haven't examined deeply yet\n"
            f"5. Your confidence level in each major spec section (high/medium/low)\n"
            f"\n"
            f"This handover will be the ONLY context your successor has about your "
            f"analysis beyond the tracker. Be specific about what matters."
        )

    return (
        f"This session is about to reset. Before it does, capture your design "
        f"rationale in {ws}/handovers/implementor-handover-{round_num}.md:\n"
        f"\n"
        f"1. Key design decisions made during this window and WHY\n"
        f"2. Tradeoffs you considered but didn't document in the spec\n"
        f"3. Constraints you discovered that aren't in the architectural docs\n"
        f"4. Areas where you accepted reviewer critiques reluctantly — and why "
        f"you're not fully convinced\n"
        f"\n"
        f"This handover will inform your successor's approach. Be candid about "
        f"uncertainty."
    )


# ---------------------------------------------------------------------------
# Pre-review prompts — approach-level, not section-level
# ---------------------------------------------------------------------------

def _build_pre_review_reviewer_prompt(
    round_num: int,
    focus_items: list[str],
    handover_path: str | None,
    convergence_override_ids: list[str] | None = None,
    source_dirs: list[str] | None = None,
    workspace_root: str = "",
    spec_path: str = "",
) -> str:
    ws = workspace_root
    parts: list[str] = []

    parts.append("ultrathink")
    parts.append("")
    parts.append(f"This is round {round_num} of a pre-review — validating the proposed approach.")
    parts.append("")
    parts.append(f"Read the proposal at {spec_path or ws + '/spec.md'}.")
    if round_num > 1:
        parts.append(f"Read the tracker at {ws}/tracker.md for issue status and focus items.")
    parts.append("")
    if source_dirs:
        parts.append("Project directories (full read access — explore the existing codebase to understand what this approach builds on):")
        for sd in source_dirs:
            parts.append(f"  - {sd}")
        parts.append("")
    parts.append(
        f"Write your review to {ws}/responses/reviewer-{round_num}.md following the structured "
        "output format described in the review context appended to your system prompt."
    )
    parts.append("")
    parts.append(
        "Focus on the APPROACH, not the details. Is this the right way to solve "
        "the problem? Are there better alternatives the author hasn't considered? "
        "Will this age well? Is the scope right?"
    )
    parts.append("")
    parts.append("Do NOT update the spec. Do NOT implement anything. Review only.")

    if handover_path:
        parts.append("")
        parts.append(
            f"Read the prior reviewer's handover at {ws}/{handover_path} for accumulated "
            f"insights from previous rounds."
        )

    if round_num >= 2:
        parts.append("")
        parts.append(
            "Check whether the author has addressed your concerns from the "
            "previous round. If the approach has shifted, evaluate the new "
            "direction on its own merits."
        )

    if focus_items:
        parts.append("")
        parts.append(
            f"The tracker shows {len(focus_items)} open/contested items. Focus on these: "
            + ", ".join(focus_items)
        )

    if round_num >= 2:
        parts.append("")
        parts.append(
            "EVIDENCE REQUIRED for confirmations — bare assertions are not accepted:\n"
            "- For each ADDRESSED item you confirm as resolved: cite what changed "
            "in the proposal that addresses it.\n"
            "- For each REJECTED item you accept: state why the author's "
            "reasoning is correct.\n"
            "- SIGNAL: APPROVED will only be accepted when ALL items are in terminal "
            "state (VERIFIED or ACCEPTED)."
        )

    if convergence_override_ids:
        parts.append("")
        parts.append(
            "The following items are NOT in terminal state. You MUST provide evidence "
            "for each before APPROVED can be accepted: "
            + ", ".join(convergence_override_ids)
        )

    return "\n".join(parts)


def _build_pre_review_implementor_prompt(
    round_num: int,
    focus_items: list[str],
    source_dirs: list[str] | None = None,
    workspace_root: str = "",
    spec_path: str = "",
) -> str:
    ws = workspace_root
    parts: list[str] = []

    parts.append(f"This is round {round_num} of a pre-review — validating the proposed approach.")
    parts.append("")
    parts.append(f"Read the reviewer's challenges at {ws}/responses/reviewer-{round_num}.md.")
    parts.append(f"Read the tracker at {ws}/tracker.md for focus items and issue statuses.")
    if source_dirs:
        parts.append("")
        parts.append("Project directories (full read access):")
        for sd in source_dirs:
            parts.append(f"  - {sd}")
    parts.append("")
    sp = spec_path or f"{ws}/spec.md"
    parts.append(
        f"Address each challenge. Where the reviewer has found a genuine weakness "
        f"in the approach, revise the proposal at {sp}. Where they haven't, defend "
        "your choice with specific reasoning. If the reviewer proposes a better "
        "approach, evaluate it honestly — pivot if it's genuinely better."
    )
    parts.append("")
    parts.append(
        f"Write your response to {ws}/responses/implementor-{round_num}.md following the "
        "structured output format described in the review context appended to your system prompt."
    )

    if focus_items:
        parts.append("")
        parts.append(f"Focus items: {', '.join(focus_items)}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Code review prompts — code vs spec alignment
# ---------------------------------------------------------------------------

def _build_code_review_reviewer_prompt(
    round_num: int,
    focus_items: list[str],
    handover_path: str | None,
    convergence_override_ids: list[str] | None = None,
    source_dirs: list[str] | None = None,
    workspace_root: str = "",
    spec_path: str = "",
    maturity_stage: str = "pre-release",
) -> str:
    ws = workspace_root
    parts: list[str] = []

    parts.append("ultrathink")
    parts.append("")
    parts.append(f"This is round {round_num} of a code review against the reviewed spec.")
    parts.append("")
    parts.append(f"Read the reviewed spec at {spec_path or ws + '/spec.md'}.")
    parts.append("Then read the implementation code in the source directories below.")
    if round_num > 1:
        parts.append(f"Read the tracker at {ws}/tracker.md for issue status and focus items.")
    parts.append("")
    if source_dirs:
        parts.append("Implementation directories (full read access — this is the code to review against the spec):")
        for sd in source_dirs:
            parts.append(f"  - {sd}")
        parts.append("")
    parts.append(
        f"Write your review to {ws}/responses/reviewer-{round_num}.md following the structured "
        "output format described in the review context appended to your system prompt."
    )
    parts.append("")
    parts.append(
        "Check whether the code delivers what the spec promised. For each "
        "divergence, cite the specific spec section and the specific code "
        "location. Do NOT re-review the spec — it has been through adversarial "
        "review already. Focus on spec-to-code alignment."
    )
    parts.append("")
    parts.append("Do NOT modify the code. Review only.")

    if handover_path:
        parts.append("")
        parts.append(
            f"Read the prior reviewer's handover at {ws}/{handover_path} for accumulated "
            f"insights from previous rounds."
        )

    if round_num >= 2:
        parts.append("")
        parts.append(
            "Check whether the implementor has fixed the divergences you identified. "
            "Verify each fix against the spec — not just that the code changed, but "
            "that it now matches what the spec requires."
        )

    if focus_items:
        parts.append("")
        parts.append(
            f"The tracker shows {len(focus_items)} open/contested items. Focus on these: "
            + ", ".join(focus_items)
        )

    if round_num >= 2:
        parts.append("")
        parts.append(
            "EVIDENCE REQUIRED for confirmations — bare assertions are not accepted:\n"
            "- For each ADDRESSED item you confirm as resolved: cite the specific "
            "code change that now aligns with the spec.\n"
            "- For each REJECTED item you accept: state why the implementor's "
            "reasoning is correct and the spec should be updated.\n"
            "- SIGNAL: APPROVED will only be accepted when ALL items are in terminal "
            "state (VERIFIED or ACCEPTED)."
        )

    if convergence_override_ids:
        parts.append("")
        parts.append(
            "The following items are NOT in terminal state. You MUST provide evidence "
            "for each before APPROVED can be accepted: "
            + ", ".join(convergence_override_ids)
        )

    if maturity_stage == "released":
        parts.append("")
        parts.append(
            "**This project is RELEASED — it has external consumers.** "
            "Flag any breaking change to public APIs, config keys, "
            "serialization formats, database schemas, or CLI flags "
            "without a documented migration path as WARNING. "
            "Public API removal without prior deprecation is CRITICAL."
        )

    return "\n".join(parts)


def _build_code_review_implementor_prompt(
    round_num: int,
    focus_items: list[str],
    source_dirs: list[str] | None = None,
    workspace_root: str = "",
    spec_path: str = "",
) -> str:
    ws = workspace_root
    parts: list[str] = []

    parts.append(f"This is round {round_num} of a code review against the reviewed spec.")
    parts.append("")
    parts.append(f"Read the reviewer's findings at {ws}/responses/reviewer-{round_num}.md.")
    parts.append(f"Read the tracker at {ws}/tracker.md for focus items and issue statuses.")
    parts.append(f"Read the spec at {spec_path or ws + '/spec.md'} to verify the reviewer's claims.")
    if source_dirs:
        parts.append("")
        parts.append("Implementation directories (full read and write access):")
        for sd in source_dirs:
            parts.append(f"  - {sd}")
    parts.append("")
    parts.append(
        "Address each divergence the reviewer identified. Where the code genuinely "
        "deviates from the spec, fix the code. Where you deliberately deviated, "
        "explain why and propose a spec update. Where the reviewer misreads the "
        "spec, cite the specific section that supports your implementation."
    )
    parts.append("")
    parts.append(
        f"Write your response to {ws}/responses/implementor-{round_num}.md following the "
        "structured output format described in the review context appended to your system prompt."
    )

    if focus_items:
        parts.append("")
        parts.append(f"Focus items: {', '.join(focus_items)}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Final review prompts — production readiness of branch diff
# ---------------------------------------------------------------------------

def _build_final_review_reviewer_prompt(
    round_num: int,
    focus_items: list[str],
    handover_path: str | None,
    convergence_override_ids: list[str] | None = None,
    source_dirs: list[str] | None = None,
    workspace_root: str = "",
    spec_path: str = "",
    depth: str | None = None,
    maturity_stage: str = "pre-release",
) -> str:
    depth = depth or "standard"
    parts: list[str] = []

    if round_num == 1:
        if depth == "light":
            parts.append(
                "Quick review of the branch diff. Focus on correctness risks "
                "and security issues only. Flag items that would cause bugs or "
                "vulnerabilities in production. This is a single-pass sanity check."
            )
        else:
            parts.append(
                "Review the branch diff for production readiness. "
                "Compute `git diff <base>..HEAD` in each source directory. "
                "Read every changed file and apply production readiness criteria."
            )
            parts.append(
                "\n**Main code:** architecture, correctness, edge cases, error "
                "handling, performance, concurrency, security, naming, structure, "
                "layer compliance."
            )
            parts.append(
                "\n**Test code:** coverage completeness, assertion quality, "
                "missing scenarios, test isolation."
            )
            if depth == "deep":
                parts.append(
                    "\n**Cross-module impact:** shared interface changes, "
                    "behavioral changes visible to other modules, transaction "
                    "boundary changes, configuration changes, test isolation "
                    "across modules."
                )
        if source_dirs:
            parts.append(f"\nSource directories: {', '.join(source_dirs)}")
    else:
        parts.append(f"Round {round_num} review.")
        if focus_items:
            parts.append("\nOpen items from previous rounds:\n")
            for item in focus_items:
                parts.append(f"- {item}")
            parts.append(
                "\nFor each open item: verify the implementor's fix by reading "
                "the actual code. Mark as RESOLVED (fix confirmed), "
                "ACCEPTED (rejection is valid), or STILL OPEN (not fixed)."
            )
        parts.append(
            "\nAlso look for new issues not previously raised."
        )

    if convergence_override_ids:
        ids = ", ".join(convergence_override_ids)
        parts.append(
            f"\n**CONVERGENCE OVERRIDE:** Items {ids} were marked resolved "
            "without sufficient evidence. You MUST provide concrete evidence "
            "for each — quote the code or explain why the concern no longer applies."
        )

    if maturity_stage == "released":
        parts.append(
            "\n**This project is RELEASED — it has external consumers.** "
            "Flag any breaking change to public APIs, config keys, "
            "serialization formats, database schemas, or CLI flags "
            "without a documented migration path as WARNING. "
            "Public API removal without prior deprecation is CRITICAL."
        )

    if handover_path:
        parts.append(f"\nPrevious session handover: {handover_path}")

    parts.append(
        f"\nWrite your review to {workspace_root}/responses/reviewer-{round_num}.md"
    )

    return "\n".join(parts)


def _build_final_review_implementor_prompt(
    round_num: int,
    focus_items: list[str],
    source_dirs: list[str] | None = None,
    workspace_root: str = "",
    spec_path: str = "",
    depth: str | None = None,
) -> str:
    parts: list[str] = []

    parts.append(
        "The reviewer has raised issues with the branch code. For each item:"
    )
    parts.append(
        "\n- **FIXED:** Fix the code in the source directories. Show what you "
        "changed. Do NOT update a spec — fix the actual source code."
    )
    parts.append(
        "- **REJECTED:** Defend the implementation with evidence. Quote the "
        "code, reference tests, explain the design rationale."
    )

    if focus_items:
        parts.append("\n## Items to address\n")
        for item in focus_items:
            parts.append(f"- {item}")

    if source_dirs:
        parts.append(f"\nSource directories: {', '.join(source_dirs)}")

    parts.append(
        f"\nWrite your response to {workspace_root}/responses/implementor-{round_num}.md"
    )

    return "\n".join(parts)
