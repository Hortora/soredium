"""Issue tracker for adversarial design review.

Manages the issue lifecycle state machine, premature convergence
detection, and tracker file rendering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Final


class IssueStatus(Enum):
    OPEN = "OPEN"
    ADDRESSED = "ADDRESSED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"
    CONTESTED = "CONTESTED"
    DEFERRED = "DEFERRED"


_TERMINAL: Final = frozenset({IssueStatus.VERIFIED, IssueStatus.ACCEPTED, IssueStatus.DEFERRED})

PRIORITY_ORDER: Final = ("HIGH", "MEDIUM", "LOW")


def _heading_slug(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    return slug

_VALID_TRANSITIONS: Final[dict[IssueStatus, frozenset[IssueStatus]]] = {
    IssueStatus.OPEN: frozenset({IssueStatus.ADDRESSED, IssueStatus.REJECTED, IssueStatus.DEFERRED}),
    IssueStatus.ADDRESSED: frozenset({IssueStatus.VERIFIED, IssueStatus.CONTESTED}),
    IssueStatus.REJECTED: frozenset({IssueStatus.ACCEPTED, IssueStatus.CONTESTED}),
    IssueStatus.CONTESTED: frozenset({IssueStatus.ADDRESSED, IssueStatus.DEFERRED}),
    IssueStatus.VERIFIED: frozenset(),
    IssueStatus.ACCEPTED: frozenset(),
    IssueStatus.DEFERRED: frozenset(),
}


@dataclass
class TrackedIssue:
    issue_id: str
    summary: str
    round_raised: int
    status: IssueStatus = IssueStatus.OPEN
    contested_rounds: int = 0
    commit_before: str = ""
    commit_after: str = ""
    section_ref: str = ""
    rationale: str = ""
    notes: str = ""
    location: str = ""
    priority: str = "LOW"
    depends: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ConvergenceResult:
    should_override: bool
    unconfirmed_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VerifyResult:
    section_changed: bool
    note: str = ""


@dataclass(frozen=True)
class Assumption:
    text: str
    round_surfaced: int
    source: str


@dataclass(frozen=True)
class SettledDecisionEntry:
    text: str
    from_issue: str
    rationale: str


@dataclass(frozen=True)
class EvidenceResult:
    verified: bool
    note: str = ""


@dataclass
class RoundSummary:
    round_num: int
    raised: int = 0
    verified: int = 0
    accepted: int = 0
    open: int = 0
    contested: int = 0
    deferred: int = 0


class Tracker:

    def __init__(self, project_name: str) -> None:
        self.project_name = project_name
        self.start_date = date.today().isoformat()
        self.current_round = 0
        self._issues: dict[str, TrackedIssue] = {}
        self._assumptions: list[Assumption] = []
        self._settled: list[SettledDecisionEntry] = []
        self._round_summaries: list[RoundSummary] = []
        self._previous_snapshot: dict[str, IssueStatus] = {}

    def add_issue(self, issue_id: str, summary: str, round_raised: int,
                  location: str = "", priority: str = "LOW",
                  depends: list[str] | None = None) -> None:
        self._issues[issue_id] = TrackedIssue(
            issue_id=issue_id, summary=summary, round_raised=round_raised,
            location=location, priority=priority,
            depends=depends if depends is not None else [],
        )

    def get_issue(self, issue_id: str) -> TrackedIssue:
        if issue_id not in self._issues:
            raise KeyError(f"Unknown issue: {issue_id}")
        return self._issues[issue_id]

    def has_issue(self, issue_id: str) -> bool:
        return issue_id in self._issues

    def issue_ids(self) -> set[str]:
        return set(self._issues.keys())

    def issues(self) -> list[TrackedIssue]:
        return list(self._issues.values())

    def all_resolved(self) -> bool:
        return bool(self._issues) and all(
            issue.status in _TERMINAL for issue in self._issues.values()
        )

    def _check_transition(self, issue: TrackedIssue, target: IssueStatus) -> None:
        valid = _VALID_TRANSITIONS.get(issue.status, frozenset())
        if target not in valid:
            raise ValueError(
                f"Invalid transition for {issue.issue_id}: "
                f"{issue.status.value} → {target.value}"
            )

    def mark_addressed(
        self, issue_id: str, section_ref: str, commit_hash: str, rationale: str,
    ) -> None:
        issue = self.get_issue(issue_id)
        self._check_transition(issue, IssueStatus.ADDRESSED)
        issue.status = IssueStatus.ADDRESSED
        issue.section_ref = section_ref
        issue.commit_after = commit_hash
        issue.rationale = rationale

    def mark_rejected(self, issue_id: str, rationale: str) -> None:
        issue = self.get_issue(issue_id)
        self._check_transition(issue, IssueStatus.REJECTED)
        issue.status = IssueStatus.REJECTED
        issue.rationale = rationale

    def mark_verified(self, issue_id: str) -> None:
        issue = self.get_issue(issue_id)
        self._check_transition(issue, IssueStatus.VERIFIED)
        issue.status = IssueStatus.VERIFIED

    def mark_accepted(self, issue_id: str) -> None:
        issue = self.get_issue(issue_id)
        self._check_transition(issue, IssueStatus.ACCEPTED)
        issue.status = IssueStatus.ACCEPTED

    def mark_contested(self, issue_id: str, reason: str) -> None:
        issue = self.get_issue(issue_id)
        self._check_transition(issue, IssueStatus.CONTESTED)
        issue.contested_rounds += 1
        if issue.contested_rounds >= 2:
            # Auto-escalation: bypass transition check for CONTESTED → DEFERRED
            issue.status = IssueStatus.DEFERRED
            issue.notes = f"auto-escalated: contested for {issue.contested_rounds} rounds"
        else:
            issue.status = IssueStatus.CONTESTED
            issue.notes = reason

    def mark_deferred(self, issue_id: str, note: str) -> None:
        issue = self.get_issue(issue_id)
        self._check_transition(issue, IssueStatus.DEFERRED)
        issue.status = IssueStatus.DEFERRED
        issue.notes = note

    def check_premature_convergence(self, round_num: int) -> ConvergenceResult:
        if round_num > 3:
            return ConvergenceResult(should_override=False)

        all_ids = list(self._issues.keys())
        verified_ids = {
            iid for iid, issue in self._issues.items()
            if issue.status in (IssueStatus.VERIFIED, IssueStatus.ACCEPTED, IssueStatus.DEFERRED)
        }
        unconfirmed = [iid for iid in all_ids if iid not in verified_ids]

        if len(unconfirmed) > len(all_ids) / 2:
            return ConvergenceResult(should_override=True, unconfirmed_ids=unconfirmed)

        return ConvergenceResult(should_override=False)

    def get_focus_items(self) -> list[str]:
        return [
            iid for iid, issue in self._issues.items()
            if issue.status in (
                IssueStatus.OPEN, IssueStatus.CONTESTED,
                IssueStatus.ADDRESSED, IssueStatus.REJECTED,
            )
        ]

    def get_focus_items_by_priority(self) -> dict[str, list[str]]:
        focus = self.get_focus_items()
        grouped: dict[str, list[str]] = {}
        for iid in focus:
            priority = self._issues[iid].priority
            grouped.setdefault(priority, []).append(iid)
        return {p: grouped[p] for p in PRIORITY_ORDER if p in grouped}

    def add_assumption(self, text: str, round_surfaced: int, source: str) -> None:
        self._assumptions.append(Assumption(text=text, round_surfaced=round_surfaced, source=source))

    def add_settled_decision(self, text: str, from_issue: str, rationale: str) -> None:
        self._settled.append(SettledDecisionEntry(text=text, from_issue=from_issue, rationale=rationale))

    def record_round(self, round_num: int) -> None:
        current_snapshot = self._status_snapshot()
        previous_snapshot = self._previous_snapshot

        counts = RoundSummary(round_num=round_num)
        for issue in self._issues.values():
            if issue.round_raised == round_num:
                counts.raised += 1

        for iid, status in current_snapshot.items():
            prev = previous_snapshot.get(iid)
            if status == IssueStatus.VERIFIED and prev != IssueStatus.VERIFIED:
                counts.verified += 1
            elif status == IssueStatus.ACCEPTED and prev != IssueStatus.ACCEPTED:
                counts.accepted += 1
            elif status == IssueStatus.DEFERRED and prev != IssueStatus.DEFERRED:
                counts.deferred += 1
            elif status == IssueStatus.CONTESTED and prev != IssueStatus.CONTESTED:
                counts.contested += 1

        counts.open = sum(
            1 for s in current_snapshot.values()
            if s in (IssueStatus.OPEN, IssueStatus.ADDRESSED, IssueStatus.REJECTED, IssueStatus.CONTESTED)
        )

        self._round_summaries.append(counts)
        self._previous_snapshot = current_snapshot

    def _status_snapshot(self) -> dict[str, IssueStatus]:
        return {iid: issue.status for iid, issue in self._issues.items()}

    def get_round_summaries(self) -> list[RoundSummary]:
        return list(self._round_summaries)

    def render(self) -> str:
        lines: list[str] = []
        lines.append("# Design Review Tracker")
        lines.append("")
        lines.append(f"Spec: spec.md | Project: {self.project_name}")
        lines.append(f"Started: {self.start_date} | Current round: {self.current_round}")
        lines.append("")

        lines.append("## Issues")
        lines.append("")
        for issue in self._issues.values():
            slug = _heading_slug(f"{issue.issue_id}: {issue.summary}")
            lines.append(f"### {issue.issue_id}: {issue.summary}")
            reviewer_file = f"responses/reviewer-{issue.round_raised}.md"
            lines.append(f"- **Raised:** Round {issue.round_raised} ([{reviewer_file}]({reviewer_file}#{slug}))")
            lines.append(f"- **Status:** {issue.status.value}")
            if issue.location:
                lines.append(f"- **Location:** {issue.location}")
            if issue.priority and issue.priority != "LOW":
                lines.append(f"- **Priority:** {issue.priority}")
            if issue.depends:
                lines.append(f"- **Depends:** {', '.join(issue.depends)}")
            if issue.contested_rounds:
                lines.append(f"- **Contested rounds:** {issue.contested_rounds}")
            if issue.commit_after:
                lines.append(f"- **Spec commit:** {issue.commit_before} → {issue.commit_after}")
            if issue.section_ref:
                lines.append(f"- **Evidence:** [§{issue.section_ref}](spec.md)")
            if issue.rationale:
                lines.append(f"- **Rationale:** {issue.rationale}")
            if issue.notes:
                lines.append(f"- **Notes:** {issue.notes}")
            lines.append("")

        if self._round_summaries:
            lines.append("## Summary")
            lines.append("")
            lines.append("| Round | Raised | Verified | Accepted | Open | Contested | Deferred |")
            lines.append("|-------|--------|----------|----------|------|-----------|----------|")
            for s in self._round_summaries:
                lines.append(
                    f"| {s.round_num} | {s.raised} | {s.verified} | {s.accepted} "
                    f"| {s.open} | {s.contested} | {s.deferred} |"
                )
            lines.append("")

        focus = self.get_focus_items()
        lines.append("## Focus for next round")
        if focus:
            lines.append(", ".join(focus))
        else:
            lines.append("None — all issues resolved")
        lines.append("")

        if self._assumptions:
            lines.append("## Assumptions")
            lines.append("")
            lines.append("| # | Assumption | Surfaced | Source |")
            lines.append("|---|-----------|----------|--------|")
            for i, a in enumerate(self._assumptions, 1):
                lines.append(f"| A{i} | {a.text} | Round {a.round_surfaced} | {a.source} |")
            lines.append("")

        if self._settled:
            lines.append("## Settled Decisions")
            lines.append("")
            lines.append("| Decision | From issue | Rationale |")
            lines.append("|----------|-----------|-----------|")
            for d in self._settled:
                lines.append(f"| {d.text} | {d.from_issue} | {d.rationale} |")
            lines.append("")

        return "\n".join(lines)

    def write(self, path: Path) -> None:
        path.write_text(self.render())


# ---------------------------------------------------------------------------
# Evidence verification (replaces verify_against_diff)
# ---------------------------------------------------------------------------

def verify_evidence_against_diff(
    evidence: list,
    diff: str,
    spec_content: str,
) -> EvidenceResult:
    if not evidence:
        return EvidenceResult(verified=False, note="no evidence provided")

    for ev in evidence:
        section_ref = _extract_section_number(ev.location)
        if section_ref is None:
            continue

        section_range = _find_section_range(spec_content, section_ref)
        if section_range is None:
            return EvidenceResult(
                verified=False,
                note=f"section {ev.location} not found in spec",
            )

        modified_lines = _parse_diff_modified_lines(diff)
        start, end = section_range
        if any(start <= line <= end for line in modified_lines):
            return EvidenceResult(verified=True)

    first_loc = evidence[0].location if evidence else "unknown"
    return EvidenceResult(
        verified=False,
        note=f"{first_loc} not modified in diff",
    )


def _extract_section_number(location: str) -> str | None:
    m = re.search(r"§(\d+(?:\.\d+)*)", location)
    return m.group(1) if m else None


def _find_section_range(content: str, section_ref: str) -> tuple[int, int] | None:
    lines = content.split("\n")
    heading_re = re.compile(r"^(#{1,6})\s+(.+)")
    start_line = None
    start_level = 0

    for i, line in enumerate(lines, 1):
        m = heading_re.match(line)
        if not m:
            continue
        level = len(m.group(1))
        title = m.group(2)
        num_match = re.match(r"[§S]?(\d+(?:\.\d+)*)", title)
        if num_match and num_match.group(1) == section_ref:
            start_line = i
            start_level = level
            continue
        if start_line is not None and level <= start_level:
            return (start_line, i - 1)

    if start_line is not None:
        return (start_line, len(lines))

    for i, line in enumerate(lines, 1):
        if f"§{section_ref}" in line:
            return (i, i)

    return None


def _parse_diff_modified_lines(diff: str) -> set[int]:
    modified: set[int] = set()
    current_line = 0
    for line in diff.split("\n"):
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            if m:
                current_line = int(m.group(1))
            continue
        if line.startswith("+") and not line.startswith("+++"):
            modified.add(current_line)
            current_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            pass
        else:
            current_line += 1
    return modified
