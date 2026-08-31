"""Documentation freshness detection — shared by work-end gate and CI Action."""

import json
import os
import sys
from dataclasses import dataclass, field


def parse_anchors(filepath: str) -> dict | None:
    """Parse YAML frontmatter with structural anchors from a markdown file."""
    with open(filepath, 'r') as f:
        content = f.read()

    if not content.startswith('---'):
        return None

    close = content.find('\n---', 3)
    if close < 0:
        return None

    fm_block = content[4:close].strip()
    result = _parse_yaml_frontmatter(fm_block)
    result.setdefault('anchors', {})
    return result


def _parse_yaml_frontmatter(block: str) -> dict:
    """Minimal YAML parser for frontmatter — handles flat keys and one level of nesting."""
    result = {}
    current_key = None
    current_list_key = None

    for line in block.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue

        indent = len(line) - len(line.lstrip())

        if indent == 0 and ':' in stripped:
            key, _, value = stripped.partition(':')
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if value:
                result[key] = value
                current_key = None
                current_list_key = None
            else:
                current_key = key
                if key not in result:
                    result[key] = {}
                current_list_key = None

        elif indent > 0 and current_key is not None:
            if stripped.startswith('- '):
                item = stripped[2:].strip()
                if current_list_key and current_key in result and isinstance(result[current_key], dict):
                    result[current_key].setdefault(current_list_key, [])
                    result[current_key][current_list_key].append(item)
            elif ':' in stripped:
                sub_key, _, sub_value = stripped.partition(':')
                sub_key = sub_key.strip()
                sub_value = sub_value.strip()
                if not sub_value:
                    current_list_key = sub_key
                    if isinstance(result.get(current_key), dict):
                        result[current_key].setdefault(sub_key, [])
                else:
                    if isinstance(result.get(current_key), dict):
                        result[current_key][sub_key] = sub_value

    return result


@dataclass
class AnchoredDoc:
    path: str
    capability: str
    audience: str
    repo: str
    anchors: dict = field(default_factory=dict)
    verified_current: str | None = None


def find_anchored_docs(docs_dir: str) -> list[AnchoredDoc]:
    """Scan a docs directory for files with structural anchor frontmatter."""
    results = []
    for root, _, files in os.walk(docs_dir):
        for fname in sorted(files):
            if not fname.endswith('.md'):
                continue
            fpath = os.path.join(root, fname)
            parsed = parse_anchors(fpath)
            if parsed and parsed.get('anchors'):
                results.append(AnchoredDoc(
                    path=os.path.relpath(fpath, docs_dir),
                    capability=parsed.get('capability', ''),
                    audience=parsed.get('audience', ''),
                    repo=parsed.get('repo', ''),
                    anchors=parsed.get('anchors', {}),
                    verified_current=parsed.get('verified-current'),
                ))
    return results


@dataclass
class StaleCandidate:
    doc_path: str
    capability: str
    anchor_type: str
    anchor_value: str
    changed_file: str
    reason: str


def detect_stale(diff_files: list[str], anchored_docs: list[AnchoredDoc]) -> list[StaleCandidate]:
    """Match changed files against structural anchors to find candidate-stale sections."""
    candidates = []

    for doc in anchored_docs:
        if doc.verified_current:
            continue

        for anchor_type, anchor_values in doc.anchors.items():
            for anchor in anchor_values:
                for changed in diff_files:
                    if _anchor_matches_file(anchor, anchor_type, changed):
                        candidates.append(StaleCandidate(
                            doc_path=doc.path,
                            capability=doc.capability,
                            anchor_type=anchor_type,
                            anchor_value=anchor,
                            changed_file=changed,
                            reason=f"{anchor_type} anchor '{anchor}' matches changed file '{changed}'"
                        ))

    seen = set()
    deduped = []
    for c in candidates:
        key = (c.doc_path, c.anchor_value)
        if key not in seen:
            seen.add(key)
            deduped.append(c)

    return deduped


def _anchor_matches_file(anchor: str, anchor_type: str, changed_file: str) -> bool:
    """Check if a structural anchor matches a changed file path."""
    if anchor_type in ('classes', 'spis'):
        expected_path = anchor.replace('.', '/') + '.java'
        alt_path = anchor.replace('.', '/') + '.kt'
        return changed_file.endswith(expected_path) or changed_file.endswith(alt_path)

    elif anchor_type == 'config-keys':
        config_files = ('application.properties', 'application.yaml', 'application.yml')
        return any(changed_file.endswith(cf) for cf in config_files)

    elif anchor_type == 'protocols':
        return anchor in changed_file

    return False


def main():
    """CLI entry point. Usage: doc_freshness_check.py --diff <file> --docs <dir> [--graph <file>]"""
    import argparse
    parser = argparse.ArgumentParser(description='Documentation freshness detection')
    parser.add_argument('--diff', required=True, help='File containing list of changed files (one per line)')
    parser.add_argument('--docs', required=True, help='Path to docs directory')
    parser.add_argument('--graph', help='Path to dependency-graph.json (for dependent repo checks)')
    parser.add_argument('--repo', help='Current repo name (for cross-repo filtering)')
    args = parser.parse_args()

    with open(args.diff) as f:
        diff_files = [line.strip() for line in f if line.strip()]

    anchored = find_anchored_docs(args.docs)
    candidates = detect_stale(diff_files, anchored)

    output = {
        'candidates': [
            {
                'doc_path': c.doc_path,
                'capability': c.capability,
                'anchor_type': c.anchor_type,
                'anchor_value': c.anchor_value,
                'changed_file': c.changed_file,
                'reason': c.reason,
            }
            for c in candidates
        ],
        'total_anchored_docs': len(anchored),
        'total_candidates': len(candidates),
    }

    print(json.dumps(output, indent=2))
    return 1 if candidates else 0


if __name__ == '__main__':
    sys.exit(main())
