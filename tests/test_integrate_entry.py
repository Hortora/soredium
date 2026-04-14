import pytest
import re
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from integrate_entry import integrate, generate_summary, parse_entry

VALID_ENTRY = """\
---
id: GE-0123
title: "Quarkus CDI: @UnlessBuildProfile fails in consumers"
type: gotcha
domain: quarkus/cdi
score: 13
tags: [quarkus, cdi, build-profile]
verified: 2026-04-09
staleness_threshold: 180
summary: "@UnlessBuildProfile causes Unsatisfied dependency"
---

Body text.
"""

NEW_FORMAT_ENTRY = """\
---
id: GE-20260410-5fd0c3
title: "validate_garden.py strip_code_fences false positive"
type: gotcha
domain: tools/hortora
score: 12
tags: [hortora, validator]
---

Body text.
"""

LEGACY_MARKDOWN_ENTRY = """\
## Some legacy entry title

**ID:** GE-0042
**Stack:** some-tool

Body text without YAML frontmatter.
"""


def _garden_with_drift(tmp_path, drift: int = 0) -> Path:
    """Fixture: minimal garden with GARDEN.md drift counter."""
    domain = tmp_path / 'quarkus' / 'cdi'
    domain.mkdir(parents=True)
    (domain / 'INDEX.md').write_text(
        '| GE-ID | Title | Type | Score |\n|-------|-------|------|-------|\n'
    )
    (tmp_path / '_index').mkdir()
    (tmp_path / '_index' / 'global.md').write_text(
        '| Domain | Index |\n|--------|-------|\n'
    )
    (tmp_path / 'GARDEN.md').write_text(
        f'**Last legacy ID:** GE-0001\n'
        f'**Last full DEDUPE sweep:** 2026-04-14\n'
        f'**Entries merged since last sweep:** {drift}\n'
        f'**Drift threshold:** 10\n'
    )
    return tmp_path


class TestDriftCounter:

    def _run(self, entry, garden):
        with patch('integrate_entry.run_validate'), \
             patch('integrate_entry.git_commit'):
            return integrate(str(entry), str(garden))

    def test_drift_counter_increments_from_zero(self, tmp_path):
        garden = _garden_with_drift(tmp_path, drift=0)
        entry = garden / 'quarkus' / 'cdi' / 'GE-0123.md'
        entry.write_text(VALID_ENTRY)
        self._run(entry, garden)
        content = (garden / 'GARDEN.md').read_text()
        m = re.search(r'\*\*Entries merged since last sweep:\*\*\s*(\d+)', content)
        assert m and int(m.group(1)) == 1

    def test_drift_counter_increments_from_nonzero(self, tmp_path):
        garden = _garden_with_drift(tmp_path, drift=3)
        entry = garden / 'quarkus' / 'cdi' / 'GE-0123.md'
        entry.write_text(VALID_ENTRY)
        self._run(entry, garden)
        content = (garden / 'GARDEN.md').read_text()
        m = re.search(r'\*\*Entries merged since last sweep:\*\*\s*(\d+)', content)
        assert m and int(m.group(1)) == 4

    def test_drift_counter_missing_field_no_crash(self, tmp_path):
        domain = tmp_path / 'quarkus' / 'cdi'
        domain.mkdir(parents=True)
        (domain / 'INDEX.md').write_text('| GE-ID | Title | Type | Score |\n|-------|-------|------|-------|\n')
        (tmp_path / '_index').mkdir()
        (tmp_path / '_index' / 'global.md').write_text('| Domain | Index |\n|--------|-------|\n')
        (tmp_path / 'GARDEN.md').write_text('**Last legacy ID:** GE-0001\n')
        entry = domain / 'GE-0123.md'
        entry.write_text(VALID_ENTRY)
        result = self._run(entry, tmp_path)
        assert result['status'] == 'ok'

    def test_no_garden_md_no_crash(self, tmp_path):
        domain = tmp_path / 'quarkus' / 'cdi'
        domain.mkdir(parents=True)
        (domain / 'INDEX.md').write_text('| GE-ID | Title | Type | Score |\n|-------|-------|------|-------|\n')
        (tmp_path / '_index').mkdir()
        (tmp_path / '_index' / 'global.md').write_text('| Domain | Index |\n|--------|-------|\n')
        entry = domain / 'GE-0123.md'
        entry.write_text(VALID_ENTRY)
        result = self._run(entry, tmp_path)
        assert result['status'] == 'ok'

    def test_other_garden_md_fields_preserved(self, tmp_path):
        garden = _garden_with_drift(tmp_path, drift=0)
        entry = garden / 'quarkus' / 'cdi' / 'GE-0123.md'
        entry.write_text(VALID_ENTRY)
        self._run(entry, garden)
        content = (garden / 'GARDEN.md').read_text()
        assert '**Last legacy ID:** GE-0001' in content
        assert '**Drift threshold:** 10' in content


@pytest.fixture
def garden(tmp_path):
    domain = tmp_path / "quarkus" / "cdi"
    domain.mkdir(parents=True)
    (domain / "INDEX.md").write_text(
        "| GE-ID | Title | Type | Score |\n|-------|-------|------|-------|\n"
    )
    (tmp_path / "_index").mkdir()
    (tmp_path / "_index" / "global.md").write_text(
        "| Domain | Index |\n|--------|-------|\n"
    )
    return tmp_path


@pytest.fixture
def entry(garden):
    f = garden / "quarkus" / "cdi" / "GE-0123.md"
    f.write_text(VALID_ENTRY)
    return f


