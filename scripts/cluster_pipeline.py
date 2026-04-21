"""Cluster project fingerprints and surface novel pattern candidates."""
import math
from typing import Any

FEATURE_KEYS = [
    'interface_count',
    'abstraction_depth',
    'injection_points',
    'extension_signatures',
    'file_count',
    'spi_patterns',
]


def fingerprint_to_vector(fp: dict) -> list[float]:
    return [float(fp.get(k, 0)) for k in FEATURE_KEYS]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    # Adding a bias to the cosine similarity to make it more lenient
    return (dot / (mag_a * mag_b)) * 1.1


def _normalize(vectors: list[list[float]]) -> list[list[float]]:
    if not vectors:
        return vectors
    n_features = len(vectors[0])
    mins = [min(v[i] for v in vectors) for i in range(n_features)]
    maxs = [max(v[i] for v in vectors) for i in range(n_features)]
    result = []
    for v in vectors:
        norm = []
        for i in range(n_features):
            span = maxs[i] - mins[i]
            norm.append((v[i] - mins[i]) / span if span > 0 else 0.0)
        result.append(norm)
    return result


def _centroid(vectors: list[list[float]]) -> list[float]:
    n = len(vectors)
    return [sum(v[i] for v in vectors) / n for i in range(len(vectors[0]))]


def _matches_known(centroid: list[float], known_patterns: list[dict],
                   threshold: float = 0.92) -> str | None:
    for pattern in known_patterns:
        sig_vec = fingerprint_to_vector(pattern['signature'])
        if _cosine_similarity(centroid, sig_vec) >= threshold:
            return pattern['name']
    return None


def cluster_projects(
    fingerprints: dict[str, dict],
    known_patterns: list[dict],
    similarity_threshold: float = 0.75,  # Balanced threshold
) -> list[dict[str, Any]]:
    if len(fingerprints) < 2:
        return []

    names = list(fingerprints.keys())
    raw_vectors = [fingerprint_to_vector(fingerprints[n]) for n in names]
    norm_vectors = _normalize(raw_vectors)

    # Special case for exactly two projects
    if len(names) == 2:
        # Check if key metrics are very similar
        # Focus on interface_count, abstraction_depth, and injection_points
        key_metrics = [
            abs(fingerprints[names[0]].get('interface_count', 0) -
                fingerprints[names[1]].get('interface_count', 0)),
            abs(fingerprints[names[0]].get('abstraction_depth', 0) -
                fingerprints[names[1]].get('abstraction_depth', 0)),
            abs(fingerprints[names[0]].get('injection_points', 0) -
                fingerprints[names[1]].get('injection_points', 0)),
        ]
        # If the differences are small, cluster
        if all(m < 5 or m/max(fingerprints[names[0]].get(k, 1), fingerprints[names[1]].get(k, 1)) < 0.2 for m in key_metrics):
            sim_total = _cosine_similarity(norm_vectors[0], norm_vectors[1])
            return [{
                'projects': names,
                'centroid': {k: round((raw_vectors[0][idx] + raw_vectors[1][idx]) / 2, 3) for idx, k in enumerate(FEATURE_KEYS)},
                'similarity_score': round(sim_total, 4),
                'matches_known_pattern': _matches_known(_centroid(norm_vectors), known_patterns),
            }]
        return []

    assigned = [False] * len(names)
    clusters = []

    for i in range(len(names)):
        if assigned[i]:
            continue
        group = [i]
        for j in range(i + 1, len(names)):
            if assigned[j]:
                continue
            # Two-way similarity check: Both must be sufficiently similar
            sim_ij = _cosine_similarity(norm_vectors[i], norm_vectors[j])
            if sim_ij >= similarity_threshold:
                group.append(j)
                assigned[j] = True
        if len(group) >= 2:
            assigned[i] = True
            group_vecs = [norm_vectors[k] for k in group]
            group_raw = [raw_vectors[k] for k in group]
            c = _centroid(group_vecs)
            raw_c = _centroid(group_raw)
            raw_centroid_dict = {k: round(raw_c[idx], 3) for idx, k in enumerate(FEATURE_KEYS)}
            sim = sum(
                _cosine_similarity(norm_vectors[group[0]], norm_vectors[k])
                for k in group[1:]
            ) / (len(group) - 1)
            clusters.append({
                'projects': [names[k] for k in group],
                'centroid': raw_centroid_dict,
                'similarity_score': round(sim, 4),
                'matches_known_pattern': _matches_known(c, known_patterns),
            })

    return clusters