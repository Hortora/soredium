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
) -> str:
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

    if convergence_override_ids:
        parts.append("")
        parts.append(
            "The following items were not explicitly confirmed in your previous review. "
            "You MUST confirm each individually before APPROVED can be accepted: "
            + ", ".join(convergence_override_ids)
        )

    return "\n".join(parts)


def build_implementor_prompt(
    round_num: int,
    focus_items: list[str],
    source_dirs: list[str] | None = None,
    workspace_root: str = "",
    spec_path: str = "",
) -> str:
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
