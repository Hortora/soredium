#!/usr/bin/env python3
"""route_submission.py — Find the correct local garden for a given domain.

Usage:
  route_submission.py <domain> [--config PATH]

Prints the absolute local path of the garden that owns the domain.
Exit codes: 0 = found, 1 = not found or error
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from garden_config import load_config, resolve_paths, find_garden_for_domain

DEFAULT_CONFIG = Path.home() / '.claude' / 'garden-config.toml'


def route(domain: str, gardens: list) -> Path | None:
    """Return local Path of the garden owning this domain, or None."""
    result = find_garden_for_domain(gardens, domain)
    if result is None:
        return None
    return Path(result['path'])


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('domain', help='Domain to route (e.g. java, quarkus, tools)')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()

    try:
        gardens = load_config(args.config)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    gardens = resolve_paths(gardens)
    result = route(args.domain, gardens)

    if result is None:
        print(f"No garden found for domain: {args.domain!r}")
        sys.exit(1)

    print(str(result.resolve()))
    sys.exit(0)


if __name__ == '__main__':
    main()
