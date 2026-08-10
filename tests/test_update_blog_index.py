"""Tests for write-content/update_blog_index.py"""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "write-content" / "update_blog_index.py"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def _make_blog_file(blog_dir: Path, filename: str, title: str, date: str) -> Path:
    f = blog_dir / filename
    f.write_text(
        f"---\ntitle: \"{title}\"\ndate: {date}\ntype: phase-update\n---\n\nBody text.\n"
    )
    return f


def _make_index(blog_dir: Path, content: str) -> Path:
    idx = blog_dir / "INDEX.md"
    idx.write_text(content)
    return idx


# --- Happy path ---


class TestAppendToExisting:

    def test_appends_row_with_summary(self, tmp_path):
        blog = _make_blog_file(
            tmp_path, "2026-08-03-mdp01-test-entry.md", "Test Entry", "2026-08-03"
        )
        _make_index(
            tmp_path,
            "# Blog Index\n\n| File | Date | Title |\n|------|------|-------|\n"
            "| [old.md](old.md) | 2026-07-01 | Old entry |\n",
        )

        result = _run([str(blog), "--summary", "A test summary"])
        assert result.returncode == 0

        idx = (tmp_path / "INDEX.md").read_text()
        assert "| [2026-08-03-mdp01-test-entry.md](2026-08-03-mdp01-test-entry.md) | 2026-08-03 | A test summary |" in idx
        assert "| [old.md](old.md) | 2026-07-01 | Old entry |" in idx

    def test_falls_back_to_frontmatter_title(self, tmp_path):
        blog = _make_blog_file(
            tmp_path, "2026-08-03-mdp01-fallback.md", "Fallback Title", "2026-08-03"
        )
        _make_index(
            tmp_path,
            "# Blog Index\n\n| File | Date | Title |\n|------|------|-------|\n",
        )

        result = _run([str(blog)])
        assert result.returncode == 0

        idx = (tmp_path / "INDEX.md").read_text()
        assert "| [2026-08-03-mdp01-fallback.md](2026-08-03-mdp01-fallback.md) | 2026-08-03 | Fallback Title |" in idx


class TestCreateNewIndex:

    def test_creates_index_when_absent(self, tmp_path):
        blog = _make_blog_file(
            tmp_path, "2026-08-03-mdp01-new.md", "New Entry", "2026-08-03"
        )

        result = _run([str(blog), "--summary", "Brand new"])
        assert result.returncode == 0

        idx = tmp_path / "INDEX.md"
        assert idx.exists()
        content = idx.read_text()
        assert "# Blog Index" in content
        assert "| File | Date | Title |" in content
        assert "| [2026-08-03-mdp01-new.md](2026-08-03-mdp01-new.md) | 2026-08-03 | Brand new |" in content


class TestIdempotency:

    def test_does_not_duplicate_existing_entry(self, tmp_path):
        blog = _make_blog_file(
            tmp_path, "2026-08-03-mdp01-idem.md", "Idempotent", "2026-08-03"
        )
        _make_index(
            tmp_path,
            "# Blog Index\n\n| File | Date | Title |\n|------|------|-------|\n"
            "| [2026-08-03-mdp01-idem.md](2026-08-03-mdp01-idem.md) | 2026-08-03 | Already there |\n",
        )

        result = _run([str(blog), "--summary", "Different summary"])
        assert result.returncode == 0

        idx = (tmp_path / "INDEX.md").read_text()
        row_pattern = "| [2026-08-03-mdp01-idem.md]"
        assert idx.count(row_pattern) == 1
        assert "Already there" in idx
        assert "Different summary" not in idx

    def test_idempotent_on_repeated_calls(self, tmp_path):
        blog = _make_blog_file(
            tmp_path, "2026-08-03-mdp01-repeat.md", "Repeat", "2026-08-03"
        )

        _run([str(blog), "--summary", "First call"])
        _run([str(blog), "--summary", "Second call"])

        idx = (tmp_path / "INDEX.md").read_text()
        row_pattern = "| [2026-08-03-mdp01-repeat.md]"
        assert idx.count(row_pattern) == 1
        assert "First call" in idx


