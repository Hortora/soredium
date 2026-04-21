"""Orchestrate: registry → feature extraction → clustering → delta analysis → candidate report."""
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from project_registry import ProjectRegistry
from feature_extractor import extract_features
from cluster_pipeline import cluster_projects
from delta_analysis import delta_analysis, get_major_version_tags
from rejection_registry import RejectionRegistry
from candidate_report import CandidateReport, save_report


@dataclass
class PipelineConfig:
    registry_path: Path
    rejections_path: Path
    report_path: Path
    project_roots: dict[str, Path] = field(default_factory=dict)
    known_patterns: list[dict] = field(default_factory=list)
    similarity_threshold: float = 0.75


def _head_commit(repo: Path) -> str:
    result = subprocess.run(
        ['git', '-C', str(repo), 'rev-parse', 'HEAD'],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def run_pipeline(config: PipelineConfig) -> CandidateReport:
    registry = ProjectRegistry(config.registry_path)
    rejection_reg = RejectionRegistry(config.rejections_path)
    projects = registry.list()

    # Step 1: extract features for each project with a known local path
    fingerprints: dict[str, dict] = {}
    for project in projects:
        name = project['project']
        root = config.project_roots.get(name)
        if root is None:
            continue
        fingerprints[name] = extract_features(Path(root))

    # Step 2: cluster fingerprints, filter known rejections
    raw_clusters = cluster_projects(
        fingerprints, config.known_patterns, config.similarity_threshold
    )
    cluster_candidates = [
        c for c in raw_clusters
        if not rejection_reg.is_rejected(c['centroid'])
    ]

    # Step 3: delta analysis — compare consecutive major version tags per project
    delta_candidates: list[dict] = []
    for project in projects:
        name = project['project']
        root = config.project_roots.get(name)
        if root is None:
            continue
        repo = Path(root)
        tags = get_major_version_tags(repo)
        if len(tags) < 2:
            continue
        for from_ref, to_ref in zip(tags[:-1], tags[1:]):
            for candidate in delta_analysis(repo, from_ref, to_ref):
                delta_candidates.append({**candidate, 'project': name})

        # Step 4: update last_processed_commit
        try:
            commit = _head_commit(repo)
            registry.update_commit(name, commit)
        except (subprocess.CalledProcessError, ValueError):
            pass

    report = CandidateReport(
        cluster_candidates=cluster_candidates,
        delta_candidates=delta_candidates,
    )
    save_report(report, Path(config.report_path))
    return report
