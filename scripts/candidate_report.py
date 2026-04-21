"""Serialize/deserialize cluster+delta candidate reports to/from JSON."""
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class CandidateReport:
    cluster_candidates: list
    delta_candidates: list
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def total_count(self) -> int:
        return len(self.cluster_candidates) + len(self.delta_candidates)


def save_report(report: CandidateReport, path: Path) -> None:
    path = Path(path)
    data = {
        'generated_at': report.generated_at,
        'cluster_candidates': report.cluster_candidates,
        'delta_candidates': report.delta_candidates,
    }
    path.write_text(json.dumps(data, indent=2))


def load_report(path: Path) -> CandidateReport:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Report not found: {path}")
    data = json.loads(path.read_text())
    return CandidateReport(
        cluster_candidates=data['cluster_candidates'],
        delta_candidates=data['delta_candidates'],
        generated_at=data['generated_at'],
    )