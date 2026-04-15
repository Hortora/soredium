#!/usr/bin/env python3
"""
Garden integrity validator.

Checks:
1. Every entry in garden files has **ID:** GE-XXXX
2. All GE-IDs are unique across the garden
3. Every GARDEN.md index entry with GE-ID prefix points to an existing entry
4. GARDEN.md counter >= highest GE-ID found in garden files
5. Every GE-ID in a garden file appears in the By Technology section (not just By Label)
6. CHECKED.md pairs reference only valid GE-IDs
7. DISCARDED.md entries reference valid submission GE-IDs
8. Submission files in submissions/ include Submission ID header

Usage: python3 validate_garden.py [garden_root] [--verbose]
       garden_root defaults to $HORTORA_GARDEN or ~/.hortora/garden

Exit codes: 0=clean, 1=errors found, 2=warnings only
"""

import re
import sys
from pathlib import Path

# --structural <garden_root>: early-exit structural check
if '--structural' in sys.argv:
    _idx = sys.argv.index('--structural')
    if _idx + 1 >= len(sys.argv):
        print('ERROR: --structural requires a GARDEN_ROOT argument', file=sys.stderr)
        sys.exit(1)
    _garden = Path(sys.argv[_idx + 1]).expanduser().resolve()
    _errors = []
    if not (_garden / 'GARDEN.md').exists():
        _errors.append('Missing GARDEN.md')
    if not (_garden / '_index' / 'global.md').exists():
        _errors.append('Missing _index/global.md')
    if _errors:
        for _e in _errors:
            print(f'ERROR: {_e}', file=sys.stderr)
        sys.exit(1)
    print('Structural check passed')
    sys.exit(0)

if '--freshness' in sys.argv:
    import os as _os
    from datetime import date as _date
    import re as _re

    _idx = sys.argv.index('--freshness')
    # Garden root: next positional arg if present, else $HORTORA_GARDEN or default
    if _idx + 1 < len(sys.argv) and not sys.argv[_idx + 1].startswith('--'):
        _garden = Path(sys.argv[_idx + 1]).expanduser().resolve()
    elif 'HORTORA_GARDEN' in _os.environ:
        _garden = Path(_os.environ['HORTORA_GARDEN']).expanduser().resolve()
    else:
        _garden = (Path.home() / '.hortora' / 'garden').resolve()

    _today = _date.today()
    _overdue = []
    _exclude = {'.git', 'submissions', 'scripts'}
    _skip_names = {'GARDEN.md', 'CHECKED.md', 'DISCARDED.md'}

    for _path in _garden.rglob('*.md'):
        if any(part in _exclude for part in _path.parts):
            continue
        if _path.name in _skip_names:
            continue
        _content = _path.read_text()
        _content_normalized = _content.replace('\r\n', '\n')
        _fm_match = _re.match(r'^---\n(.*?)\n---', _content_normalized, _re.DOTALL)
        if not _fm_match:
            continue
        _fm = _fm_match.group(1)

        _t = _re.search(r'staleness_threshold:\s*(\d+)', _fm)
        if not _t:
            continue
        _threshold = int(_t.group(1))

        _s = _re.search(r'submitted:\s*(\d{4}-\d{2}-\d{2})', _fm)
        if not _s:
            continue
        try:
            _submitted = _date.fromisoformat(_s.group(1))
            _r = _re.search(r'last_reviewed:\s*(\d{4}-\d{2}-\d{2})', _fm)
            _last_reviewed = _date.fromisoformat(_r.group(1)) if _r else None
        except ValueError:
            continue

        _ref = max(_submitted, _last_reviewed) if _last_reviewed else _submitted
        _age = (_today - _ref).days

        if _age > _threshold:
            _id_m = _re.search(r'^id:\s*(.+)$', _fm, _re.MULTILINE)
            _ti_m = _re.search(r'^title:\s*"?(.+?)"?\s*$', _fm, _re.MULTILINE)
            _overdue.append((
                _id_m.group(1).strip() if _id_m else 'unknown',
                _ti_m.group(1).strip().strip('"') if _ti_m else 'unknown',
                _age,
                _threshold,
            ))

    _overdue.sort(key=lambda x: x[2], reverse=True)
    print(f"Freshness check: {len(_overdue)} entries past staleness threshold")
    for _ge_id, _entry_title, _age, _thresh in _overdue[:10]:
        print(f"  {_ge_id}: {_entry_title[:60]} ({_age}d / {_thresh}d threshold)")
    if len(_overdue) > 10:
        print(f"  ... and {len(_overdue) - 10} more")
    sys.exit(2 if _overdue else 0)

