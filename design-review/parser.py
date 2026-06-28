"""Structured output parser for adversarial design review responses.

Parses reviewer and implementor response files to extract signals,
issues, confirmations, section references, and markers. Uses regex-based
fuzzy matching with per-item fallbacks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Signal:
    signal_type: str
    description: str | None = None
    is_default: bool = False


@dataclass
class Issue:
    issue_id: str
    title: str
    body: str


@dataclass(frozen=True)
class Confirmation:
    issue_id: str
    is_resolved: bool
    reason: str = ""


@dataclass
class IssueResponse:
    issue_id: str
    status: str
    section_ref: str | None = None
    rationale: str = ""
    body: str = ""


@dataclass(frozen=True)
class SettledDecision:
    text: str
    from_issue: str


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_SIGNAL_RE: Final = re.compile(
    r"^\s*SIGNAL\s*[:\s]+\s*(APPROVED|CONTINUE|DECISION_NEEDED)\b\s*[.:]*\s*(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_HEADING_RE: Final = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.MULTILINE)

_ISSUE_ID_RE: Final = re.compile(r"R(\d+)-(\d+)")

_ISSUE_RESPONSE_RE: Final = re.compile(
    r"^#{2,3}\s+R(\d+)-(\d+)\s*[:\s—\-]+\s*(FIXED|REJECTED|ESCALATED)\b",
    re.IGNORECASE | re.MULTILINE,
)

_CONFIRMATION_RE: Final = re.compile(
    r"R(\d+)-(\d+)\b[^#\n]*?\b(resolved|still\s+open)\b",
    re.IGNORECASE,
)

_SECTION_REF_RE: Final = re.compile(
    r"§(\d+(?:\.\d+)*)|[Ss]ection\s+(\d+(?:\.\d+)*)"
)

_ASSUMPTION_RE: Final = re.compile(r"^ASSUMPTION:\s*(.+)$", re.MULTILINE)

_SETTLED_RE: Final = re.compile(
    r"^SETTLED:\s*(.+?)(?:\(from\s+(R\d+-\d+)\))?\s*$", re.MULTILINE
)

_KNOWN_SECTIONS: Final = frozenset({
    "addressed items",
    "assumptions",
    "settled decisions",
    "signals",
    "signal",
})


# ---------------------------------------------------------------------------
# Signal extraction
# ---------------------------------------------------------------------------

def extract_signal(content: str) -> Signal:
    last_10 = "\n".join(content.splitlines()[-10:])
    matches = list(_SIGNAL_RE.finditer(last_10))
    if not matches:
        all_matches = list(_SIGNAL_RE.finditer(content))
        if all_matches:
            matches = all_matches

    if not matches:
        return Signal(signal_type="CONTINUE", is_default=True)

    match = matches[-1]
    signal_type = match.group(1).upper()
    description = match.group(2).strip() if match.group(2) else None
    if signal_type == "DECISION_NEEDED" and description:
        description = description.lstrip(": ").strip()
        if not description:
            description = None
    elif signal_type != "DECISION_NEEDED":
        description = None

    return Signal(signal_type=signal_type, description=description)


# ---------------------------------------------------------------------------
# Reviewer issue extraction
# ---------------------------------------------------------------------------

def extract_new_issues(
    content: str,
    round_num: int,
    existing_ids: set[str],
) -> list[Issue]:
    headings = list(_HEADING_RE.finditer(content))
    issues: list[Issue] = []
    seq = 1

    for i, match in enumerate(headings):
        title = match.group(2).strip()

        if title.lower().rstrip(":") in _KNOWN_SECTIONS:
            continue

        if _ISSUE_ID_RE.search(title):
            found_id = _ISSUE_ID_RE.search(title).group(0)
            if found_id in existing_ids:
                continue

        start = match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(content)
        body = content[start:end].strip()

        # Strip signal section from body
        signal_match = re.search(r"\n---\s*\n", body)
        if signal_match:
            body = body[:signal_match.start()].strip()

        issue_id = f"R{round_num}-{seq:02d}"
        issues.append(Issue(issue_id=issue_id, title=title, body=body))
        seq += 1

    return issues


# ---------------------------------------------------------------------------
# Confirmation extraction
# ---------------------------------------------------------------------------

def extract_confirmations(content: str) -> list[Confirmation]:
    confirmations: list[Confirmation] = []

    for match in _CONFIRMATION_RE.finditer(content):
        issue_id = f"R{match.group(1)}-{match.group(2)}"
        status_text = match.group(3).lower().strip()
        is_resolved = "resolved" in status_text and "still" not in status_text

        reason = ""
        if not is_resolved:
            line_end = content.find("\n", match.end())
            if line_end == -1:
                line_end = len(content)
            after = content[match.end():line_end].strip()
            after = re.sub(r"^[\s—\-:]+", "", after).strip()
            reason = after

        confirmations.append(Confirmation(
            issue_id=issue_id,
            is_resolved=is_resolved,
            reason=reason,
        ))

    return confirmations


# ---------------------------------------------------------------------------
# Implementor response parsing
# ---------------------------------------------------------------------------

def extract_issue_responses(content: str) -> list[IssueResponse]:
    matches = list(_ISSUE_RESPONSE_RE.finditer(content))
    responses: list[IssueResponse] = []

    for i, match in enumerate(matches):
        issue_id = f"R{match.group(1)}-{match.group(2)}"
        status = match.group(3).upper()

        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()

        signal_match = re.search(r"\n---\s*\n", body)
        if signal_match:
            body = body[:signal_match.start()].strip()
        settled_match = re.search(r"^SETTLED:", body, re.MULTILINE)
        if settled_match:
            body = body[:settled_match.start()].strip()

        section_ref: str | None = None
        ref_match = _SECTION_REF_RE.search(body)
        if ref_match:
            section_ref = ref_match.group(1) or ref_match.group(2)

        rationale = ""
        if status == "REJECTED":
            rationale = body
        elif status == "ESCALATED":
            rationale = body

        responses.append(IssueResponse(
            issue_id=issue_id,
            status=status,
            section_ref=section_ref,
            rationale=rationale,
            body=body,
        ))

    return responses


# ---------------------------------------------------------------------------
# Marker extraction
# ---------------------------------------------------------------------------

def extract_assumptions(content: str) -> list[str]:
    return [m.group(1).strip() for m in _ASSUMPTION_RE.finditer(content)]


def extract_settled_decisions(content: str) -> list[SettledDecision]:
    decisions: list[SettledDecision] = []
    for match in _SETTLED_RE.finditer(content):
        text = match.group(1).strip()
        from_issue = match.group(2) or ""
        decisions.append(SettledDecision(text=text, from_issue=from_issue))
    return decisions
