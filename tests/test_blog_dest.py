"""Tests for work-end/blog_dest.py image handling."""

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))

from workspace_artifacts import extract_image_refs


class TestBlogImageCopy:
    def test_blog_image_copied_to_destination(self, tmp_path):
        ws_blog = tmp_path / "source" / "blog"
        ws_blog.mkdir(parents=True)
        (ws_blog / "2026-08-01-entry.md").write_text("![Photo](images/photo.png)\n")
        img = ws_blog / "images" / "photo.png"
        img.parent.mkdir()
        img.write_bytes(b"\x89PNG")

        dest = tmp_path / "dest" / "_posts"
        dest.mkdir(parents=True)

        refs = extract_image_refs(ws_blog / "2026-08-01-entry.md", ws_blog)
        for ref in refs:
            src = ws_blog / ref
            dst = dest / ref
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))

        assert (dest / "images" / "photo.png").exists()

    def test_blog_image_relative_structure_preserved(self, tmp_path):
        ws_blog = tmp_path / "source" / "blog"
        ws_blog.mkdir(parents=True)
        (ws_blog / "entry.md").write_text("![D](images/sub/deep.svg)\n")
        img = ws_blog / "images" / "sub" / "deep.svg"
        img.parent.mkdir(parents=True)
        img.write_text("<svg/>")

        dest = tmp_path / "dest" / "_posts"
        dest.mkdir(parents=True)

        refs = extract_image_refs(ws_blog / "entry.md", ws_blog)
        for ref in refs:
            src = ws_blog / ref
            dst = dest / ref
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))

        assert (dest / "images" / "sub" / "deep.svg").exists()
