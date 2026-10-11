"""Tests for project/progress.py — typed progress tracking."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
from progress import Progress, StepStatus


class TestStepStatus:
    def test_done_values(self):
        assert StepStatus.DONE.is_complete()
        assert StepStatus.SKIPPED.is_complete()
        assert StepStatus.SKIPPED_ERROR.is_complete()
        assert not StepStatus.PENDING.is_complete()
        assert not StepStatus.RUNNING.is_complete()


class TestProgressBasics:
    def test_empty_progress(self):
        p = Progress()
        assert not p.is_done("anything")
        assert p.get_attempt("anything") == 0
        assert p.get_produced("anything") == 0

    def test_mark_done(self):
        p = Progress()
        p.mark_done("review")
        assert p.is_done("review")
        assert p.status("review") == StepStatus.DONE

    def test_mark_done_with_produced(self):
        p = Progress()
        p.mark_done("land", produced=3)
        assert p.is_done("land")
        assert p.get_produced("land") == 3

    def test_mark_skipped(self):
        p = Progress()
        p.mark_skipped("review")
        assert p.is_done("review")
        assert p.status("review") == StepStatus.SKIPPED

    def test_mark_skipped_error(self):
        p = Progress()
        p.mark_skipped_error("review")
        assert p.is_done("review")
        assert p.status("review") == StepStatus.SKIPPED_ERROR

    def test_increment_attempt(self):
        p = Progress()
        assert p.get_attempt("review") == 0
        p.increment_attempt("review")
        assert p.get_attempt("review") == 1
        p.increment_attempt("review")
        assert p.get_attempt("review") == 2

    def test_reset_attempt(self):
        p = Progress()
        p.increment_attempt("review")
        p.increment_attempt("review")
        p.reset_attempt("review")
        assert p.get_attempt("review") == 0

    def test_set_and_get_value(self):
        p = Progress()
        p.set("sweep_selected", "forage,protocol")
        assert p.get("sweep_selected") == "forage,protocol"

    def test_get_default(self):
        p = Progress()
        assert p.get("nonexistent", "default") == "default"

    def test_landed_shas(self):
        p = Progress()
        p.set_landed_sha("myrepo", "abc123")
        assert p.get_landed_sha("myrepo") == "abc123"
        assert p.get_landed_sha("other") == ""


class TestProgressSerialization:
    def test_round_trip(self, tmp_path):
        p = Progress()
        p.mark_done("review")
        p.mark_done("land", produced=3)
        p.mark_skipped("forage")
        p.increment_attempt("squash")
        p.increment_attempt("squash")
        p.set("sweep_selected", "forage,protocol")
        p.set_landed_sha("myrepo", "abc123")
        p.save(tmp_path)

        loaded = Progress.load(tmp_path)
        assert loaded.is_done("review")
        assert loaded.is_done("land")
        assert loaded.get_produced("land") == 3
        assert loaded.is_done("forage")
        assert loaded.status("forage") == StepStatus.SKIPPED
        assert loaded.get_attempt("squash") == 2
        assert loaded.get("sweep_selected") == "forage,protocol"
        assert loaded.get_landed_sha("myrepo") == "abc123"

    def test_backward_compat_read(self, tmp_path):
        (tmp_path / ".work-progress").write_text(
            "review=done\n"
            "land=done\n"
            "land_produced=3\n"
            "squash_attempt=2\n"
            "forage=skipped\n"
            "sweep_selected=forage,protocol\n"
            "_landed_sha:myrepo=abc123\n"
        )
        loaded = Progress.load(tmp_path)
        assert loaded.is_done("review")
        assert loaded.get_produced("land") == 3
        assert loaded.get_attempt("squash") == 2
        assert loaded.status("forage") == StepStatus.SKIPPED
        assert loaded.get("sweep_selected") == "forage,protocol"
        assert loaded.get_landed_sha("myrepo") == "abc123"

    def test_legacy_close_progress(self, tmp_path):
        (tmp_path / ".close-progress").write_text("review=done\n")
        loaded = Progress.load(tmp_path)
        assert loaded.is_done("review")

    def test_empty_workspace(self, tmp_path):
        loaded = Progress.load(tmp_path)
        assert not loaded.is_done("anything")

    def test_save_creates_work_progress(self, tmp_path):
        p = Progress()
        p.mark_done("review")
        p.save(tmp_path)
        assert (tmp_path / ".work-progress").exists()

    def test_per_repo_done(self):
        p = Progress()
        p.mark_done("land:myrepo")
        p.mark_done("land:other")
        assert p.is_per_repo_done("land")

    def test_per_repo_partial(self):
        p = Progress()
        p.mark_done("land:myrepo")
        p.set("land:other", "running")
        assert not p.is_per_repo_done("land")

    def test_per_repo_all_one_repo_done(self):
        p = Progress()
        p.mark_done("land:myrepo")
        assert p.is_per_repo_done("land")


class TestProgressDictCompat:
    def test_as_dict(self):
        p = Progress()
        p.mark_done("review")
        p.set("sweep_selected", "forage")
        d = p.as_dict()
        assert d["review"] == "done"
        assert d["sweep_selected"] == "forage"

    def test_from_dict(self):
        d = {"review": "done", "land_produced": "3", "squash_attempt": "2",
             "_landed_sha:myrepo": "abc123"}
        p = Progress.from_dict(d)
        assert p.is_done("review")
        assert p.get_produced("land") == 3
        assert p.get_attempt("squash") == 2
        assert p.get_landed_sha("myrepo") == "abc123"

    def test_contains(self):
        p = Progress()
        p.mark_done("review")
        assert "review" in p
        assert "nonexistent" not in p
