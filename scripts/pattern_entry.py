"""Generate patterns-garden entry skeleton from an accepted cluster candidate."""
import secrets
from datetime import date
from pathlib import Path
import yaml

SKELETON_SECTIONS = [
    'Pattern description',
    'When to use',
    'When not to use',
    'Variants',
]


def _make_id() -> str:
    today = date.today().strftime('%Y%m%d')
    return f"GP-{today}-{secrets.token_hex(3)}"


def generate_skeleton(cluster: dict, registry_projects: list[dict]) -> str:
    project_index = {p['project']: p for p in registry_projects}

    observed_in = []
    for name in cluster['projects']:
        reg = project_index.get(name, {})
        observed_in.append({
            'project': name,
            'url': reg.get('url', ''),
        })

    frontmatter = {
        'id': _make_id(),
        'garden': 'patterns',
        'title': '',
        'type': 'architectural',
        'domain': 'jvm',
        'tags': [],
        'score': 10,
        'verified': False,
        'staleness_threshold': 730,
        'submitted': str(date.today()),
        'observed_in': observed_in,
    }

    body_sections = '\n\n'.join(
        f'### {s}\n<!-- {s} -->' for s in SKELETON_SECTIONS
    )

    return f"---\n{yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)}---\n\n{body_sections}\n"


def write_skeleton(cluster: dict, registry_projects: list[dict], out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    skeleton = generate_skeleton(cluster, registry_projects)
    entry_id = yaml.safe_load(skeleton.split('---\n')[1])['id']
    path = out_dir / f"{entry_id}.md"
    path.write_text(skeleton)
    return path