if '--dedupe-check' in sys.argv:
    import os as _os
    import re as _re
    import subprocess as _sp

    _idx = sys.argv.index('--dedupe-check')
    if _idx + 1 < len(sys.argv) and not sys.argv[_idx + 1].startswith('--'):
        _garden = Path(sys.argv[_idx + 1]).expanduser().resolve()
    elif 'HORTORA_GARDEN' in _os.environ:
        _garden = Path(_os.environ['HORTORA_GARDEN']).expanduser().resolve()
    else:
        _garden = (Path.home() / '.hortora' / 'garden').resolve()

    _drift = 0
    _threshold = 10
    _garden_md = _garden / 'GARDEN.md'
    if _garden_md.exists():
        _content = _garden_md.read_text()
        _m = _re.search(r'\*\*Entries merged since last sweep:\*\*\s*(\d+)', _content)
        if _m:
            _drift = int(_m.group(1))
        _t = _re.search(r'\*\*Drift threshold:\*\*\s*(\d+)', _content)
        if _t:
            _threshold = int(_t.group(1))

    # Cross-check with git log — count 'index: integrate' commits since last 'dedupe:' commit
    try:
        _log = _sp.run(
            ['git', '-C', str(_garden), 'log', '--format=%s'],
            capture_output=True, text=True, check=True
        ).stdout.strip().splitlines()
        _git_count = 0
        for _line in _log:
            if _line.startswith('dedupe:'):
                break
            if _line.startswith('index: integrate'):
                _git_count += 1
        if _git_count > _drift:
            _drift = _git_count
    except Exception:
        pass  # not a git repo or git unavailable — use counter only

    if _drift >= _threshold:
        print(f"Dedupe check: drift={_drift}, threshold={_threshold} — DEDUPE recommended")
        sys.exit(2)
    else:
        print(f"Dedupe check: drift={_drift}, threshold={_threshold} — OK")
        sys.exit(0)

if '--check-db' in sys.argv:
    import sqlite3 as _sqlite3

    _idx = sys.argv.index('--check-db')
    if _idx + 1 < len(sys.argv) and not sys.argv[_idx + 1].startswith('--'):
        _garden = Path(sys.argv[_idx + 1]).expanduser().resolve()
    else:
        import os as _os2
        _garden = Path(_os2.environ.get('HORTORA_GARDEN',
                       str(Path.home() / '.hortora' / 'garden'))).resolve()

    _db_path = _garden / 'garden.db'
    if not _db_path.exists():
        print(f"ERROR: garden.db not found in {_garden}")
        sys.exit(1)

    try:
        _conn = _sqlite3.connect(str(_db_path))
        _version = _conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if not _version:
            print("ERROR: schema_version table empty — garden.db may be uninitialised")
            _conn.close()
            sys.exit(1)
        _checked = _conn.execute("SELECT COUNT(*) FROM checked_pairs").fetchone()[0]
        _discarded = _conn.execute("SELECT COUNT(*) FROM discarded_entries").fetchone()[0]
        _indexed = _conn.execute("SELECT COUNT(*) FROM entries_index").fetchone()[0]
        _conn.close()
        print(f"garden.db OK — schema version {_version[0]}")
        print(f"  checked pairs:     {_checked}")
        print(f"  discarded entries: {_discarded}")
        print(f"  entries indexed:   {_indexed}")
        sys.exit(0)
    except _sqlite3.DatabaseError as _e:
        print(f"ERROR: garden.db is corrupt or unreadable: {_e}")
        sys.exit(1)

import os
# Garden root: first non-flag positional argument, $HORTORA_GARDEN env var, or default
_args = [a for a in sys.argv[1:] if not a.startswith('--')]
_default = Path(os.environ['HORTORA_GARDEN']).expanduser() if 'HORTORA_GARDEN' in os.environ else Path.home() / '.hortora' / 'garden'
GARDEN_ROOT = Path(_args[0]).expanduser().resolve() if _args else _default.resolve()

GARDEN_MD = GARDEN_ROOT / "GARDEN.md"
CHECKED_MD = GARDEN_ROOT / "CHECKED.md"
DISCARDED_MD = GARDEN_ROOT / "DISCARDED.md"
SUBMISSIONS_DIR = GARDEN_ROOT / "submissions"
EXCLUDE_DIRS = {'.git', 'submissions', 'scripts'}

