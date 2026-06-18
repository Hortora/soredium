#!/usr/bin/env python3
"""
Tests for workspace-init scripts: workspace_create.py, artifact_migrate.py, hook_install.py

Covers: happy path, idempotency, missing args, nonexistent paths, edge cases.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

WORKSPACE_CREATE = Path(__file__).parent.parent / "workspace-init" / "workspace_create.py"
ARTIFACT_MIGRATE = Path(__file__).parent.parent / "workspace-init" / "artifact_migrate.py"
HOOK_INSTALL = Path(__file__).parent.parent / "workspace-init" / "hook_install.py"


def run_create(subcommand: str, workspace: Path, *extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(WORKSPACE_CREATE), subcommand, str(workspace)] + list(extra_args),
        capture_output=True, text=True,
    )


def run_migrate(subcommand: str, *positional: str, **kw_args: str) -> subprocess.CompletedProcess:
    args = [sys.executable, str(ARTIFACT_MIGRATE), subcommand] + list(positional)
    args += [f"{k}={v}" for k, v in kw_args.items()]
    return subprocess.run(args, capture_output=True, text=True)


def run_hook(subcommand: str, project: Path, *extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK_INSTALL), subcommand, str(project)] + list(extra_args),
        capture_output=True, text=True,
    )


def parse(result: subprocess.CompletedProcess) -> dict[str, str]:
    """Extract KEY=VALUE pairs from stdout."""
    out: dict[str, str] = {}
    for line in result.stdout.strip().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k] = v
    return out


def init_git(path: Path) -> None:
    """Initialise a bare git repo at the given path."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"],
        capture_output=True, check=True,
    )


# ===========================================================================
# workspace_create.py
# ===========================================================================

