"""Tests for scripts/blog_person_check.py"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from blog_person_check import scan_diff, is_safe_match, get_staged_blog_files

SCRIPT = Path(__file__).parent.parent / "scripts" / "blog_person_check.py"


class TestScanDiff:
    def _make_diff(self, *added_lines: str) -> str:
        lines = ["diff --git a/blog/entry.md b/blog/entry.md",
                 "@@ -0,0 +1,%d @@" % len(added_lines)]
        for line in added_lines:
            lines.append(f"+{line}")
        return "\n".join(lines)

    def test_detects_name_said(self):
        diff = self._make_diff("John Smith said the architecture was wrong.")
        findings = scan_diff(diff, "blog/entry.md")
        assert len(findings) == 1
        assert "John Smith said" in findings[0][2]

    def test_detects_according_to(self):
        diff = self._make_diff("According to Jane Doe, the migration was risky.")
        findings = scan_diff(diff, "blog/entry.md")
        assert len(findings) == 1

    def test_detects_possessive_opinion(self):
        diff = self._make_diff("Bob Wilson's feedback was that we should revert.")
        findings = scan_diff(diff, "blog/entry.md")
        assert len(findings) == 1

    def test_detects_pronoun_attribution(self):
        diff = self._make_diff("She decided the rollback was necessary.")
        findings = scan_diff(diff, "blog/entry.md")
        assert len(findings) == 1

    def test_detects_at_mention(self):
        diff = self._make_diff("Thanks to @jdoe for catching this.")
        findings = scan_diff(diff, "blog/entry.md")
        assert len(findings) == 1

    def test_ignores_technical_names(self):
        diff = self._make_diff(
            "Claude Code handles this automatically.",
            "GitHub Actions runs the CI pipeline.",
            "Maven Central hosts the artifacts.",
            "IntelliJ IDEA provides semantic analysis.",
        )
        findings = scan_diff(diff, "blog/entry.md")
        assert len(findings) == 0

    def test_ignores_section_references(self):
        diff = self._make_diff(
            "Phase A completed successfully.",
            "Step Three requires manual review.",
        )
        findings = scan_diff(diff, "blog/entry.md")
        assert len(findings) == 0

    def test_no_false_positive_on_code(self):
        diff = self._make_diff(
            "The `UserService` class handles authentication.",
            "Run `git rebase origin/main` to sync.",
        )
        findings = scan_diff(diff, "blog/entry.md")
        assert len(findings) == 0

    def test_ignores_removed_lines(self):
        diff = (
            "diff --git a/blog/entry.md b/blog/entry.md\n"
            "@@ -1,3 +1,2 @@\n"
            "-John Smith said this was bad.\n"
            " Technical content stays.\n"
        )
        findings = scan_diff(diff, "blog/entry.md")
        assert len(findings) == 0

    def test_multiple_findings(self):
        diff = self._make_diff(
            "Alice Brown told the team to ship it.",
            "According to Bob Chen, the risk was low.",
        )
        findings = scan_diff(diff, "blog/entry.md")
        assert len(findings) == 2


class TestIsSafeMatch:
    def test_safe_prefix(self):
        assert is_safe_match("Claude Code") is True
        assert is_safe_match("GitHub Actions") is True

    def test_unsafe_name(self):
        assert is_safe_match("John Smith") is False
        assert is_safe_match("Alice") is False


class TestGetStagedBlogFiles:
    def _init_repo(self, path):
        subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True)

    def test_detects_staged_blog_files(self, tmp_path):
        self._init_repo(tmp_path)
        blog = tmp_path / "blog"
        blog.mkdir()
        (blog / "entry.md").write_text("# Entry\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "blog/entry.md"], capture_output=True)

        files = get_staged_blog_files(str(tmp_path))
        assert "blog/entry.md" in files

    def test_ignores_non_blog_files(self, tmp_path):
        self._init_repo(tmp_path)
        (tmp_path / "README.md").write_text("# README\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], capture_output=True)

        files = get_staged_blog_files(str(tmp_path))
        assert len(files) == 0

    def test_ignores_non_md_blog_files(self, tmp_path):
        self._init_repo(tmp_path)
        blog = tmp_path / "blog"
        blog.mkdir()
        (blog / "image.png").write_bytes(b"\x89PNG")
        subprocess.run(["git", "-C", str(tmp_path), "add", "blog/image.png"], capture_output=True)

        files = get_staged_blog_files(str(tmp_path))
        assert len(files) == 0


class TestIntegration:
    SCRIPT = Path(__file__).parent.parent / "scripts" / "blog_person_check.py"

    def _init_repo(self, path):
        subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True)

    def test_passes_clean_blog(self, tmp_path):
        self._init_repo(tmp_path)
        blog = tmp_path / "blog"
        blog.mkdir()
        (blog / "entry.md").write_text("# Technical Decision\n\nWe chose option A.\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "blog/entry.md"], capture_output=True)

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT), str(tmp_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "FLAGGED=0" in result.stdout

    def test_blocks_person_reference(self, tmp_path):
        self._init_repo(tmp_path)
        blog = tmp_path / "blog"
        blog.mkdir()
        (blog / "entry.md").write_text("# Meeting Notes\n\nJohn Smith said the deadline was unrealistic.\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "blog/entry.md"], capture_output=True)

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT), str(tmp_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "FLAGGED=1" in result.stdout
        assert "FLAG=" in result.stdout

    def test_passes_no_blog_files(self, tmp_path):
        self._init_repo(tmp_path)
        (tmp_path / "README.md").write_text("# Readme\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], capture_output=True)

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT), str(tmp_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "BLOG_FILES=0" in result.stdout
