#!/usr/bin/env python3
"""
Tests for git-squash scripts: commit_gather.py, rebase_exec.py, branch_swap.py,
and ctx.py base-branch delegation.

Covers: happy path, edge cases, missing args, error conditions.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

COMMIT_GATHER = Path(__file__).parent.parent / "git-squash" / "commit_gather.py"
REBASE_EXEC = Path(__file__).parent.parent / "git-squash" / "rebase_exec.py"
BRANCH_SWAP = Path(__file__).parent.parent / "git-squash" / "branch_swap.py"
CTX = Path(__file__).parent.parent / "git-squash" / "ctx.py"


def run_script(script: Path, *args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script)] + list(args),
        capture_output=True, text=True,
        cwd=cwd,
    )


def parse_kv(result: subprocess.CompletedProcess) -> dict[str, str]:
    """Extract KEY=VALUE pairs from stdout."""
    out: dict[str, str] = {}
    for line in result.stdout.strip().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k] = v
    return out


def init_repo(path: Path, branch: str = "main") -> Path:
    """Initialise a git repo with user config and an initial commit."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", branch, str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test User"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"],
        capture_output=True, check=True,
    )
    return path


def add_commit(repo: Path, filename: str, content: str, message: str, body: str = "") -> str:
    """Add a file and commit. Returns the SHA."""
    filepath = repo / filename
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content)
    subprocess.run(
        ["git", "-C", str(repo), "add", filename],
        capture_output=True, check=True,
    )
    full_msg = f"{message}\n\n{body}" if body else message
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", full_msg],
        capture_output=True, check=True,
    )
    r = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def get_sha(repo: Path, ref: str = "HEAD") -> str:
    r = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", ref],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def commit_count(repo: Path, range_spec: str) -> int:
    r = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--count", range_spec],
        capture_output=True, text=True, check=True,
    )
    return int(r.stdout.strip())


# ===========================================================================
# commit_gather.py
# ===========================================================================