def _run(entry, garden):
    """Run integrate with all side-effect functions mocked."""
    with patch('integrate_entry.run_validate'), \
         patch('integrate_entry.git_commit'):
        return integrate(str(entry), str(garden))


def test_summary_file_created(garden, entry):
    _run(entry, garden)
    summary = garden / "_summaries" / "quarkus" / "cdi" / "GE-0123.md"
    assert summary.exists()
    assert "GE-0123" in summary.read_text()


def test_domain_index_updated(garden, entry):
    _run(entry, garden)
    content = (garden / "quarkus" / "cdi" / "INDEX.md").read_text()
    assert "GE-0123" in content


def test_labels_updated_for_each_tag(garden, entry):
    _run(entry, garden)
    for tag in ['quarkus', 'cdi', 'build-profile']:
        label_file = garden / "labels" / f"{tag}.md"
        assert label_file.exists(), f"Missing label file for tag '{tag}'"
        assert "GE-0123" in label_file.read_text()


def test_new_domain_added_to_global_index(tmp_path):
    (tmp_path / "_index").mkdir()
    (tmp_path / "_index" / "global.md").write_text("| Domain | Index |\n|--------|-------|\n")
    domain = tmp_path / "newdomain" / "sub"
    domain.mkdir(parents=True)
    (domain / "INDEX.md").write_text("| GE-ID | Title | Type | Score |\n|-------|-------|------|-------|\n")
    entry = domain / "GE-0001.md"
    entry.write_text(VALID_ENTRY.replace('domain: quarkus/cdi', 'domain: newdomain/sub')
                                .replace('id: GE-0123', 'id: GE-0001'))
    with patch('integrate_entry.run_validate'), \
         patch('integrate_entry.git_commit'):
        integrate(str(entry), str(tmp_path))
    assert "newdomain" in (tmp_path / "_index" / "global.md").read_text()


def test_ge_id_from_frontmatter_wins_over_filename(garden):
    """ID in frontmatter must be used, not the filename stem."""
    # File is named GE-9999.md but frontmatter says GE-0123
    misnamed = garden / "quarkus" / "cdi" / "GE-9999.md"
    misnamed.write_text(VALID_ENTRY)  # VALID_ENTRY has id: GE-0123
    result = _run(misnamed, garden)
    assert result['ge_id'] == 'GE-0123'
    # Summary written under GE-0123, not GE-9999
    assert (garden / "_summaries" / "quarkus" / "cdi" / "GE-0123.md").exists()
    assert not (garden / "_summaries" / "quarkus" / "cdi" / "GE-9999.md").exists()


def test_ge_id_falls_back_to_filename_when_no_frontmatter_id(garden):
    """When frontmatter has no id field, filename stem is used."""
    entry_no_id = VALID_ENTRY.replace('id: GE-0123\n', '')
    f = garden / "quarkus" / "cdi" / "GE-0123.md"
    f.write_text(entry_no_id)
    result = _run(f, garden)
    assert result['ge_id'] == 'GE-0123'


def test_new_format_id_used_correctly(tmp_path):
    """GE-YYYYMMDD-xxxxxx from frontmatter is used verbatim."""
    domain = tmp_path / "tools" / "hortora"
    domain.mkdir(parents=True)
    (domain / "INDEX.md").write_text("| GE-ID | Title | Type | Score |\n|-------|-------|------|-------|\n")
    (tmp_path / "_index").mkdir()
    (tmp_path / "_index" / "global.md").write_text("| Domain | Index |\n|--------|-------|\n")
    entry = domain / "GE-20260410-5fd0c3.md"
    entry.write_text(NEW_FORMAT_ENTRY)
    with patch('integrate_entry.run_validate'), \
         patch('integrate_entry.git_commit'):
        result = integrate(str(entry), str(tmp_path))
    assert result['ge_id'] == 'GE-20260410-5fd0c3'
    assert (tmp_path / "_summaries" / "tools" / "hortora" / "GE-20260410-5fd0c3.md").exists()


def test_legacy_markdown_entry_no_crash(tmp_path):
    """Entries without YAML frontmatter are handled gracefully (no crash)."""
    domain = tmp_path / "tools"
    domain.mkdir(parents=True)
    (domain / "INDEX.md").write_text("| GE-ID | Title | Type | Score |\n|-------|-------|------|-------|\n")
    (tmp_path / "_index").mkdir()
    (tmp_path / "_index" / "global.md").write_text("| Domain | Index |\n|--------|-------|\n")
    entry = domain / "GE-0042.md"
    entry.write_text(LEGACY_MARKDOWN_ENTRY)
    with patch('integrate_entry.run_validate'), \
         patch('integrate_entry.git_commit'):
        result = integrate(str(entry), str(tmp_path))
    # Falls back to filename stem
    assert result['ge_id'] == 'GE-0042'


def test_generate_summary_format():
    fm = {'title': 'Test title', 'type': 'gotcha', 'score': 12,
          'tags': ['quarkus', 'cdi', 'extra-tag']}
    s = generate_summary(fm, 'GE-0001')
    assert 'GE-0001' in s
    assert 'gotcha' in s
    assert '12/15' in s
    assert 'quarkus' in s


def test_parse_entry_with_frontmatter():
    entry = Path("/tmp/test.md")
    entry.write_text(VALID_ENTRY)
    fm, body = parse_entry(entry)
    assert fm['id'] == 'GE-0123'
    assert fm['type'] == 'gotcha'
    assert body == 'Body text.'


def test_parse_entry_without_frontmatter():
    entry = Path("/tmp/legacy.md")
    entry.write_text(LEGACY_MARKDOWN_ENTRY)
    fm, body = parse_entry(entry)
    assert fm == {}
    assert '**ID:** GE-0042' in body
