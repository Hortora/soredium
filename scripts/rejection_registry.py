"""Registry of rejected pattern candidates — prevents re-surfacing known noise."""
from __future__ import annotations
import math
from datetime import date
from pathlib import Path
import yaml

from cluster_pipeline import FEATURE_KEYS, fingerprint_to_vector

_REJECTION_SIMILARITY_THRESHOLD = 0.98


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class RejectionRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> list:
        data = yaml.safe_load(self.path.read_text()) or {}
        return data.get('rejections', [])

    def _save(self, rejections: list) -> None:
        self.path.write_text(
            yaml.dump({'rejections': rejections}, default_flow_style=False, sort_keys=False)
        )

    def list(self) -> list:
        return self._load()

    def add(self, centroid: dict, projects: list[str], reason: str) -> None:
        rejections = self._load()
        rejections.append({
            'centroid': centroid,
            'projects': projects,
            'reason': reason,
            'rejected_at': str(date.today()),
        })
        self._save(rejections)

    def is_rejected(self, centroid: dict) -> bool:
        vec = fingerprint_to_vector(centroid)
        for record in self._load():
            known_vec = fingerprint_to_vector(record['centroid'])
            if _cosine_similarity(vec, known_vec) >= _REJECTION_SIMILARITY_THRESHOLD:
                return True
        return False
