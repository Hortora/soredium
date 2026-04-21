"""Human validation gate for pattern candidates.

validate_candidates() accepts a decide_fn callback for testability.
The CLI (__main__) wires it to stdin.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from candidate_report import CandidateReport
from rejection_registry import RejectionRegistry
from pattern_entry import write_skeleton


class Decision:
    ACCEPT = 'accept'
    REJECT = 'reject'
    SKIP = 'skip'


@dataclass
class SessionSummary:
    accepted: int
    rejected: int
    skipped: int

    def total(self) -> int:
        return self.accepted + self.rejected + self.skipped


def validate_candidates(
    report: CandidateReport,
    registry_projects: list[dict],
    rejections_path: Path,
    out_dir: Path,
    decide_fn: Callable[[dict], tuple[str, str | None]],
) -> SessionSummary:
    """Process all cluster candidates through decide_fn.

    decide_fn(candidate) -> (Decision.ACCEPT|REJECT|SKIP, reason_or_None)
    Already-rejected candidates are auto-skipped without calling decide_fn.
    """
    rejection_reg = RejectionRegistry(rejections_path)
    accepted = rejected = skipped = 0

    for candidate in report.cluster_candidates:
        if rejection_reg.is_rejected(candidate['centroid']):
            skipped += 1
            continue

        decision, reason = decide_fn(candidate)

        if decision == Decision.ACCEPT:
            write_skeleton(candidate, registry_projects, out_dir)
            accepted += 1
        elif decision == Decision.REJECT:
            rejection_reg.add(candidate['centroid'], candidate['projects'], reason or '')
            rejected += 1
        else:
            skipped += 1

    return SessionSummary(accepted=accepted, rejected=rejected, skipped=skipped)


if __name__ == '__main__':
    import sys
    from candidate_report import load_report

    if len(sys.argv) < 4:
        print('Usage: validate_candidates.py <report.json> <rejections.yaml> <out_dir>')
        sys.exit(1)

    report = load_report(Path(sys.argv[1]))
    rejections_path = Path(sys.argv[2])
    out_dir = Path(sys.argv[3])
    registry_projects: list[dict] = []

    def _stdin_decide(candidate: dict) -> tuple[str, str | None]:
        print(f"\nCandidate: {candidate['projects']}")
        print(f"  Similarity: {candidate['similarity_score']}")
        print(f"  Centroid: {candidate['centroid']}")
        choice = input('  [a]ccept / [r]eject / [s]kip: ').strip().lower()
        if choice == 'a':
            return Decision.ACCEPT, None
        elif choice == 'r':
            reason = input('  Reason: ').strip()
            return Decision.REJECT, reason
        return Decision.SKIP, None

    summary = validate_candidates(report, registry_projects, rejections_path, out_dir, _stdin_decide)
    print(f'\nDone — accepted: {summary.accepted}, rejected: {summary.rejected}, skipped: {summary.skipped}')