# --- Edge cases ---


class TestEdgeCases:

    def test_blog_file_does_not_exist(self, tmp_path):
        result = _run([str(tmp_path / "nonexistent.md")])
        assert result.returncode != 0
        assert "not found" in result.stderr.lower() or "does not exist" in result.stderr.lower()

    def test_blog_file_missing_frontmatter(self, tmp_path):
        f = tmp_path / "2026-08-03-mdp01-no-fm.md"
        f.write_text("No frontmatter here, just text.\n")

        result = _run([str(f), "--summary", "Has summary"])
        assert result.returncode != 0
        assert "frontmatter" in result.stderr.lower()

    def test_blog_file_missing_date_in_frontmatter(self, tmp_path):
        f = tmp_path / "2026-08-03-mdp01-no-date.md"
        f.write_text("---\ntitle: \"No Date\"\n---\n\nBody.\n")

        result = _run([str(f), "--summary", "Has summary"])
        assert result.returncode != 0
        assert "date" in result.stderr.lower()

    def test_blog_file_missing_title_no_summary(self, tmp_path):
        f = tmp_path / "2026-08-03-mdp01-no-title.md"
        f.write_text("---\ndate: 2026-08-03\n---\n\nBody.\n")

        result = _run([str(f)])
        assert result.returncode != 0
        assert "title" in result.stderr.lower() or "summary" in result.stderr.lower()

    def test_title_with_quotes_in_frontmatter(self, tmp_path):
        f = tmp_path / "2026-08-03-mdp01-quotes.md"
        f.write_text('---\ntitle: "It\'s a \\"Quoted\\" Title"\ndate: 2026-08-03\n---\n\nBody.\n')

        result = _run([str(f)])
        assert result.returncode == 0

        idx = (tmp_path / "INDEX.md").read_text()
        assert "2026-08-03-mdp01-quotes.md" in idx

    def test_index_ends_without_newline(self, tmp_path):
        blog = _make_blog_file(
            tmp_path, "2026-08-03-mdp01-nonl.md", "No Newline", "2026-08-03"
        )
        idx_path = tmp_path / "INDEX.md"
        idx_path.write_text(
            "# Blog Index\n\n| File | Date | Title |\n|------|------|-------|\n"
            "| [old.md](old.md) | 2026-07-01 | Old |"  # no trailing newline
        )

        result = _run([str(blog), "--summary", "After no newline"])
        assert result.returncode == 0

        lines = idx_path.read_text().splitlines()
        assert any("2026-08-03-mdp01-nonl.md" in line for line in lines)
        assert any("old.md" in line for line in lines)


# --- Bad arguments ---


class TestBadArguments:

    def test_no_arguments(self):
        result = _run([])
        assert result.returncode != 0

    def test_too_many_positional_arguments(self, tmp_path):
        f = tmp_path / "a.md"
        f.write_text("---\ntitle: A\ndate: 2026-01-01\n---\n")
        result = _run([str(f), "extra_arg"])
        assert result.returncode != 0


class TestDocsSubdirectory:
    """Verify update_blog_index works when blog is under docs/blog/."""

    def test_creates_index_in_docs_blog(self, tmp_path):
        blog_dir = tmp_path / "docs" / "blog"
        blog_dir.mkdir(parents=True)
        blog = _make_blog_file(
            blog_dir, "2026-08-10-mdp01-test.md", "Docs Blog Test", "2026-08-10"
        )

        result = _run([str(blog), "--summary", "Test in docs/blog"])
        assert result.returncode == 0

        index = blog_dir / "INDEX.md"
        assert index.exists()
        assert "2026-08-10-mdp01-test.md" in index.read_text()
        assert not (tmp_path / "INDEX.md").exists()
