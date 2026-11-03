"""Tests for check_promoted_images in verification/close_checks.py."""
import subprocess
from pathlib import Path

import pytest

from verification import Finding


def _init_git(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "test"], capture_output=True)
    (path / ".gitkeep").touch()
    subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "init"], capture_output=True)


class TestCheckPromotedImages:
    def test_all_images_present_no_findings(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        _init_git(proj)
        docs = proj / "docs" / "blog"
        docs.mkdir(parents=True)
        img = docs / "images" / "fig.png"
        img.parent.mkdir()
        img.write_bytes(b"\x89PNG")
        md = docs / "entry.md"
        md.write_text("![alt](images/fig.png)\n")

        from verification.close_checks import check_promoted_images
        findings = check_promoted_images(proj)
        assert findings == []

    def test_missing_image_returns_warn(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        _init_git(proj)
        docs = proj / "docs" / "blog"
        docs.mkdir(parents=True)
        md = docs / "entry.md"
        md.write_text("![alt](images/missing.png)\n")

        from verification.close_checks import check_promoted_images
        findings = check_promoted_images(proj)
        assert len(findings) >= 1
        assert all(f.severity == "WARN" for f in findings)
        assert any("missing.png" in f.message for f in findings)

    def test_url_refs_not_flagged(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        _init_git(proj)
        docs = proj / "docs" / "blog"
        docs.mkdir(parents=True)
        md = docs / "entry.md"
        md.write_text("![alt](https://example.com/img.png)\n")

        from verification.close_checks import check_promoted_images
        findings = check_promoted_images(proj)
        assert findings == []

    def test_specs_dir_also_scanned(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        _init_git(proj)
        specs = proj / "docs" / "specs"
        specs.mkdir(parents=True)
        md = specs / "design.md"
        md.write_text("![diagram](diagrams/arch.png)\n")

        from verification.close_checks import check_promoted_images
        findings = check_promoted_images(proj)
        assert len(findings) >= 1
        assert any("arch.png" in f.message for f in findings)

    def test_no_docs_dir_no_findings(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        _init_git(proj)

        from verification.close_checks import check_promoted_images
        findings = check_promoted_images(proj)
        assert findings == []
