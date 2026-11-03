"""Tests for extract_image_refs() and check_broken_images() in verification/repo_checks.py."""
import pytest
from pathlib import Path

from verification.repo_checks import extract_image_refs, check_broken_images


class TestExtractImageRefs:
    def test_markdown_image(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("![alt](images/fig1.png)\n")
        refs = extract_image_refs(md)
        assert len(refs) == 1
        assert refs[0][0] == "images/fig1.png"
        assert refs[0][1] == (tmp_path / "images/fig1.png").resolve()

    def test_markdown_image_no_alt(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("![](screenshot.png)\n")
        refs = extract_image_refs(md)
        assert len(refs) == 1
        assert refs[0][0] == "screenshot.png"

    def test_html_img(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text('<img src="assets/logo.svg">\n')
        refs = extract_image_refs(md)
        assert len(refs) == 1
        assert refs[0][0] == "assets/logo.svg"

    def test_html_img_single_quotes(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("<img src='assets/logo.svg'>\n")
        refs = extract_image_refs(md)
        assert len(refs) == 1
        assert refs[0][0] == "assets/logo.svg"

    def test_skips_http_url(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("![alt](http://example.com/img.png)\n")
        refs = extract_image_refs(md)
        assert refs == []

    def test_skips_https_url(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("![alt](https://cdn.example.com/img.png)\n")
        refs = extract_image_refs(md)
        assert refs == []

    def test_skips_data_url(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("![alt](data://base64stuff)\n")
        refs = extract_image_refs(md)
        assert refs == []

    def test_skips_protocol_relative(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("![alt](//cdn.example.com/img.png)\n")
        refs = extract_image_refs(md)
        assert refs == []

    def test_skips_placeholder(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("![alt](x)\n![alt]({thumb_src})\n![alt](path)\n")
        refs = extract_image_refs(md)
        assert refs == []

    def test_skips_chrome_url(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("![alt](chrome://something)\n")
        refs = extract_image_refs(md)
        assert refs == []

    def test_root_relative_path(self, tmp_path):
        (tmp_path / ".git").mkdir()
        subdir = tmp_path / "docs"
        subdir.mkdir()
        md = subdir / "doc.md"
        md.write_text("![alt](/assets/img/fig.png)\n")
        refs = extract_image_refs(md)
        assert len(refs) == 1
        assert refs[0][0] == "/assets/img/fig.png"
        assert refs[0][1] == tmp_path / "assets/img/fig.png"

    def test_multiple_refs_on_one_line(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("![a](one.png) text ![b](two.png)\n")
        refs = extract_image_refs(md)
        assert len(refs) == 2
        assert refs[0][0] == "one.png"
        assert refs[1][0] == "two.png"

    def test_nonexistent_image_still_returned(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("![alt](does-not-exist.png)\n")
        refs = extract_image_refs(md)
        assert len(refs) == 1

    def test_url_encoded_path(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("![alt](images/my%20image.png)\n")
        refs = extract_image_refs(md)
        assert len(refs) == 1
        assert refs[0][0] == "images/my image.png"

    def test_empty_file(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("")
        refs = extract_image_refs(md)
        assert refs == []

    def test_no_images(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("# Hello\n\nJust text.\n")
        refs = extract_image_refs(md)
        assert refs == []


class TestCheckBrokenImagesRefactored:
    def test_existing_image_no_findings(self, tmp_path):
        img = tmp_path / "fig.png"
        img.write_bytes(b"\x89PNG")
        md = tmp_path / "doc.md"
        md.write_text("![alt](fig.png)\n")
        findings = check_broken_images(md)
        assert findings == []

    def test_missing_image_returns_finding(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("![alt](missing.png)\n")
        findings = check_broken_images(md)
        assert len(findings) == 1
        assert findings[0].severity == "ERROR"
        assert findings[0].category == "broken-image"
        assert "missing.png" in findings[0].message

    def test_url_reference_no_findings(self, tmp_path):
        md = tmp_path / "doc.md"
        md.write_text("![alt](https://example.com/img.png)\n")
        findings = check_broken_images(md)
        assert findings == []

    def test_mixed_existing_and_missing(self, tmp_path):
        img = tmp_path / "exists.png"
        img.write_bytes(b"\x89PNG")
        md = tmp_path / "doc.md"
        md.write_text("![a](exists.png)\n![b](missing.png)\n")
        findings = check_broken_images(md)
        assert len(findings) == 1
        assert "missing.png" in findings[0].message
