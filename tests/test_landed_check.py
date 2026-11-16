"""Whether work recorded as landed is really on the base branch (#527).

Real git repos throughout. The archive gate (`verify_landed_shas`) and the
shared check behind it (`landed_check.content_on_base`) are both exercised.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

import slot_metadata
from slot_test_helpers import init_repo_with_remote


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args],
                            capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _commit(repo: Path, files: dict[str, str | None], message: str) -> str:
    for name, content in files.items():
        path = repo / name
        if content is None:
            _git(repo, "rm", "-q", name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def family(tmp_path):
    root = tmp_path / "family"
    root.mkdir()
    (root / "slots" / "1").mkdir(parents=True)
    init_repo_with_remote(root / "engine")
    return root


def _repo(family: Path) -> Path:
    return family / "engine"


def _slot(family: Path) -> Path:
    return family / "slots" / "1"


def _record(family: Path, sha: str) -> None:
    (_slot(family) / ".landed").write_text(
        f"branch=feature\nrepos=engine\nlanded_shas=engine:{sha}\n")


def _verify(family: Path) -> tuple[bool, list[str]]:
    return slot_metadata.verify_landed_shas(_slot(family), family)


def _branch(family: Path) -> Path:
    repo = _repo(family)
    _git(repo, "checkout", "-q", "-b", "feature")
    return repo


class TestWorkThatDidNotLand:
    def test_docs_only_work_is_not_landed(self, family):
        repo = _branch(family)
        sha = _commit(repo, {"docs/spec.md": "the design\n"}, "docs: add the spec")
        _git(repo, "checkout", "-q", "main")
        _record(family, sha)

        ok, failures = _verify(family)

        assert ok is False
        assert "docs/spec.md" in failures[0]

    def test_image_only_work_is_not_landed(self, family):
        repo = _branch(family)
        (repo / "diagram.png").write_bytes(b"\x89PNG\r\n\x00\x01\x02")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "docs: diagram")
        sha = _git(repo, "rev-parse", "HEAD")
        _git(repo, "checkout", "-q", "main")
        _record(family, sha)

        ok, _ = _verify(family)

        assert ok is False

    def test_same_subject_with_different_content_is_not_landed(self, family):
        repo = _branch(family)
        sha = _commit(repo, {"a.py": "print('branch')\n"}, "fix: the thing")
        _git(repo, "checkout", "-q", "main")
        _commit(repo, {"b.py": "print('unrelated')\n"}, "fix: the thing")
        _record(family, sha)

        ok, failures = _verify(family)

        assert ok is False
        assert "a.py" in failures[0]

    def test_partly_landed_branch_is_not_landed(self, family):
        repo = _branch(family)
        _commit(repo, {"a.py": "a = 1\n"}, "feat: a")
        sha = _commit(repo, {"notes.md": "notes\n"}, "docs: notes")
        _git(repo, "checkout", "-q", "main")
        _commit(repo, {"a.py": "a = 1\n"}, "feat: a")
        _record(family, sha)

        ok, failures = _verify(family)

        assert ok is False
        assert "notes.md" in failures[0]

    def test_file_base_changed_differently_is_not_landed(self, family):
        repo = _branch(family)
        sha = _commit(repo, {"a.py": "x = 1\n", "b.py": "b = 1\n"}, "feat: x")
        _git(repo, "checkout", "-q", "main")
        _commit(repo, {"a.py": "x = 2\n", "b.py": "b = 1\n"}, "feat: other x")
        _commit(repo, {"a.py": "x = 3\n", "b.py": "b = 2\n"}, "feat: move on")
        _record(family, sha)

        ok, failures = _verify(family)

        assert ok is False
        assert "a.py" in failures[0]
        assert "b.py" not in failures[0]

    def test_deletion_base_never_made_is_not_landed(self, family):
        repo = _branch(family)
        sha = _commit(repo, {"README.md": None}, "chore: drop readme")
        _git(repo, "checkout", "-q", "main")
        _commit(repo, {"README.md": "# engine, edited\n"}, "docs: edit readme")
        _record(family, sha)

        ok, failures = _verify(family)

        assert ok is False
        assert "README.md" in failures[0]

    def test_sha_missing_from_canonical_is_not_landed(self, family):
        _record(family, "0123456789abcdef0123456789abcdef01234567")

        ok, failures = _verify(family)

        assert ok is False
        assert "not found" in failures[0]

    def test_unrelated_history_is_not_landed(self, family):
        repo = _repo(family)
        _git(repo, "checkout", "-q", "--orphan", "island")
        sha = _commit(repo, {"island.txt": "x\n"}, "island")
        _git(repo, "checkout", "-q", "-f", "main")
        _record(family, sha)

        ok, _ = _verify(family)

        assert ok is False


class TestWorkThatLanded:
    def test_fast_forwarded_work(self, family):
        repo = _branch(family)
        sha = _commit(repo, {"docs/spec.md": "spec\n"}, "docs: spec")
        _git(repo, "checkout", "-q", "main")
        _git(repo, "merge", "-q", "--ff-only", "feature")
        _record(family, sha)

        assert _verify(family) == (True, [])

    def test_rebased_work_recorded_under_its_old_sha(self, family):
        repo = _branch(family)
        _commit(repo, {"docs/spec.md": "spec\n"}, "docs: spec")
        old_tip = _commit(repo, {"a.py": "a = 1\n"}, "feat: a")
        _git(repo, "checkout", "-q", "main")
        _commit(repo, {"other.txt": "moved on\n"}, "chore: main moved")
        _git(repo, "checkout", "-q", "feature")
        _git(repo, "rebase", "-q", "main")
        _git(repo, "checkout", "-q", "main")
        _git(repo, "merge", "-q", "--ff-only", "feature")
        _record(family, old_tip)

        assert _verify(family) == (True, [])

    def test_squashed_work_under_a_different_subject(self, family):
        repo = _branch(family)
        _commit(repo, {"docs/spec.md": "spec\n"}, "wip: spec")
        tip = _commit(repo, {"a.py": "a = 1\n"}, "wip: a")
        _git(repo, "checkout", "-q", "main")
        _git(repo, "merge", "-q", "--squash", "feature")
        _git(repo, "commit", "-q", "-m", "feat: a with its spec")
        _record(family, tip)

        assert _verify(family) == (True, [])

    def test_squashed_work_after_main_changed_the_same_file(self, family):
        repo = _branch(family)
        _commit(repo, {"README.md": "# engine\n\nfeature notes\n"}, "wip: notes")
        tip = _commit(repo, {"a.py": "a = 1\n"}, "wip: a")
        _git(repo, "checkout", "-q", "main")
        _git(repo, "merge", "-q", "--squash", "feature")
        _git(repo, "commit", "-q", "-m", "feat: a")
        _commit(repo, {"README.md": "# engine\n\nfeature notes\n\nlater edit\n"},
                "docs: later edit")
        _record(family, tip)

        assert _verify(family) == (True, [])

    def test_landed_with_extra_changes_then_base_moved_on(self, family):
        import landed_check
        repo = _branch(family)
        _commit(repo, {"README.md": "# engine\n\nfeature notes\n"}, "wip: notes")
        tip = _commit(repo, {"a.py": "a = 1\n"}, "wip: a")
        _git(repo, "checkout", "-q", "main")
        _commit(repo, {"README.md": "# engine\n\nfeature notes\n", "a.py": "a = 1\n",
                       "extra.txt": "landed alongside\n"}, "feat: a and more")
        _commit(repo, {"README.md": "# engine\n\nrewritten\n", "a.py": "a = 2\n"},
                "refactor: move on")
        _record(family, tip)

        assert _verify(family) == (True, [])
        assert landed_check.content_on_base(repo, tip, "main").method == "content_in_history"

    def test_deletion_that_landed_before_base_restored_the_file(self, family):
        repo = _branch(family)
        tip = _commit(repo, {"README.md": None, "a.py": "a = 1\n"}, "chore: drop readme")
        _git(repo, "checkout", "-q", "main")
        _commit(repo, {"README.md": None, "a.py": "a = 1\n", "x.txt": "x\n"}, "chore: drop")
        _commit(repo, {"README.md": "# back\n", "a.py": "a = 2\n"}, "docs: readme back")
        _record(family, tip)

        assert _verify(family) == (True, [])

    def test_lifecycle_files_on_the_branch_are_not_compared(self, family):
        repo = _branch(family)
        _commit(repo, {"a.py": "a = 1\n"}, "feat: a")
        tip = _commit(repo, {".close-state": "phase=land\n", "JOURNAL.md": "j\n"},
                      "chore: lifecycle")
        _git(repo, "checkout", "-q", "main")
        _commit(repo, {"a.py": "a = 1\n"}, "feat: a")
        _record(family, tip)

        assert _verify(family) == (True, [])

    def test_deletion_that_landed(self, family):
        repo = _branch(family)
        tip = _commit(repo, {"README.md": None}, "chore: drop readme")
        _git(repo, "checkout", "-q", "main")
        _commit(repo, {"README.md": None, "x.txt": "x\n"}, "chore: drop readme and add x")
        _record(family, tip)

        assert _verify(family) == (True, [])


class TestContentOnBase:
    def test_reports_how_it_was_proved(self, family):
        import landed_check
        repo = _branch(family)
        sha = _commit(repo, {"a.py": "a = 1\n"}, "feat: a")
        _git(repo, "checkout", "-q", "main")
        _git(repo, "merge", "-q", "--ff-only", "feature")

        result = landed_check.content_on_base(repo, sha, "main")

        assert result.landed is True
        assert result.method == "ancestry"

    def test_lists_the_files_that_are_missing(self, family):
        import landed_check
        repo = _branch(family)
        sha = _commit(repo, {"docs/a.md": "a\n", "docs/b.md": "b\n"}, "docs: two")
        _git(repo, "checkout", "-q", "main")

        result = landed_check.content_on_base(repo, sha, "main")

        assert result.landed is False
        assert result.missing == ["docs/a.md", "docs/b.md"]

    def test_unknown_base_branch_is_not_landed(self, family):
        import landed_check
        repo = _repo(family)
        sha = _git(repo, "rev-parse", "HEAD")

        result = landed_check.content_on_base(repo, sha, "no-such-branch")

        assert result.landed is False

    def test_outcomes_check_fails_docs_only_work(self, family):
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from verification.outcomes import verify_content_landed, VerifyResult
        repo = _branch(family)
        sha = _commit(repo, {"docs/spec.md": "spec\n"}, "docs: spec")
        _git(repo, "checkout", "-q", "main")

        assert verify_content_landed(repo, sha, "main").result == VerifyResult.FAIL
