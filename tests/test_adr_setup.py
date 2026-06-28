"""Tests for adversarial-design-review workspace setup and session invocation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


class TestWorkspaceSetup:

    def test_creates_directory_structure(self, tmp_path: Path) -> None:
        from adversarial_design_review.setup import setup_review

        spec_file = tmp_path / "input-spec.md"
        spec_file.write_text("# My Design\n\nSome content.\n")

        ws = setup_review(
            spec_path=spec_file,
            title="test-design",
            source_dirs=[str(tmp_path)],
            adr_root=tmp_path / "adr",
        )

        assert ws.is_dir()
        assert (ws / ".spec-path").exists()
        assert (ws / "responses").is_dir()
        assert (ws / "decisions").is_dir()
        assert (ws / "handovers").is_dir()
        assert (ws / "agents" / "reviewer").is_dir()
        assert (ws / "agents" / "implementor").is_dir()

    def test_git_initialized(self, tmp_path: Path) -> None:
        from adversarial_design_review.setup import setup_review

        spec_file = tmp_path / "input-spec.md"
        spec_file.write_text("# My Design\n")

        ws = setup_review(
            spec_path=spec_file,
            title="test-design",
            source_dirs=[str(tmp_path)],
            adr_root=tmp_path / "adr",
        )

        adr_root = tmp_path / "adr"
        assert (adr_root / ".git").is_dir()
        result = subprocess.run(
            ["git", "log", "--oneline"], cwd=adr_root,
            capture_output=True, text=True,
        )
        assert "setup" in result.stdout

    def test_context_md_generated(self, tmp_path: Path) -> None:
        from adversarial_design_review.setup import setup_review

        spec_file = tmp_path / "input-spec.md"
        spec_file.write_text("# My Design\n")

        ws = setup_review(
            spec_path=spec_file,
            title="test-design",
            source_dirs=[str(tmp_path)],
            adr_root=tmp_path / "adr",
        )

        context_md = ws / "context.md"
        assert context_md.exists()
        content = context_md.read_text()
        assert "Directory Layout" in content
        assert "Structured Output Format" in content
        assert "File Ownership" in content
        assert "SIGNAL" in content

    def test_agent_claude_mds_generated(self, tmp_path: Path) -> None:
        from adversarial_design_review.setup import setup_review

        spec_file = tmp_path / "input-spec.md"
        spec_file.write_text("# My Design\n")

        ws = setup_review(
            spec_path=spec_file,
            title="test-design",
            source_dirs=[str(tmp_path)],
            adr_root=tmp_path / "adr",
        )

        reviewer_md = ws / "agents" / "reviewer" / "CLAUDE.md"
        implementor_md = ws / "agents" / "implementor" / "CLAUDE.md"

        assert reviewer_md.exists()
        assert implementor_md.exists()

        assert "Adversarial" in reviewer_md.read_text()
        assert "Implementor" in implementor_md.read_text()

    def test_workspace_name_includes_title(self, tmp_path: Path) -> None:
        from adversarial_design_review.setup import setup_review

        spec_file = tmp_path / "input-spec.md"
        spec_file.write_text("# My Design\n")

        ws = setup_review(
            spec_path=spec_file,
            title="invoice-aggregate",
            source_dirs=[str(tmp_path)],
            adr_root=tmp_path / "adr",
        )

        assert "invoice-aggregate" in ws.name


class TestAnnotateSpecHeadings:

    def test_annotates_h2_headings(self) -> None:
        from adversarial_design_review.setup import annotate_spec_headings

        content = "# My Spec\n\n## Problem Statement\n\nSome text.\n\n## Proposed Design\n\nMore text.\n"
        result = annotate_spec_headings(content)
        assert "## S1: Problem Statement" in result
        assert "## S2: Proposed Design" in result
        assert "# My Spec" in result  # h1 untouched

    def test_annotates_h3_headings(self) -> None:
        from adversarial_design_review.setup import annotate_spec_headings

        content = "## Design\n\n### Event Schema\n\nText.\n\n### State Machine\n\nText.\n"
        result = annotate_spec_headings(content)
        assert "## S1: Design" in result
        assert "### S1.1: Event Schema" in result
        assert "### S1.2: State Machine" in result

    def test_skips_already_annotated(self) -> None:
        from adversarial_design_review.setup import annotate_spec_headings

        content = "## S1: Already Annotated\n\n## Another Section\n"
        result = annotate_spec_headings(content)
        assert "## S1: Already Annotated" in result
        assert "## S2: Another Section" in result

    def test_preserves_content(self) -> None:
        from adversarial_design_review.setup import annotate_spec_headings

        content = "# Title\n\n## Overview\n\nParagraph with **bold** and `code`.\n\n- List item\n- Another\n"
        result = annotate_spec_headings(content)
        assert "Paragraph with **bold** and `code`." in result
        assert "- List item" in result

    def test_empty_spec(self) -> None:
        from adversarial_design_review.setup import annotate_spec_headings

        assert annotate_spec_headings("") == ""
        assert annotate_spec_headings("Just text, no headings.\n") == "Just text, no headings.\n"


class TestBuildClaudeCommand:

    @pytest.fixture
    def ws(self, tmp_path: Path) -> Path:
        from adversarial_design_review.setup import setup_review

        spec = tmp_path / "spec.md"
        spec.write_text("# Test\n")
        return setup_review(spec_path=spec, title="test", source_dirs=[str(tmp_path)],
                               adr_root=tmp_path / "adr")

    def test_fresh_session_command(self, ws: Path) -> None:
        from adversarial_design_review.setup import build_claude_command

        cmd = build_claude_command(
            role_dir=ws / "agents" / "reviewer",
            context_md=ws / "context.md",
            source_dirs=["/project", "/platform"],
            adr_root=ws,
            model="opus",
            budget=5.0,
            effort="high",
            prompt="Review round 1",
            session_id=None,
        )

        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "--append-system-prompt-file" in cmd
        assert "--disallowedTools" in cmd
        assert "Skill" in cmd
        assert "--model" in cmd
        assert "opus" in cmd[cmd.index("--model") + 1]

    def test_resumed_session_command(self, ws: Path) -> None:
        from adversarial_design_review.setup import build_claude_command

        cmd = build_claude_command(
            role_dir=ws / "agents" / "reviewer",
            context_md=ws / "context.md",
            source_dirs=["/project"],
            adr_root=ws,
            model="opus",
            budget=5.0,
            effort="high",
            prompt="Review round 2",
            session_id="abc-123",
        )

        assert "--resume" in cmd
        assert "abc-123" in cmd
        assert "--append-system-prompt-file" in cmd

    def test_multiple_source_dirs(self, ws: Path) -> None:
        from adversarial_design_review.setup import build_claude_command

        cmd = build_claude_command(
            role_dir=ws / "agents" / "reviewer",
            context_md=ws / "context.md",
            source_dirs=["/project", "/platform", "/workspace"],
            adr_root=ws,
            model="opus",
            budget=5.0,
            effort="high",
            prompt="test",
            session_id=None,
        )

        add_dir_indices = [i for i, v in enumerate(cmd) if v == "--add-dir"]
        assert len(add_dir_indices) >= 4  # 3 source dirs + adr root
