"""Cluster pipeline feature extraction and processing."""
import math

FEATURE_KEYS = ['interface_count', 'abstraction_depth', 'injection_points',
                'extension_signatures', 'file_count', 'spi_patterns']


def fingerprint_to_vector(fp: dict) -> list[float]:
    """Convert feature fingerprint to normalized vector."""
    return [float(fp.get(key, 0.0)) for key in FEATURE_KEYS]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _centroid(fingerprints: list[dict]) -> dict:
    """Return the mean fingerprint across a list of fingerprints."""
    result = {}
    for key in FEATURE_KEYS:
        result[key] = sum(fp.get(key, 0.0) for fp in fingerprints) / len(fingerprints)
    return result


def _match_known_pattern(centroid: dict, known_patterns: list[dict], threshold: float = 0.9) -> str | None:
    vec = fingerprint_to_vector(centroid)
    for pattern in known_patterns:
        known_vec = fingerprint_to_vector(pattern.get('signature', {}))
        if _cosine_similarity(vec, known_vec) >= threshold:
            return pattern.get('name')
    return None


def cluster_projects(
    fingerprints: dict[str, dict],
    known_patterns: list[dict],
    similarity_threshold: float = 0.95,
) -> list[dict]:
    """Cluster projects by feature similarity. Returns candidate clusters with >= 2 members."""
    names = list(fingerprints.keys())
    if len(names) < 2:
        return []

    vectors = {name: fingerprint_to_vector(fingerprints[name]) for name in names}

    # Greedy single-linkage clustering
    visited: set[str] = set()
    clusters: list[list[str]] = []

    for i, name in enumerate(names):
        if name in visited:
            continue
        cluster = [name]
        visited.add(name)
        for other in names[i + 1:]:
            if other in visited:
                continue
            # Complete-linkage: other must be similar to every existing cluster member
            if all(
                _cosine_similarity(vectors[other], vectors[member]) >= similarity_threshold
                for member in cluster
            ):
                cluster.append(other)
                visited.add(other)
        if len(cluster) >= 2:
            clusters.append(cluster)

    results = []
    for cluster in clusters:
        fps = [fingerprints[n] for n in cluster]
        c = _centroid(fps)
        vecs = [vectors[n] for n in cluster]
        # similarity_score: mean pairwise similarity
        pairs = [(i, j) for i in range(len(vecs)) for j in range(i + 1, len(vecs))]
        score = (
            sum(_cosine_similarity(vecs[i], vecs[j]) for i, j in pairs) / len(pairs)
            if pairs else 1.0
        )
        results.append({
            'projects': cluster,
            'centroid': c,
            'similarity_score': score,
            'matches_known_pattern': _match_known_pattern(c, known_patterns),
        })
    return results