# Legacy format: GE-NNNN (sequential counter, entries GE-0001 through GE-0172)
# New format: GE-YYYYMMDD-xxxxxx (date + 6 hex chars, ADR-0003)
GE_ID_LEGACY = r'GE-\d{4}'
GE_ID_NEW = r'GE-\d{8}-[0-9a-f]{6}'
GE_ID_ANY = rf'(?:{GE_ID_NEW}|{GE_ID_LEGACY})'  # new format first — prevents GE-\d{4} greedily matching prefix of GE-YYYYMMDD-xxxxxx
GE_ID_PATTERN = re.compile(GE_ID_ANY)

errors = []
warnings = []
info = []
verbose = '--verbose' in sys.argv


def log_error(msg):
    errors.append(f"ERROR: {msg}")

def log_warning(msg):
    warnings.append(f"WARNING: {msg}")

def log_info(msg):
    if verbose:
        info.append(f"  {msg}")


def get_garden_counter() -> int | None:
    """Read Last assigned ID from GARDEN.md metadata."""
    if not GARDEN_MD.exists():
        log_error("GARDEN.md not found")
        return None
    content = GARDEN_MD.read_text()
    m = re.search(r'\*\*(?:Last legacy ID|Last assigned ID):\*\*\s*(GE-(\d{4}))', content)
    if not m:
        log_error("GARDEN.md has no 'Last assigned ID' metadata")
        return None
    return int(m.group(2))


def get_garden_index_ids() -> dict[str, str]:
    """Return {ge_id: entry_title} from GARDEN.md index lines (all sections)."""
    if not GARDEN_MD.exists():
        return {}
    results = {}
    content = GARDEN_MD.read_text()
    for m in re.finditer(rf'-\s+({GE_ID_ANY})\s+\[([^\]]+)\]', content):
        results[m.group(1)] = m.group(2)
    return results


def get_by_technology_ids() -> set[str]:
    """Return GE-IDs that appear in the By Technology section of GARDEN.md."""
    if not GARDEN_MD.exists():
        return set()
    content = GARDEN_MD.read_text()
    m = re.search(r'## By Technology\n(.*?)(?:\n---)', content, re.DOTALL)
    if not m:
        return set()
    return set(re.findall(GE_ID_ANY, m.group(1)))


def strip_code_fences(content: str) -> str:
    """Remove content inside fenced code blocks (``` or ~~~) to avoid false positives."""
    return re.sub(r'```.*?```', '', content, flags=re.DOTALL) \
             .replace('\n~~~', '\n```')  # normalise tildes then strip remaining


def scan_garden_entry_ids() -> dict[str, list[str]]:
    """Scan all garden files (not submissions) for **ID:** GE-XXXX.

    Strips fenced code blocks first so that GE-IDs used as examples inside
    code snippets are not counted as real entry IDs.
    """
    all_ids: dict[str, list[str]] = {}
    for path in GARDEN_ROOT.rglob("*.md"):
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if path.name in ("GARDEN.md", "CHECKED.md", "DISCARDED.md"):
            continue
        content = strip_code_fences(path.read_text())
        for m in re.finditer(rf'^\*\*ID:\*\*\s+({GE_ID_ANY})', content, re.MULTILINE):
            ge_id = m.group(1)
            all_ids.setdefault(ge_id, []).append(str(path.relative_to(GARDEN_ROOT)))
    return all_ids


def get_checked_pairs() -> list[tuple[str, str]]:
    """Return list of (id_a, id_b) pairs from CHECKED.md."""
    if not CHECKED_MD.exists():
        return []
    pairs = []
    content = CHECKED_MD.read_text()
    for m in re.finditer(rf'\|\s*({GE_ID_ANY})\s*[×x]\s*({GE_ID_ANY})\s*\|', content):
        pairs.append((m.group(1), m.group(2)))
    return pairs


def get_discarded_ids() -> list[tuple[str, str]]:
    """Return list of (discarded_ge_id, conflicts_with_ge_id) from DISCARDED.md."""
    if not DISCARDED_MD.exists():
        return []
    results = []
    content = DISCARDED_MD.read_text()
    for m in re.finditer(rf'\|\s*({GE_ID_ANY})\s*\|\s*({GE_ID_ANY})\s*\|', content):
        results.append((m.group(1), m.group(2)))
    return results


def get_submission_ids() -> dict[str, str]:
    """Return {ge_id: filename} for submissions that declare a Submission ID."""
    results = {}
    if not SUBMISSIONS_DIR.exists():
        return results
    for path in SUBMISSIONS_DIR.glob("*.md"):
        content = path.read_text()
        m = re.search(rf'^\*\*Submission ID:\*\*\s+({GE_ID_ANY})', content, re.MULTILINE)
        if m:
            results[m.group(1)] = path.name
    return results


