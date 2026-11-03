"""Tests for image co-promotion in artifact_promote.py."""
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))


def _init_git(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "test"], capture_output=True)
    (path / ".gitkeep").touch()
    subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "init"], capture_output=True)


class TestToProjectImageCopromotion:
    def test_md_with_image_promotes_both(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        _init_git(ws)
        proj = tmp_path / "project"
        proj.mkdir()
        _init_git(proj)

        blog_dir = ws / "docs" / "blog"
        blog_dir.mkdir(parents=True)
        img_dir = blog_dir / "images"
        img_dir.mkdir()
        img = img_dir / "fig1.png"
        img.write_bytes(b"\x89PNG")
        md = blog_dir / "entry.md"
        md.write_text("![alt](images/fig1.png)\n")

        from artifact_promote import to_project

        with patch("artifact_promote._push_or_report"):
            rc = to_project(str(proj), str(ws), {
                "artifacts": "docs/blog/entry.md",
                "covers": "",
            })

        assert rc == 0
        assert (proj / "docs/blog/entry.md").exists()
        assert (proj / "docs/blog/images/fig1.png").exists()

    def test_md_with_missing_image_promotes_md_only(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        _init_git(ws)
        proj = tmp_path / "project"
        proj.mkdir()
        _init_git(proj)

        blog_dir = ws / "docs" / "blog"
        blog_dir.mkdir(parents=True)
        md = blog_dir / "entry.md"
        md.write_text("![alt](images/missing.png)\n")

        from artifact_promote import to_project

        with patch("artifact_promote._push_or_report"):
            rc = to_project(str(proj), str(ws), {
                "artifacts": "docs/blog/entry.md",
                "covers": "",
            })

        assert rc == 0
        assert (proj / "docs/blog/entry.md").exists()
        assert not (proj / "docs/blog/images/missing.png").exists()

    def test_nested_image_dir_preserved(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        _init_git(ws)
        proj = tmp_path / "project"
        proj.mkdir()
        _init_git(proj)

        spec_dir = ws / "specs" / "feature"
        spec_dir.mkdir(parents=True)
        img_dir = spec_dir / "images" / "screenshots"
        img_dir.mkdir(parents=True)
        img = img_dir / "screen1.png"
        img.write_bytes(b"\x89PNG")
        md = spec_dir / "design.md"
        md.write_text("![screen](images/screenshots/screen1.png)\n")

        from artifact_promote import to_project

        with patch("artifact_promote._push_or_report"):
            rc = to_project(str(proj), str(ws), {
                "artifacts": "specs/feature/design.md",
                "covers": "",
            })

        assert rc == 0
        assert (proj / "specs/feature/images/screenshots/screen1.png").exists()

    def test_non_md_artifact_no_image_scan(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        _init_git(ws)
        proj = tmp_path / "project"
        proj.mkdir()
        _init_git(proj)

        data = ws / "data.json"
        data.write_text('{"key": "value"}\n')

        from artifact_promote import to_project

        with patch("artifact_promote._push_or_report"):
            rc = to_project(str(proj), str(ws), {
                "artifacts": "data.json",
                "covers": "",
            })

        assert rc == 0
        assert (proj / "data.json").exists()
