import pytest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from integrate_entry import integrate, generate_summary

VALID_ENTRY = """\
---
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
    with patch('integrate_entry.close_github_issue'), \
         patch('integrate_entry.run_validate'), \
         patch('integrate_entry.git_commit'):
        return integrate(str(entry), str(garden), close_issue=False)


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
    entry.write_text(VALID_ENTRY.replace('domain: quarkus/cdi', 'domain: newdomain/sub'))
    with patch('integrate_entry.close_github_issue'), \
         patch('integrate_entry.run_validate'), \
         patch('integrate_entry.git_commit'):
        integrate(str(entry), str(tmp_path), close_issue=False)
    assert "newdomain" in (tmp_path / "_index" / "global.md").read_text()


def test_close_issue_called_with_ge_id(garden, entry):
    with patch('integrate_entry.close_github_issue') as mock_close, \
         patch('integrate_entry.run_validate'), \
         patch('integrate_entry.git_commit'):
        integrate(str(entry), str(garden), close_issue=True)
    mock_close.assert_called_once_with("GE-0123")


def test_generate_summary_format():
    fm = {'title': 'Test title', 'type': 'gotcha', 'score': 12,
          'tags': ['quarkus', 'cdi', 'extra-tag']}
    s = generate_summary(fm, 'GE-0001')
    assert 'GE-0001' in s
    assert 'gotcha' in s
    assert '12/15' in s
    assert 'quarkus' in s
