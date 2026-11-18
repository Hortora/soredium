"""Tests for SVG XML validation in artifact_sweep.py and artifact_promote.py."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))


VALID_SVG = """\
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
  <circle cx="50" cy="50" r="40" fill="blue"/>
</svg>
"""

INVALID_SVG = """\
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
  <text>Values where x < y break XML</text>
</svg>
"""


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(path)],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit",
                    "--allow-empty", "-m", "init"],
                   capture_output=True, check=True)
    return path


class TestValidateSvg:
    """Unit tests for validate_svg() in artifact_sweep.py."""

    def test_valid_svg_passes(self, tmp_path):
        from artifact_sweep import validate_svg

        svg = tmp_path / "good.svg"
        svg.write_text(VALID_SVG)
        validate_svg(svg)

    def test_invalid_svg_raises_with_location(self, tmp_path):
        from artifact_sweep import validate_svg, InvalidSvg

        svg = tmp_path / "bad.svg"
        svg.write_text(INVALID_SVG)

        with pytest.raises(InvalidSvg, match="bad.svg"):
            validate_svg(svg)


class TestPromoteGapsSvg:
    """SVG validation during direct promotion via promote_gaps (manually constructed gaps)."""

    def test_valid_svg_promoted(self, tmp_path):
        from artifact_sweep import promote_gaps

        ws = tmp_path / "workspace"
        ws.mkdir()
        proj = _init_repo(tmp_path / "project")

        svg = ws / "blog" / "diagram.svg"
        svg.parent.mkdir(parents=True)
        svg.write_text(VALID_SVG)

        gaps = [{
            "category": "blog",
            "source": str(svg),
            "source_rel": "blog/diagram.svg",
            "dest_rel": "docs/blog/diagram.svg",
            "dest": str(proj / "docs" / "blog" / "diagram.svg"),
        }]
        result = promote_gaps(gaps, proj)

        assert result["promoted"] == 1
        assert "error" not in result
        assert (proj / "docs" / "blog" / "diagram.svg").exists()

    def test_invalid_svg_blocks_promotion(self, tmp_path):
        from artifact_sweep import promote_gaps

        ws = tmp_path / "workspace"
        ws.mkdir()
        proj = _init_repo(tmp_path / "project")

        svg = ws / "blog" / "broken.svg"
        svg.parent.mkdir(parents=True)
        svg.write_text(INVALID_SVG)

        gaps = [{
            "category": "blog",
            "source": str(svg),
            "source_rel": "blog/broken.svg",
            "dest_rel": "docs/blog/broken.svg",
            "dest": str(proj / "docs" / "blog" / "broken.svg"),
        }]
        result = promote_gaps(gaps, proj)

        assert result["promoted"] == 0
        assert "error" in result
        assert "invalid SVG" in result["error"]
        assert "broken.svg" in result["error"]


class TestCopromotionSvgValidation:
    """SVG validation when an SVG is co-promoted as an image ref from markdown."""

    def test_valid_svg_copromoted_with_md(self, tmp_path):
        from artifact_sweep import find_gaps, promote_gaps

        ws = _init_repo(tmp_path / "workspace")
        proj = _init_repo(tmp_path / "project")

        (ws / "blog").mkdir()
        (ws / "blog" / "images").mkdir()
        (ws / "blog" / "images" / "arch.svg").write_text(VALID_SVG)
        (ws / "blog" / "entry.md").write_text("# Entry\n![diagram](images/arch.svg)\n")

        gaps = find_gaps(ws, proj)
        result = promote_gaps(gaps, proj)

        assert result["promoted"] > 0
        assert "error" not in result
        assert (proj / "docs" / "blog" / "entry.md").exists()
        assert (proj / "docs" / "blog" / "images" / "arch.svg").exists()

    def test_invalid_svg_copromoted_blocks_with_error(self, tmp_path):
        from artifact_sweep import find_gaps, promote_gaps

        ws = _init_repo(tmp_path / "workspace")
        proj = _init_repo(tmp_path / "project")

        (ws / "blog").mkdir()
        (ws / "blog" / "images").mkdir()
        (ws / "blog" / "images" / "broken.svg").write_text(INVALID_SVG)
        (ws / "blog" / "entry.md").write_text("# Entry\n![diagram](images/broken.svg)\n")

        gaps = find_gaps(ws, proj)
        result = promote_gaps(gaps, proj)

        assert result["promoted"] == 0
        assert "error" in result
        assert "broken.svg" in result["error"]


class TestCopromoteImagesUnit:
    """Unit tests for _copromote_images SVG validation path in artifact_promote.py."""

    def test_valid_svg_ref_copies_without_error(self, tmp_path):
        from artifact_promote import _copromote_images

        repo = _init_repo(tmp_path / "repo")
        src_dir = tmp_path / "source"
        src_dir.mkdir()
        (src_dir / "images").mkdir()
        (src_dir / "images" / "fig.svg").write_text(VALID_SVG)
        md_src = src_dir / "entry.md"
        md_src.write_text("![fig](images/fig.svg)\n")
        md_dst = repo / "docs" / "blog" / "entry.md"
        md_dst.parent.mkdir(parents=True)
        md_dst.write_text("![fig](images/fig.svg)\n")

        copied = _copromote_images(md_src, md_dst, str(repo))
        assert copied >= 1
        assert (repo / "docs" / "blog" / "images" / "fig.svg").exists()

    def test_invalid_svg_ref_raises_image_not_promoted(self, tmp_path):
        from artifact_promote import _copromote_images, ImageNotPromoted

        repo = _init_repo(tmp_path / "repo")
        src_dir = tmp_path / "source"
        src_dir.mkdir()
        (src_dir / "images").mkdir()
        (src_dir / "images" / "bad.svg").write_text(INVALID_SVG)
        md_src = src_dir / "entry.md"
        md_src.write_text("![fig](images/bad.svg)\n")
        md_dst = repo / "docs" / "blog" / "entry.md"
        md_dst.parent.mkdir(parents=True)
        md_dst.write_text("![fig](images/bad.svg)\n")

        with pytest.raises(ImageNotPromoted, match="bad.svg"):
            _copromote_images(md_src, md_dst, str(repo))