def validate():
    print(f"Validating garden at {GARDEN_ROOT}\n")

    # 0. Validate SCHEMA.md if present (federation config)
    _schema_path = GARDEN_MD.parent / 'SCHEMA.md'
    if _schema_path.exists():
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            'validate_schema',
            Path(__file__).parent / 'validate_schema.py'
        )
        _vs = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_vs)
        _schema_content = _schema_path.read_text(encoding='utf-8')
        _schema = _vs.parse_schema(_schema_content)
        if _schema is None:
            log_error("SCHEMA.md has no YAML frontmatter")
        else:
            _s_errors, _s_warnings = _vs.validate_schema(_schema)
            for _e in _s_errors:
                log_error(f"SCHEMA.md: {_e}")
            for _w in _s_warnings:
                log_info(f"SCHEMA.md: {_w}")

    # 1. Scan garden entry IDs
    entry_ids = scan_garden_entry_ids()
    log_info(f"Found {len(entry_ids)} GE-IDs in garden entries")

    # 2. Check uniqueness
    for ge_id, files in entry_ids.items():
        if len(files) > 1:
            log_error(f"{ge_id} appears in multiple files: {', '.join(files)}")

    # 3. Check counter consistency (legacy GE-NNNN IDs only — new GE-YYYYMMDD-xxxxxx IDs are counter-free)
    legacy_ids = [gid for gid in entry_ids if re.fullmatch(r'GE-\d{4}', gid)]
    counter = get_garden_counter()
    if counter is not None and legacy_ids:
        highest = max(int(gid[3:]) for gid in legacy_ids)
        if counter < highest:
            log_error(f"GARDEN.md counter GE-{counter:04d} is BELOW highest legacy entry ID GE-{highest:04d}")
        else:
            log_info(f"Counter GE-{counter:04d} >= highest legacy entry GE-{highest:04d} ✓")

    # 4. Check GARDEN.md index vs actual entries (whole index)
    index_ids = get_garden_index_ids()
    log_info(f"Found {len(index_ids)} GE-IDs in GARDEN.md index")
    for ge_id, title in index_ids.items():
        if ge_id not in entry_ids:
            log_error(f"Index references {ge_id} ({title!r}) but no matching **ID:** in any garden file")
    for ge_id in entry_ids:
        if ge_id not in index_ids:
            log_warning(f"{ge_id} exists in a garden file but is missing from GARDEN.md index")

    # 4b. Check By Technology section specifically
    # Appearing in By Label or By Symptom/Type alone is not sufficient
    tech_ids = get_by_technology_ids()
    log_info(f"Found {len(tech_ids)} GE-IDs in By Technology section")
    for ge_id in entry_ids:
        if ge_id not in tech_ids:
            log_error(f"{ge_id} is missing from GARDEN.md By Technology section"
                      f" (By Label/Symptom alone is not sufficient)")

    # 5. Check CHECKED.md pairs reference valid IDs
    all_known_ids = set(entry_ids.keys()) | set(get_submission_ids().keys())
    for id_a, id_b in get_checked_pairs():
        if id_a not in all_known_ids:
            log_warning(f"CHECKED.md references {id_a} which is not in garden entries or submissions")
        if id_b not in all_known_ids:
            log_warning(f"CHECKED.md references {id_b} which is not in garden entries or submissions")

    # 6. Check DISCARDED.md conflicts point to real entries
    for discarded, conflicts_with in get_discarded_ids():
        if conflicts_with not in entry_ids:
            log_error(f"DISCARDED.md: {discarded} conflicts with {conflicts_with} but {conflicts_with} not found in garden")

    # 7. Check submissions have IDs
    if SUBMISSIONS_DIR.exists():
        sub_files = list(SUBMISSIONS_DIR.glob("*.md"))
        missing_id = [f.name for f in sub_files
                      if not re.search(r'\*\*Submission ID:\*\*', f.read_text())]
        if missing_id:
            log_warning(f"Submissions missing Submission ID header: {', '.join(missing_id)}")

    # Report
    print("\n".join(info))
    if errors:
        print()
        for e in errors:
            print(e)
    if warnings:
        print()
        for w in warnings:
            print(w)
    if not errors and not warnings:
        print("✅ Garden integrity check passed — no issues found")
    elif not errors:
        print(f"\n⚠️  {len(warnings)} warning(s), no errors")
    else:
        print(f"\n❌ {len(errors)} error(s), {len(warnings)} warning(s)")

    if errors:
        sys.exit(1)
    elif warnings:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    validate()
