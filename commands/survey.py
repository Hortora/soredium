"""Survey command — read-only inspection of every area in a family root."""
from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from commands.events import SurveyAreaInfo, SurveyReady
from project.areas import survey as run_survey


def execute(family_root: str = "") -> SurveyReady:
    if not family_root:
        raise ValueError("family_root is required")

    root = Path(family_root).expanduser().resolve()
    results = run_survey([root])
    if not results:
        return SurveyReady(family_root=str(root), areas=[], attention=[], summary={})

    sr = results[0]
    area_infos = []
    for report in sr.areas:
        a = report.area
        area_infos.append(SurveyAreaInfo(
            kind=a.kind,
            path=str(a.path),
            slot_number=a.slot_number,
            project=a.project_repo.name if a.project_repo else None,
            workspace=a.workspace_repo.name if a.workspace_repo else None,
            repos=[{**asdict(r), "path": str(r.path)} for r in report.repos],
            queues=[{"path": str(q.path), "items": q.items,
                     "open_items": q.open_items,
                     "active_issue": q.active_issue,
                     "status": q.status, "is_root": q.is_root}
                    for q in report.queues],
            closures=[asdict(c) for c in report.closures],
            work_end_preview=asdict(report.work_end_preview) if report.work_end_preview else None,
            markers=report.markers,
            findings=[{"severity": f.severity, "category": f.category,
                       "message": f.message} for f in report.findings],
            drift=[asdict(d) for d in report.drift],
            error=report.error,
        ))

    return SurveyReady(
        family_root=str(sr.family_root),
        areas=area_infos,
        attention=[{"severity": f.severity, "category": f.category,
                    "message": f.message} for f in sr.attention],
        summary=sr.summary,
    )
