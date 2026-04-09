#!/usr/bin/env python3
"""
Tests for the git-based garden access model.

Verifies that the coordination primitives used by forage and harvest
work correctly: reading from HEAD, atomic commits, conflict detection,
and rebase recovery. All tests use temporary git repos.
"""

import subprocess
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.garden_fixture import GitGarden, git, git_out


class TestCounterReadFromHead(unittest.TestCase):
    """Counter must be read from git HEAD, not the working tree."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = GitGarden(Path(self.tmp.name))
        self.garden.init_garden("GE-0100")

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_counter_from_committed_state(self):
        counter = self.garden.current_counter()
        self.assertEqual(counter, 100)

    def test_head_ignores_uncommitted_working_tree_changes(self):
        """A partial write to GARDEN.md is invisible to git show HEAD:."""
        # Simulate another session mid-write — corrupt the counter in working tree
        content = (self.garden.root / "GARDEN.md").read_text()
        (self.garden.root / "GARDEN.md").write_text("PARTIAL WRITE IN PROGRESS\n")

        # Reading from HEAD should still return committed state
        head_content = self.garden.read_head("GARDEN.md")
        self.assertIn("GE-0100", head_content)
        self.assertNotIn("PARTIAL WRITE", head_content)

    def test_counter_updates_only_after_commit(self):
        """Incrementing the counter in the working tree doesn't change HEAD."""
        self.garden.increment_counter("GE-0101")

        # Working tree has new counter, HEAD still has old one
        self.assertEqual(self.garden.current_counter(), 100)

        # After commit, HEAD reflects the new counter
        self.garden.commit_all("test: bump counter")
        self.assertEqual(self.garden.current_counter(), 101)


class TestAtomicSubmissionCommit(unittest.TestCase):
    """Submission file and counter update must be committed together."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = GitGarden(Path(self.tmp.name))
        self.garden.init_garden("GE-0100")

    def tearDown(self):
        self.tmp.cleanup()

    def test_submission_and_counter_visible_after_commit(self):
        """After commit, both submission and counter are in HEAD."""
        filename = self.garden.add_submission("GE-0101", "Some gotcha", "testproject")
        self.garden.increment_counter("GE-0101")
        self.garden.commit("submit(testproject): GE-0101 'Some gotcha'",
                           f"submissions/{filename}", "GARDEN.md")

        # Both are now in HEAD
        self.assertEqual(self.garden.current_counter(), 101)
        submissions = self.garden.list_submissions()
        self.assertIn(f"submissions/{filename}", submissions)

    def test_uncommitted_submission_invisible_to_list(self):
        """git ls-tree doesn't see files not yet committed."""
        filename = self.garden.add_submission("GE-0101", "Some gotcha", "testproject")

        # Not committed yet
        submissions = self.garden.list_submissions()
        self.assertNotIn(f"submissions/{filename}", submissions)

    def test_uncommitted_counter_invisible_to_read_head(self):
        """Incrementing counter without committing doesn't affect HEAD."""
        self.garden.increment_counter("GE-0101")
        self.assertEqual(self.garden.current_counter(), 100)  # still old value

    def test_commit_atomicity_both_or_neither(self):
        """If we add both files, both appear in the same commit."""
        filename = self.garden.add_submission("GE-0101", "Some gotcha", "testproject")
        self.garden.increment_counter("GE-0101")
        sha_before = self.garden.head_sha()

        self.garden.commit("submit(testproject): GE-0101 'Some gotcha'",
                           f"submissions/{filename}", "GARDEN.md")

        sha_after = self.garden.head_sha()
        self.assertNotEqual(sha_before, sha_after)

        # Both changes are in the single new commit
        diff = git_out(self.garden.root, "show", "--name-only", "--format=", "HEAD")
        self.assertIn(f"submissions/{filename}", diff)
        self.assertIn("GARDEN.md", diff)