class TestCommitGather:

    def test_missing_args(self):
        result = run_script(COMMIT_GATHER)
        assert result.returncode == 1
        assert "ERROR=missing_args" in result.stderr

    def test_missing_range(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        result = run_script(COMMIT_GATHER, str(repo))
        assert result.returncode == 1
        assert "ERROR=missing_range" in result.stderr

    def test_not_a_repo(self, tmp_path):
        not_repo = tmp_path / "not-a-repo"
        not_repo.mkdir()
        result = run_script(COMMIT_GATHER, str(not_repo), "range=abc..def")
        assert result.returncode == 1
        assert "ERROR=not_a_repo" in result.stderr

    def test_empty_range(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        base = get_sha(repo)
        # No commits after init, so base..HEAD is empty
        result = run_script(COMMIT_GATHER, str(repo), f"range={base}..HEAD")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["commit_count"] == 0
        assert data["commits"] == []

    def test_basic_commit_data(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        base = get_sha(repo)
        add_commit(repo, "src/X.java", "class X {}", "feat: add X")
        result = run_script(COMMIT_GATHER, str(repo), f"range={base}..HEAD")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["commit_count"] == 1
        c = data["commits"][0]
        assert c["subject"] == "feat: add X"
        assert "src/X.java" in c["files"]
        assert c["author"] == "test@test.com"
        assert c["insertions"] == 1
        assert c["deletions"] == 0
        assert len(c["sha"]) == 40

    def test_issue_refs_extracted(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        base = get_sha(repo)
        add_commit(repo, "a.txt", "a", "fix: bug", body="Closes #33\nRefs #44")
        result = run_script(COMMIT_GATHER, str(repo), f"range={base}..HEAD")
        data = json.loads(result.stdout)
        refs = data["commits"][0]["issue_refs"]
        assert len(refs) == 2
        types = {r["type"] for r in refs}
        numbers = {r["number"] for r in refs}
        assert "Closes" in types
        assert "Refs" in types
        assert 33 in numbers
        assert 44 in numbers

    def test_issue_refs_in_subject(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        base = get_sha(repo)
        add_commit(repo, "a.txt", "a", "fix: bug Fixes #7")
        result = run_script(COMMIT_GATHER, str(repo), f"range={base}..HEAD")
        data = json.loads(result.stdout)
        refs = data["commits"][0]["issue_refs"]
        assert len(refs) == 1
        assert refs[0]["type"] == "Fixes"
        assert refs[0]["number"] == 7

    def test_multiple_commits(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        base = get_sha(repo)
        add_commit(repo, "a.txt", "a", "feat: first")
        add_commit(repo, "b.txt", "b", "fix: second")
        add_commit(repo, "c.txt", "c", "docs: third")
        result = run_script(COMMIT_GATHER, str(repo), f"range={base}..HEAD")
        data = json.loads(result.stdout)
        assert data["commit_count"] == 3
        subjects = [c["subject"] for c in data["commits"]]
        # git log is newest first
        assert "docs: third" in subjects
        assert "fix: second" in subjects
        assert "feat: first" in subjects

    def test_multiple_files_in_commit(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        base = get_sha(repo)
        (repo / "a.txt").write_text("aaa")
        (repo / "b.txt").write_text("bbb")
        subprocess.run(
            ["git", "-C", str(repo), "add", "a.txt", "b.txt"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "feat: two files"],
            capture_output=True, check=True,
        )
        result = run_script(COMMIT_GATHER, str(repo), f"range={base}..HEAD")
        data = json.loads(result.stdout)
        files = data["commits"][0]["files"]
        assert "a.txt" in files
        assert "b.txt" in files

    def test_conventional_commit_detection_true(self, tmp_path):
        """80% conventional commits before range -> is_conventional=true"""
        repo = init_repo(tmp_path / "repo")
        # Create 20 conventional commits before range
        for i in range(20):
            add_commit(repo, f"pre{i}.txt", str(i), f"feat: pre-commit {i}")
        base = get_sha(repo)
        add_commit(repo, "target.txt", "x", "feat: target")
        result = run_script(COMMIT_GATHER, str(repo), f"range={base}..HEAD")
        data = json.loads(result.stdout)
        assert data["is_conventional"] is True

    def test_conventional_commit_detection_false(self, tmp_path):
        """<80% conventional commits before range -> is_conventional=false"""
        repo = init_repo(tmp_path / "repo")
        # Create 20 non-conventional commits
        for i in range(20):
            add_commit(repo, f"pre{i}.txt", str(i), f"random commit number {i}")
        base = get_sha(repo)
        add_commit(repo, "target.txt", "x", "another random commit")
        result = run_script(COMMIT_GATHER, str(repo), f"range={base}..HEAD")
        data = json.loads(result.stdout)
        assert data["is_conventional"] is False

    def test_pr_null_when_no_gh(self, tmp_path):
        """PR should be null when gh is not available or not in a PR context."""
        repo = init_repo(tmp_path / "repo")
        base = get_sha(repo)
        add_commit(repo, "a.txt", "a", "feat: something")
        result = run_script(COMMIT_GATHER, str(repo), f"range={base}..HEAD")
        data = json.loads(result.stdout)
        # In test env, gh pr view won't work — pr should be null
        assert data["pr"] is None

    def test_patch_id_present(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        base = get_sha(repo)
        add_commit(repo, "a.txt", "content", "feat: add a")
        result = run_script(COMMIT_GATHER, str(repo), f"range={base}..HEAD")
        data = json.loads(result.stdout)
        assert data["commits"][0]["patch_id"] != ""

    def test_body_captured(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        base = get_sha(repo)
        add_commit(repo, "a.txt", "a", "feat: with body", body="This is the body text.")
        result = run_script(COMMIT_GATHER, str(repo), f"range={base}..HEAD")
        data = json.loads(result.stdout)
        assert "This is the body text." in data["commits"][0]["body"]

    def test_deletions_counted(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        add_commit(repo, "a.txt", "line1\nline2\nline3\n", "setup")
        base = get_sha(repo)
        # Modify file: remove lines
        (repo / "a.txt").write_text("line1\n")
        subprocess.run(
            ["git", "-C", str(repo), "add", "a.txt"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "fix: trim"],
            capture_output=True, check=True,
        )
        result = run_script(COMMIT_GATHER, str(repo), f"range={base}..HEAD")
        data = json.loads(result.stdout)
        assert data["commits"][0]["deletions"] > 0


# ===========================================================================
# rebase_exec.py
# ===========================================================================

class TestRebaseExecSingle:

    def test_missing_args(self):
        result = run_script(REBASE_EXEC)
        assert result.returncode == 1
        out = parse_kv(result)
        assert out.get("ERROR") == "missing_args"

    def test_not_a_repo(self, tmp_path):
        not_repo = tmp_path / "not-a-repo"
        not_repo.mkdir()
        result = run_script(REBASE_EXEC, "single", str(not_repo))
        assert result.returncode == 1
        out = parse_kv(result)
        assert out.get("ERROR") == "not_a_repo"

    def test_single_squash(self, tmp_path):
        """Squash 2 commits into 1."""
        repo = init_repo(tmp_path / "repo")
        add_commit(repo, "a.txt", "a", "feat: first")
        add_commit(repo, "b.txt", "b", "fix: second")
        # Before: init + 2 = at least 2 after init
        result = run_script(REBASE_EXEC, "single", str(repo))
        assert result.returncode == 0
        out = parse_kv(result)
        assert out["SQUASHED"] == "yes"
        # Both files should still exist
        assert (repo / "a.txt").exists()
        assert (repo / "b.txt").exists()
        # Verify commit count decreased
        r = subprocess.run(
            ["git", "-C", str(repo), "log", "--oneline"],
            capture_output=True, text=True,
        )
        # Should have init + 1 squashed = 2 commits total
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        assert len(lines) == 2

    def test_single_fails_with_one_commit(self, tmp_path):
        """Only init commit — can't squash HEAD~1."""
        repo = init_repo(tmp_path / "repo")
        result = run_script(REBASE_EXEC, "single", str(repo))
        assert result.returncode == 1
        out = parse_kv(result)
        assert out.get("ERROR") == "single_failed"


class TestRebaseExecMulti:

    def test_missing_base_and_todo(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        result = run_script(REBASE_EXEC, "multi", str(repo))
        assert result.returncode == 1
        out = parse_kv(result)
        assert out.get("ERROR") == "missing_args"

    def test_multi_rebase(self, tmp_path):
        """Squash 3 commits into 1 using a todo file."""
        repo = init_repo(tmp_path / "repo")
        base_sha = get_sha(repo)
        sha1 = add_commit(repo, "a.txt", "a", "feat: first")
        sha2 = add_commit(repo, "b.txt", "b", "fix: second")
        sha3 = add_commit(repo, "c.txt", "c", "docs: third")

        # Create todo file: pick first, squash rest
        todo = tmp_path / "todo"
        todo.write_text(
            f"pick {sha1[:7]} feat: first\n"
            f"squash {sha2[:7]} fix: second\n"
            f"squash {sha3[:7]} docs: third\n"
        )

        result = run_script(REBASE_EXEC, "multi", str(repo),
                          f"base={base_sha}", f"todo-file={todo}")
        assert result.returncode == 0
        out = parse_kv(result)
        assert out["REBASED"] == "yes"
        assert out["COMMITS_BEFORE"] == "3"
        assert out["COMMITS_AFTER"] == "1"

        # Verify all files present
        assert (repo / "a.txt").exists()
        assert (repo / "b.txt").exists()
        assert (repo / "c.txt").exists()

    def test_multi_pick_all(self, tmp_path):
        """Pick all commits — count should not change."""
        repo = init_repo(tmp_path / "repo")
        base_sha = get_sha(repo)
        sha1 = add_commit(repo, "a.txt", "a", "feat: first")
        sha2 = add_commit(repo, "b.txt", "b", "fix: second")

        todo = tmp_path / "todo"
        todo.write_text(
            f"pick {sha1[:7]} feat: first\n"
            f"pick {sha2[:7]} fix: second\n"
        )

        result = run_script(REBASE_EXEC, "multi", str(repo),
                          f"base={base_sha}", f"todo-file={todo}")
        assert result.returncode == 0
        out = parse_kv(result)
        assert out["COMMITS_BEFORE"] == "2"
        assert out["COMMITS_AFTER"] == "2"


class TestRebaseExecAmendMessage:

    def test_amend_message(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        add_commit(repo, "a.txt", "a", "old message")
        result = run_script(REBASE_EXEC, "amend-message", str(repo),
                          "message=new message")
        assert result.returncode == 0
        out = parse_kv(result)
        assert out["AMENDED"] == "yes"

        # Verify message changed
        r = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%s"],
            capture_output=True, text=True,
        )
        assert r.stdout.strip() == "new message"

    def test_amend_missing_message(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        add_commit(repo, "a.txt", "a", "old")
        result = run_script(REBASE_EXEC, "amend-message", str(repo))
        assert result.returncode == 1
        out = parse_kv(result)
        assert out.get("ERROR") == "missing_args"

    def test_unknown_subcommand(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        result = run_script(REBASE_EXEC, "bogus", str(repo))
        assert result.returncode == 1
        out = parse_kv(result)
        assert out.get("ERROR") == "unknown_subcommand"


# ===========================================================================
# branch_swap.py
# ===========================================================================

class TestBranchSwap:

    def test_missing_args(self):
        result = run_script(BRANCH_SWAP)
        assert result.returncode == 1
        out = parse_kv(result)
        assert out.get("ERROR") == "missing_args"

    def test_missing_orig_or_work(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        result = run_script(BRANCH_SWAP, str(repo), "orig=main")
        assert result.returncode == 1
        out = parse_kv(result)
        assert out.get("ERROR") == "missing_args"

    def test_not_a_repo(self, tmp_path):
        not_repo = tmp_path / "not-a-repo"
        not_repo.mkdir()
        result = run_script(BRANCH_SWAP, str(not_repo), "orig=main", "work=feat")
        assert result.returncode == 1
        out = parse_kv(result)
        assert out.get("ERROR") == "not_a_repo"

    def test_swap_branches(self, tmp_path):
        """Create orig + work branches, swap, verify names changed."""
        repo = init_repo(tmp_path / "repo")
        # Create orig branch with a file
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-b", "feature-x"],
            capture_output=True, check=True,
        )
        add_commit(repo, "orig.txt", "original", "feat: original work")

        # Create work branch from feature-x
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-b", "squash/wip-feature-x"],
            capture_output=True, check=True,
        )
        add_commit(repo, "squashed.txt", "squashed", "feat: squashed work")

        # Switch to main so we can rename branches
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "main"],
            capture_output=True, check=True,
        )

        result = run_script(BRANCH_SWAP, str(repo),
                          "orig=feature-x", "work=squash/wip-feature-x")
        assert result.returncode == 0
        out = parse_kv(result)
        assert out["SWAPPED"] == "yes"
        assert "backup/pre-squash-feature-x-" in out["BACKUP"]

        # Verify: feature-x now points to what was squash/wip-feature-x
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "feature-x"],
            capture_output=True, check=True,
        )
        assert (repo / "squashed.txt").exists()

        # Verify: backup branch has the original work
        r = subprocess.run(
            ["git", "-C", str(repo), "branch", "--list", "backup/*"],
            capture_output=True, text=True,
        )
        assert "backup/pre-squash-feature-x-" in r.stdout

    def test_swap_reports_backup_on_failure(self, tmp_path):
        """If work rename fails, backup name is still reported."""
        repo = init_repo(tmp_path / "repo")
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-b", "feat"],
            capture_output=True, check=True,
        )
        add_commit(repo, "a.txt", "a", "feat: a")
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "main"],
            capture_output=True, check=True,
        )

        # Try to swap with non-existent work branch
        result = run_script(BRANCH_SWAP, str(repo),
                          "orig=feat", "work=nonexistent")
        assert result.returncode == 1
        out = parse_kv(result)
        assert out.get("ERROR") == "swap_failed"
        assert "BACKUP" in out  # backup was created before failure

    def test_swap_push_failure_non_fatal(self, tmp_path):
        """Push failure doesn't block the swap — reports PUSH_FAILED instead."""
        repo = init_repo(tmp_path / "repo")
        # No remote, so push will fail
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-b", "feat"],
            capture_output=True, check=True,
        )
        add_commit(repo, "a.txt", "a", "feat: a")
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-b", "squash/wip"],
            capture_output=True, check=True,
        )
        add_commit(repo, "b.txt", "b", "feat: b")
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "main"],
            capture_output=True, check=True,
        )

        result = run_script(BRANCH_SWAP, str(repo),
                          "orig=feat", "work=squash/wip")
        assert result.returncode == 0
        out = parse_kv(result)
        assert out["SWAPPED"] == "yes"
        assert out["UPSTREAM_SET"] in ("yes", "no")
        assert out.get("PUSH_FAILED") == "yes"

    def test_status_clean_reported(self, tmp_path):
        """STATUS_CLEAN reflects working tree state."""
        repo = init_repo(tmp_path / "repo")
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-b", "feat"],
            capture_output=True, check=True,
        )
        add_commit(repo, "a.txt", "a", "feat: a")
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-b", "squash/wip"],
            capture_output=True, check=True,
        )
        add_commit(repo, "b.txt", "b", "feat: b")
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "main"],
            capture_output=True, check=True,
        )

        result = run_script(BRANCH_SWAP, str(repo),
                          "orig=feat", "work=squash/wip")
        out = parse_kv(result)
        assert out["STATUS_CLEAN"] in ("yes", "no")