class TestWorkspaceCreateDirs:

    def test_creates_all_standard_dirs(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        result = run_create("create-dirs", ws)
        assert result.returncode == 0
        for d in ["plans", "specs", "snapshots", "adr", "blog", "design"]:
            assert (ws / d).is_dir(), f"{d} not created"

    def test_output_created_yes_on_first_run(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        result = run_create("create-dirs", ws)
        out = parse(result)
        assert out["CREATED"] == "yes"

    def test_idempotent_second_run(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run_create("create-dirs", ws)
        result = run_create("create-dirs", ws)
        assert result.returncode == 0
        out = parse(result)
        assert out["CREATED"] == "no"

    def test_exits_1_for_nonexistent_workspace(self, tmp_path):
        result = run_create("create-dirs", tmp_path / "nonexistent")
        assert result.returncode == 1

    def test_partial_dirs_exist(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "plans").mkdir()
        (ws / "specs").mkdir()
        result = run_create("create-dirs", ws)
        out = parse(result)
        assert out["CREATED"] == "yes"  # not all existed
        assert (ws / "adr").is_dir()


class TestWorkspaceCreateIndexes:

    def test_creates_three_index_files(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run_create("create-dirs", ws)
        result = run_create("create-indexes", ws)
        assert result.returncode == 0
        out = parse(result)
        assert out["CREATED"] == "3"
        for d in ["snapshots", "adr", "blog"]:
            assert (ws / d / "INDEX.md").is_file()

    def test_index_content_has_table_header(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run_create("create-dirs", ws)
        run_create("create-indexes", ws)
        content = (ws / "adr" / "INDEX.md").read_text()
        assert "# ADR Index" in content
        assert "| ID |" in content

    def test_idempotent_does_not_overwrite(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run_create("create-dirs", ws)
        run_create("create-indexes", ws)
        # Modify one
        (ws / "adr" / "INDEX.md").write_text("custom content\n")
        result = run_create("create-indexes", ws)
        out = parse(result)
        assert out["CREATED"] == "0"
        assert (ws / "adr" / "INDEX.md").read_text() == "custom content\n"

    def test_creates_parent_dirs_if_missing(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        # Don't create dirs first — indexes should create parent dirs
        result = run_create("create-indexes", ws)
        assert result.returncode == 0
        assert (ws / "adr" / "INDEX.md").is_file()

    def test_exits_1_for_nonexistent_workspace(self, tmp_path):
        result = run_create("create-indexes", tmp_path / "nonexistent")
        assert result.returncode == 1


class TestWorkspaceCreateStubs:

    def test_creates_handoff_and_ideas(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        result = run_create("create-stubs", ws)
        assert result.returncode == 0
        out = parse(result)
        assert out["CREATED"] == "2"
        assert (ws / "HANDOFF.md").is_file()
        assert (ws / "IDEAS.md").is_file()

    def test_handoff_content(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run_create("create-stubs", ws)
        content = (ws / "HANDOFF.md").read_text()
        assert "# Handoff" in content

    def test_ideas_content(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run_create("create-stubs", ws)
        content = (ws / "IDEAS.md").read_text()
        assert "# Idea Log" in content

    def test_idempotent_skips_existing(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        run_create("create-stubs", ws)
        (ws / "HANDOFF.md").write_text("custom\n")
        result = run_create("create-stubs", ws)
        out = parse(result)
        assert out["CREATED"] == "0"
        assert (ws / "HANDOFF.md").read_text() == "custom\n"

    def test_exits_1_for_nonexistent_workspace(self, tmp_path):
        result = run_create("create-stubs", tmp_path / "nonexistent")
        assert result.returncode == 1


class TestWorkspaceInitRepo:

    def test_initialises_git_repo(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "README.md").write_text("test\n")
        result = run_create("init-repo", ws)
        assert result.returncode == 0
        assert (ws / ".git").is_dir()

    def test_creates_initial_commit(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "README.md").write_text("test\n")
        run_create("init-repo", ws)
        log = subprocess.run(
            ["git", "-C", str(ws), "log", "--oneline"],
            capture_output=True, text=True,
        )
        assert "init: workspace setup" in log.stdout

    def test_error_if_already_initialised(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)
        result = run_create("init-repo", ws)
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "already_initialized"

    def test_output_empty_repo_url_without_name(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "README.md").write_text("test\n")
        result = run_create("init-repo", ws)
        out = parse(result)
        assert out.get("REPO_URL", "") == ""


class TestWorkspaceCreateErrors:

    def test_unknown_subcommand(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        result = run_create("bogus", ws)
        assert result.returncode == 1

    def test_no_args_prints_usage(self):
        result = subprocess.run(
            [sys.executable, str(WORKSPACE_CREATE)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_only_subcommand_no_path(self):
        result = subprocess.run(
            [sys.executable, str(WORKSPACE_CREATE), "create-dirs"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1


# ===========================================================================
# artifact_migrate.py
# ===========================================================================

class TestArtifactMigrateScan:

    def test_finds_handoff(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        (proj / "HANDOFF.md").write_text("handoff content\n")
        result = run_migrate("scan", str(proj))
        assert result.returncode == 0
        out = parse(result)
        found = json.loads(out["FOUND"])
        assert "HANDOFF.md" in found

    def test_finds_directory_artifacts(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        (proj / "blog").mkdir()
        (proj / "plans").mkdir()
        result = run_migrate("scan", str(proj))
        out = parse(result)
        found = json.loads(out["FOUND"])
        assert "blog/" in found
        assert "plans/" in found

    def test_finds_docs_subdirs(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        (proj / "docs" / "_posts").mkdir(parents=True)
        (proj / "docs" / "superpowers" / "plans").mkdir(parents=True)
        result = run_migrate("scan", str(proj))
        out = parse(result)
        found = json.loads(out["FOUND"])
        assert "docs/_posts/" in found
        assert "docs/superpowers/plans/" in found

    def test_empty_project_returns_empty_array(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        result = run_migrate("scan", str(proj))
        out = parse(result)
        found = json.loads(out["FOUND"])
        assert found == []

    def test_exits_1_for_nonexistent_project(self, tmp_path):
        result = run_migrate("scan", str(tmp_path / "nonexistent"))
        assert result.returncode == 1


class TestArtifactMigrateMigrate:

    def test_migrates_single_file(self, tmp_path):
        proj = tmp_path / "project"
        ws = tmp_path / "workspace"
        proj.mkdir()
        ws.mkdir()
        (proj / "HANDOFF.md").write_text("handoff content\n")
        result = run_migrate("migrate", str(proj), str(ws), paths="HANDOFF.md")
        assert result.returncode == 0
        out = parse(result)
        assert out["MIGRATED"] == "1"
        assert (ws / "HANDOFF.md").read_text() == "handoff content\n"

    def test_migrates_directory(self, tmp_path):
        proj = tmp_path / "project"
        ws = tmp_path / "workspace"
        proj.mkdir()
        ws.mkdir()
        (proj / "blog").mkdir()
        (proj / "blog" / "entry1.md").write_text("entry 1\n")
        (proj / "blog" / "entry2.md").write_text("entry 2\n")
        result = run_migrate("migrate", str(proj), str(ws), paths="blog/")
        assert result.returncode == 0
        assert (ws / "blog" / "entry1.md").is_file()
        assert (ws / "blog" / "entry2.md").is_file()

    def test_migrates_docs_posts_to_blog(self, tmp_path):
        proj = tmp_path / "project"
        ws = tmp_path / "workspace"
        proj.mkdir()
        ws.mkdir()
        (proj / "docs" / "_posts").mkdir(parents=True)
        (proj / "docs" / "_posts" / "post.md").write_text("post\n")
        result = run_migrate("migrate", str(proj), str(ws), paths="docs/_posts/")
        assert result.returncode == 0
        assert (ws / "blog" / "post.md").is_file()

    def test_migrates_superpowers_plans_to_plans(self, tmp_path):
        proj = tmp_path / "project"
        ws = tmp_path / "workspace"
        proj.mkdir()
        ws.mkdir()
        (proj / "docs" / "superpowers" / "plans").mkdir(parents=True)
        (proj / "docs" / "superpowers" / "plans" / "plan.md").write_text("plan\n")
        result = run_migrate("migrate", str(proj), str(ws), paths="docs/superpowers/plans/")
        assert result.returncode == 0
        assert (ws / "plans" / "plan.md").is_file()

    def test_migrates_multiple_paths(self, tmp_path):
        proj = tmp_path / "project"
        ws = tmp_path / "workspace"
        proj.mkdir()
        ws.mkdir()
        (proj / "HANDOFF.md").write_text("handoff\n")
        (proj / "IDEAS.md").write_text("ideas\n")
        result = run_migrate("migrate", str(proj), str(ws), paths="HANDOFF.md,IDEAS.md")
        assert result.returncode == 0
        out = parse(result)
        assert out["MIGRATED"] == "2"

    def test_error_on_nonexistent_source_path(self, tmp_path):
        proj = tmp_path / "project"
        ws = tmp_path / "workspace"
        proj.mkdir()
        ws.mkdir()
        result = run_migrate("migrate", str(proj), str(ws), paths="nonexistent.md")
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "path_not_found"

    def test_error_on_missing_paths_arg(self, tmp_path):
        proj = tmp_path / "project"
        ws = tmp_path / "workspace"
        proj.mkdir()
        ws.mkdir()
        result = run_migrate("migrate", str(proj), str(ws))
        assert result.returncode == 1

    def test_exits_1_for_nonexistent_project(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        result = run_migrate("migrate", str(tmp_path / "nonexistent"), str(ws), paths="x")
        assert result.returncode == 1

    def test_exits_1_for_nonexistent_workspace(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        result = run_migrate("migrate", str(proj), str(tmp_path / "nonexistent"), paths="x")
        assert result.returncode == 1


class TestArtifactMigrateErrors:

    def test_unknown_subcommand(self, tmp_path):
        result = run_migrate("bogus", str(tmp_path))
        assert result.returncode == 1

    def test_no_args_prints_usage(self):
        result = subprocess.run(
            [sys.executable, str(ARTIFACT_MIGRATE)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_migrate_missing_workspace_arg(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        result = subprocess.run(
            [sys.executable, str(ARTIFACT_MIGRATE), "migrate", str(proj)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1


# ===========================================================================
# hook_install.py
# ===========================================================================

class TestHookInstall:

    def test_installs_hook_file(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        init_git(proj)
        hook_src = tmp_path / "pre-push"
        hook_src.write_text("#!/bin/sh\nexit 0\n")
        result = run_hook("install", proj, f"hook-src={hook_src}", "hook-name=pre-push")
        assert result.returncode == 0
        out = parse(result)
        assert out["INSTALLED"] == "yes"
        installed = proj / ".githooks" / "pre-push"
        assert installed.is_file()
        assert installed.read_text() == "#!/bin/sh\nexit 0\n"

    def test_installed_hook_is_executable(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        init_git(proj)
        hook_src = tmp_path / "pre-push"
        hook_src.write_text("#!/bin/sh\nexit 0\n")
        run_hook("install", proj, f"hook-src={hook_src}", "hook-name=pre-push")
        installed = proj / ".githooks" / "pre-push"
        mode = os.stat(str(installed)).st_mode
        assert mode & 0o111  # at least one execute bit set

    def test_skips_if_hook_already_exists(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        init_git(proj)
        (proj / ".githooks").mkdir()
        existing = proj / ".githooks" / "pre-push"
        existing.write_text("original\n")
        hook_src = tmp_path / "pre-push"
        hook_src.write_text("replacement\n")
        result = run_hook("install", proj, f"hook-src={hook_src}", "hook-name=pre-push")
        out = parse(result)
        assert out["INSTALLED"] == "skipped"
        assert existing.read_text() == "original\n"

    def test_error_no_git_dir(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        # No git init
        hook_src = tmp_path / "pre-push"
        hook_src.write_text("#!/bin/sh\n")
        result = run_hook("install", proj, f"hook-src={hook_src}", "hook-name=pre-push")
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "no_git_dir"

    def test_error_source_not_found(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        init_git(proj)
        result = run_hook("install", proj, "hook-src=/nonexistent/hook", "hook-name=pre-push")
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "source_not_found"

    def test_error_missing_hook_src(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        init_git(proj)
        result = run_hook("install", proj, "hook-name=pre-push")
        assert result.returncode == 1

    def test_error_missing_hook_name(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        init_git(proj)
        hook_src = tmp_path / "hook"
        hook_src.write_text("#!/bin/sh\n")
        result = run_hook("install", proj, f"hook-src={hook_src}")
        assert result.returncode == 1


class TestHookConfigure:

    def test_sets_hooks_path(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        init_git(proj)
        result = run_hook("configure", proj)
        assert result.returncode == 0
        out = parse(result)
        assert out["CONFIGURED"] == "yes"
        # Verify the config was set
        cfg = subprocess.run(
            ["git", "-C", str(proj), "config", "core.hooksPath"],
            capture_output=True, text=True,
        )
        assert cfg.stdout.strip() == ".githooks"

    def test_error_no_git_dir(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        result = run_hook("configure", proj)
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "no_git_dir"


class TestHookInstallErrors:

    def test_unknown_subcommand(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        result = run_hook("bogus", proj)
        assert result.returncode == 1

    def test_no_args_prints_usage(self):
        result = subprocess.run(
            [sys.executable, str(HOOK_INSTALL)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_nonexistent_project(self, tmp_path):
        result = run_hook("install", tmp_path / "nonexistent",
                          "hook-src=/tmp/x", "hook-name=pre-push")
        assert result.returncode == 1