class TestConcurrentCommitConflict(unittest.TestCase):
    """
    Two forage sessions reading the same counter and both trying to commit
    should produce a git conflict. The loser rebases, re-reads the counter
    from new HEAD, renumbers, and re-commits — both submissions end up with
    unique IDs.

    Uses a bare repo as the shared remote so both sessions can push to the
    same origin (non-bare repos reject pushes from other repos).
    """

    def _make_clone(self, bare: Path, name: str) -> "GitGarden":
        """Clone the bare repo and return a GitGarden wrapping it."""
        clone_path = self.root / name
        subprocess.run(
            ["git", "clone", str(bare), str(clone_path)],
            capture_output=True, check=True
        )
        git(clone_path, "config", "user.email", "test@hortora.test")
        git(clone_path, "config", "user.name", "Test Hortora")
        g = GitGarden.__new__(GitGarden)
        g.root = clone_path
        g.submissions = clone_path / "submissions"
        g.submissions.mkdir(exist_ok=True)
        return g

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

        # Bare repo as the shared remote (simulates GitHub or a shared NFS garden)
        self.bare = self.root / "origin.git"
        subprocess.run(["git", "init", "--bare", str(self.bare)],
                       capture_output=True, check=True)

        # Seed the bare repo via a temporary clone
        seed = GitGarden(self.root / "seed")
        git(seed.root, "remote", "add", "origin", str(self.bare))
        seed.init_garden("GE-0100")
        git(seed.root, "push", "-u", "origin", "main")

        # Two independent sessions cloned from the same origin
        self.garden_a = self._make_clone(self.bare, "garden_a")
        self.garden_b = self._make_clone(self.bare, "garden_b")

    def tearDown(self):
        self.tmp.cleanup()

    def test_both_sessions_read_same_counter(self):
        """Before either commits, both clones see GE-0100."""
        self.assertEqual(self.garden_a.current_counter(), 100)
        self.assertEqual(self.garden_b.current_counter(), 100)

    def test_first_push_wins(self):
        """Session A pushes GE-0101 first — succeeds."""
        filename_a = self.garden_a.add_submission("GE-0101", "Session A gotcha", "proj-a")
        self.garden_a.increment_counter("GE-0101")
        self.garden_a.commit("submit(proj-a): GE-0101",
                             f"submissions/{filename_a}", "GARDEN.md")
        result = git(self.garden_a.root, "push", "origin", "main", check=False)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.garden_a.current_counter(), 101)

    def test_second_push_rejected_after_first(self):
        """B commits GE-0101 locally but push is rejected because A pushed first."""
        # A pushes first
        filename_a = self.garden_a.add_submission("GE-0101", "Session A gotcha", "proj-a")
        self.garden_a.increment_counter("GE-0101")
        self.garden_a.commit("submit(proj-a): GE-0101",
                             f"submissions/{filename_a}", "GARDEN.md")
        git(self.garden_a.root, "push", "origin", "main")

        # B also prepared GE-0101 and committed locally
        filename_b = self.garden_b.add_submission("GE-0101", "Session B gotcha", "proj-b")
        self.garden_b.increment_counter("GE-0101")
        self.garden_b.commit("submit(proj-b): GE-0101",
                             f"submissions/{filename_b}", "GARDEN.MD")

        # B's push is rejected — origin has A's commit which B doesn't have
        push_result = git(self.garden_b.root, "push", "origin", "main", check=False)
        self.assertNotEqual(push_result.returncode, 0,
                            "Push should be rejected — A's commit not in B's history")

    def test_rebase_recovery_gives_unique_ids(self):
        """
        After push rejection, B fetches and rebases onto origin/main,
        re-reads the counter from new HEAD (GE-0101 from A), takes GE-0102,
        renames the submission file, and pushes successfully.
        """
        # A commits and pushes GE-0101
        filename_a = self.garden_a.add_submission("GE-0101", "Session A gotcha", "proj-a")
        self.garden_a.increment_counter("GE-0101")
        self.garden_a.commit("submit(proj-a): GE-0101",
                             f"submissions/{filename_a}", "GARDEN.md")
        git(self.garden_a.root, "push", "origin", "main")

        # B also picked GE-0101, commits locally
        filename_b_original = self.garden_b.add_submission(
            "GE-0101", "Session B gotcha", "proj-b"
        )
        self.garden_b.increment_counter("GE-0101")
        self.garden_b.commit("submit(proj-b): GE-0101",
                             f"submissions/{filename_b_original}", "GARDEN.md")

        # B's push rejected — fetch and rebase
        git(self.garden_b.root, "fetch", "origin")
        git(self.garden_b.root, "rebase", "origin/main")

        # B re-reads counter from new HEAD — now GE-0101 (A's commit merged in)
        new_counter = self.garden_b.current_counter()
        self.assertEqual(new_counter, 101)

        # B takes GE-0102, renames file and updates header
        new_filename = filename_b_original.replace("GE-0101", "GE-0102")
        old_path = self.garden_b.submissions / filename_b_original
        new_path = self.garden_b.submissions / new_filename
        old_path.rename(new_path)
        content = new_path.read_text().replace(
            "**Submission ID:** GE-0101", "**Submission ID:** GE-0102"
        )
        new_path.write_text(content)
        self.garden_b.increment_counter("GE-0102")
        git(self.garden_b.root, "rm", f"submissions/{filename_b_original}", check=False)
        self.garden_b.commit("submit(proj-b): GE-0102 'Session B gotcha'",
                             f"submissions/{new_filename}", "GARDEN.md")

        # Push now succeeds
        push_result = git(self.garden_b.root, "push", "origin", "main", check=False)
        self.assertEqual(push_result.returncode, 0, "Rebase + push should succeed")

        # Fetch A's view of origin and verify both unique submissions are there
        git(self.garden_a.root, "fetch", "origin")
        submissions = git_out(
            self.garden_a.root, "ls-tree", "--name-only", "origin/main", "submissions/"
        )
        self.assertIn(filename_a, submissions)
        self.assertIn(new_filename, submissions)
        self.assertNotIn(filename_b_original, submissions)