# ===========================================================================
# ctx.py — base-branch delegation
# ===========================================================================

class TestCtxBaseBranch:

    def test_base_branch_from_claude_md(self, tmp_path):
        """Without base-branch arg, parses CLAUDE.md."""
        repo = init_repo(tmp_path / "repo")
        (repo / "CLAUDE.md").write_text(
            "# Project\n\n**Project base branch:** `develop`\n"
        )
        result = run_script(CTX, cwd=str(repo))
        assert result.returncode == 0
        out = parse_kv(result)
        assert out["BASE_BRANCH"] == "develop"

    def test_base_branch_default_main(self, tmp_path):
        """No CLAUDE.md -> defaults to main."""
        repo = init_repo(tmp_path / "repo")
        result = run_script(CTX, cwd=str(repo))
        assert result.returncode == 0
        out = parse_kv(result)
        assert out["BASE_BRANCH"] == "main"

    def test_base_branch_arg_overrides_claude_md(self, tmp_path):
        """base-branch=<value> takes precedence over CLAUDE.md."""
        repo = init_repo(tmp_path / "repo")
        (repo / "CLAUDE.md").write_text(
            "# Project\n\n**Project base branch:** `develop`\n"
        )
        result = run_script(CTX, "base-branch=release", cwd=str(repo))
        assert result.returncode == 0
        out = parse_kv(result)
        assert out["BASE_BRANCH"] == "release"

    def test_base_branch_arg_without_claude_md(self, tmp_path):
        """base-branch= works even without CLAUDE.md."""
        repo = init_repo(tmp_path / "repo")
        result = run_script(CTX, "base-branch=trunk", cwd=str(repo))
        assert result.returncode == 0
        out = parse_kv(result)
        assert out["BASE_BRANCH"] == "trunk"

    def test_other_fields_still_present(self, tmp_path):
        """base-branch arg doesn't break other output fields."""
        repo = init_repo(tmp_path / "repo")
        result = run_script(CTX, "base-branch=main", cwd=str(repo))
        assert result.returncode == 0
        out = parse_kv(result)
        assert "ORIG_BRANCH" in out
        assert "WORK_BRANCH" in out
        assert "UPSTREAM_REMOTE" in out
