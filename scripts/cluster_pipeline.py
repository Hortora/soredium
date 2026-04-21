"""Cluster pipeline feature extraction and processing."""

FEATURE_KEYS = ['interface_count', 'abstraction_depth', 'injection_points', 
                'extension_signatures', 'file_count', 'spi_patterns']


def fingerprint_to_vector(fp: dict) -> list[float]:
    """Convert feature fingerprint to normalized vector."""
    return [float(fp.get(key, 0.0)) for key in FEATURE_KEYS]