class TestGitLsTreeSubmissions(unittest.TestCase):
    """Submission listing via git ls-tree — committed files only."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = GitGarden(Path(self.tmp.name))
        self.garden.init_garden("GE-0100")

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_submissions_returns_empty_list(self):
        submissions = self.garden.list_submissions()
        self.assertEqual(submissions, [])

    def test_committed_submission_is_listed(self):
        filename = self.garden.add_submission("GE-0101", "Some gotcha", "proj")
        self.garden.increment_counter("GE-0101")
        self.garden.commit("submit(proj): GE-0101 'Some gotcha'",
                           f"submissions/{filename}", "GARDEN.md")

        submissions = self.garden.list_submissions()
        self.assertIn(f"submissions/{filename}", submissions)

    def test_uncommitted_submission_not_listed(self):
        """File written to disk but not committed is invisible to git ls-tree."""
        filename = self.garden.add_submission("GE-0101", "Not committed yet", "proj")

        submissions = self.garden.list_submissions()
        self.assertNotIn(f"submissions/{filename}", submissions)

    def test_multiple_submissions_all_listed(self):
        filenames = []
        for i, title in enumerate(["Gotcha A", "Gotcha B", "Gotcha C"], start=101):
            ge_id = f"GE-0{i}"
            filename = self.garden.add_submission(ge_id, title, "proj")
            self.garden.increment_counter(ge_id)
            self.garden.commit(f"submit(proj): {ge_id} '{title}'",
                               f"submissions/{filename}", "GARDEN.md")
            filenames.append(filename)

        submissions = self.garden.list_submissions()
        for filename in filenames:
            self.assertIn(f"submissions/{filename}", submissions)

    def test_revise_submission_listed_alongside_new(self):
        filename_new = self.garden.add_submission("GE-0101", "Original gotcha", "proj")
        self.garden.increment_counter("GE-0101")
        self.garden.commit("submit(proj): GE-0101 'Original gotcha'",
                           f"submissions/{filename_new}", "GARDEN.md")

        filename_revise = self.garden.add_submission(
            "GE-0102", "Fix for original", "proj",
            revise=True, target_id="GE-0101"
        )
        self.garden.increment_counter("GE-0102")
        self.garden.commit("submit(proj): GE-0102 revise 'Original gotcha' — fix found",
                           f"submissions/{filename_revise}", "GARDEN.md")

        submissions = self.garden.list_submissions()
        self.assertIn(f"submissions/{filename_new}", submissions)
        self.assertIn(f"submissions/{filename_revise}", submissions)
        self.assertTrue(any("revise" in s for s in submissions))


class TestGitShowHeadContent(unittest.TestCase):
    """git show HEAD:path returns committed content, not working tree."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = GitGarden(Path(self.tmp.name))
        self.garden.init_garden("GE-0100")

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_committed_submission_content(self):
        filename = self.garden.add_submission("GE-0101", "Read me gotcha", "proj")
        self.garden.increment_counter("GE-0101")
        self.garden.commit("submit(proj): GE-0101",
                           f"submissions/{filename}", "GARDEN.md")

        content = self.garden.read_head(f"submissions/{filename}")
        self.assertIn("GE-0101", content)
        self.assertIn("Read me gotcha", content)

    def test_working_tree_modifications_invisible(self):
        """Changes to a file not yet committed don't appear in git show HEAD."""
        filename = self.garden.add_submission("GE-0101", "Original title", "proj")
        self.garden.increment_counter("GE-0101")
        self.garden.commit("submit(proj): GE-0101",
                           f"submissions/{filename}", "GARDEN.md")

        # Modify the file in the working tree (simulate a partial re-write)
        path = self.garden.submissions / filename
        path.write_text("PARTIAL REWRITE IN PROGRESS")

        # HEAD still has the original committed content
        content = self.garden.read_head(f"submissions/{filename}")
        self.assertIn("Original title", content)
        self.assertNotIn("PARTIAL REWRITE", content)

    def test_nonexistent_path_raises(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.garden.read_head("submissions/nonexistent.md")


if __name__ == "__main__":
    unittest.main(verbosity=2)
