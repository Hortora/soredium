"""Checks measure a repo against the right thing, and landed-but-unpublished is not a fault (#515)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
for sub in ("project", "work-slot", ""):
    sys.path.insert(0, str(ROOT / sub) if sub else str(ROOT))

import canonical_sync as cs  # noqa: E402
from verification import repo_checks, close_checks  # noqa: E402
from verification.outcomes import verify_push, VerifyResult  # noqa: E402
import work_health  # noqa: E402
import slot_query  # noqa: E402


def g(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name + "\n")
    g(repo, "add", ".")
    g(repo, "commit", "-q", "-m", f"feat: {name}")
    return g(repo, "rev-parse", "HEAD")


@pytest.fixture
def world(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)],
                   capture_output=True, check=True)
    canon = tmp_path / "family" / "engine"
    canon.mkdir(parents=True)
    g(canon, "init", "-q", "-b", "main")
    g(canon, "config", "user.name", "T")
    g(canon, "config", "user.email", "t@t")
    commit(canon, "a.txt")
    g(canon, "remote", "add", "origin", str(remote))
    g(canon, "push", "-q", "-u", "origin", "main")
    slot = tmp_path / "family" / "slots" / "2"
    slot.mkdir(parents=True)
    (slot / ".slot").write_text("# Slot 2\n")
    clone = slot / "engine"
    subprocess.run(["git", "clone", "-q", str(canon), str(clone)], capture_output=True, check=True)
    g(clone, "config", "user.name", "T")
    g(clone, "config", "user.email", "t@t")
    g(clone, "remote", "rename", "origin", "local")
    return canon, clone, remote


def kinds(findings) -> list[tuple[str, str]]:
    return [(f.severity, f.category) for f in findings]


class TestReference:
    def test_clone_is_measured_against_canonical(self, world):
        canon, clone, _ = world
        assert cs.reference(clone) == ("local/main", "canonical")

    def test_canonical_is_measured_against_its_remote(self, world):
        canon, clone, _ = world
        assert cs.reference(canon) == ("origin/main", "remote")

    def test_repo_with_nothing_to_measure_against(self, tmp_path):
        repo = tmp_path / "solo"
        repo.mkdir()
        g(repo, "init", "-q", "-b", "main")
        assert cs.reference(repo) == ("", "")

    def test_clone_tracking_ref_is_refreshed_before_it_is_used(self, world):
        canon, clone, _ = world
        landed = commit(canon, "landed.txt")
        assert g(clone, "rev-parse", "local/main") != landed       # stale until asked
        cs.reference(clone)
        assert g(clone, "rev-parse", "local/main") == landed


class TestUnpublishedIsNotAFault:
    def test_canonical_ahead_of_its_remote_is_information(self, world):
        canon, clone, _ = world
        commit(canon, "landed.txt")

        assert kinds(repo_checks.check_unpushed_main(canon)) == [("INFO", "unpublished")]
        assert kinds(close_checks.check_main_pushed(canon)) == [("INFO", "unpublished")]
        verdict = verify_push(canon, "main")
        assert verdict.result == VerifyResult.PASS
        assert verdict.evidence["unpublished"] == 1

    def test_canonical_level_with_its_remote_is_clean(self, world):
        canon, clone, _ = world
        assert repo_checks.check_unpushed_main(canon) == []
        assert close_checks.check_main_pushed(canon) == []
        assert verify_push(canon, "main").result == VerifyResult.PASS

    def test_remote_that_moved_is_a_warning_that_names_publishing(self, world, tmp_path):
        canon, clone, remote = world
        other = tmp_path / "other"
        subprocess.run(["git", "clone", "-q", str(remote), str(other)], capture_output=True, check=True)
        g(other, "config", "user.name", "O")
        g(other, "config", "user.email", "o@o")
        commit(other, "theirs.txt")
        g(other, "push", "-q", "origin", "main")
        g(canon, "fetch", "-q", "origin")
        commit(canon, "landed.txt")

        findings = repo_checks.check_unpushed_main(canon)

        assert ("WARN", "remote-moved") in kinds(findings)
        assert not any(f.severity == "ERROR" for f in findings)

    def test_health_check_says_nothing_about_landed_work_awaiting_publish(self, world):
        canon, clone, _ = world
        commit(canon, "landed.txt")
        result = work_health.check_main_divergence(canon, canon)
        assert result is None or "STATUS=warn" not in result


class TestWorkThatHasNotLanded:
    def test_clone_main_ahead_of_canonical_is_an_error(self, world):
        canon, clone, _ = world
        commit(clone, "stray.txt")

        assert kinds(repo_checks.check_unpushed_main(clone)) == [("ERROR", "not-in-canonical")]
        assert kinds(close_checks.check_main_pushed(clone)) == [("ERROR", "not-in-canonical")]
        verdict = verify_push(clone, "main")
        assert verdict.result == VerifyResult.FAIL
        assert verdict.evidence["not_in_canonical"] == 1
        assert "canonical lacks" in work_health.check_main_divergence(clone, clone)

    def test_clone_level_with_canonical_is_clean_with_no_github_remote_at_all(self, world):
        canon, clone, _ = world
        assert g(clone, "remote").split() == ["local"]
        assert repo_checks.check_unpushed_main(clone) == []
        assert verify_push(clone, "main").result == VerifyResult.PASS

    def test_clone_behind_canonical_is_a_warning(self, world):
        canon, clone, _ = world
        commit(canon, "landed.txt")
        assert kinds(repo_checks.check_unpushed_main(clone)) == [("WARN", "behind-canonical")]

    def test_slot_stats_count_work_against_canonical(self, world):
        canon, clone, _ = world
        g(clone, "checkout", "-q", "-b", "issue-1")
        commit(clone, "one.txt")
        commit(clone, "two.txt")
        assert slot_query.get_repo_stats(clone)["commits"] == 2
