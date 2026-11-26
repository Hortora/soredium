"""#483: nothing is removed from a source until the destination is verified to hold it,
and an image the source has must arrive with the document that refers to it."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PUBLISH = ROOT / "publish-blog" / "blog_publish.py"


def g(repo: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=check).stdout.strip()


def init(path: Path) -> Path:
    path.mkdir(parents=True)
    g(path, "init", "-q", "-b", "main")
    g(path, "config", "user.name", "T")
    g(path, "config", "user.email", "t@t")
    (path / "README.md").write_text("init\n")
    g(path, "add", ".")
    g(path, "commit", "-q", "-m", "init")
    return path


def run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)


def entry_with_images(repo: Path, sub: str = "blog") -> Path:
    blog = repo / sub
    (blog / "images").mkdir(parents=True)
    (blog / "images" / "diagram.svg").write_text("<svg>diagram</svg>")
    (blog / "images" / "second.svg").write_text("<svg>second</svg>")
    entry = blog / "2026-01-01-entry.md"
    entry.write_text("# Entry\n\n![diagram](images/diagram.svg)\n\n"
                     '<img src="images/second.svg">\n')
    g(repo, "add", ".")
    g(repo, "commit", "-q", "-m", "docs: entry with images")
    return entry


class TestCopyEntry:
    def test_images_the_entry_refers_to_arrive_with_it(self, tmp_path):
        """The reproducer in #483: images existed in the workspace and never reached docs/blog."""
        ws = init(tmp_path / "workspace")
        entry = entry_with_images(ws)
        dest = tmp_path / "project" / "docs" / "blog"

        result = run(PUBLISH, "copy-entry", str(entry), str(dest))

        assert result.returncode == 0, result.stdout + result.stderr
        assert "COPIED=yes" in result.stdout
        assert (dest / "images" / "diagram.svg").read_text() == "<svg>diagram</svg>"
        assert (dest / "images" / "second.svg").read_text() == "<svg>second</svg>"
        assert "IMAGES_VERIFIED=2" in result.stdout

    def test_an_image_that_cannot_be_written_fails_the_copy(self, tmp_path):
        ws = init(tmp_path / "workspace")
        entry = entry_with_images(ws)
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "images").write_text("a file where the images directory must go\n")

        result = run(PUBLISH, "copy-entry", str(entry), str(dest))

        assert result.returncode == 1
        assert "ERROR=image_not_copied" in result.stdout
        assert "COPIED=yes" not in result.stdout

    def test_a_reference_the_source_never_had_is_a_warning_only(self, tmp_path):
        """Example syntax in a document, or an image that was never drawn: nothing can be
        lost by the copy, so it does not block it."""
        ws = init(tmp_path / "workspace")
        (ws / "blog").mkdir()
        entry = ws / "blog" / "entry.md"
        entry.write_text("# Entry\n\n![never existed](images/missing.png)\n")

        result = run(PUBLISH, "copy-entry", str(entry), str(tmp_path / "dest"))

        assert result.returncode == 0
        assert "WARN=image_not_found: images/missing.png" in result.stdout


class TestRemoveSource:
    def _published(self, tmp_path, commit_dest: bool = True):
        ws = init(tmp_path / "workspace")
        entry = entry_with_images(ws)
        site = init(tmp_path / "site")
        dest = site / "_notes"
        copied = run(PUBLISH, "copy-entry", str(entry), str(dest))
        assert copied.returncode == 0, copied.stdout + copied.stderr
        if commit_dest:
            g(site, "add", ".")
            g(site, "commit", "-q", "-m", "publish")
        return ws, site, dest

    def test_refuses_without_naming_a_verified_destination(self, tmp_path):
        ws, site, dest = self._published(tmp_path)

        result = run(PUBLISH, "remove-source", str(ws), "files=blog/2026-01-01-entry.md")

        assert result.returncode != 0
        assert (ws / "blog" / "2026-01-01-entry.md").exists()

    def test_removes_when_the_destination_holds_it_committed(self, tmp_path):
        ws, site, dest = self._published(tmp_path)

        result = run(PUBLISH, "remove-source", str(ws), "files=blog/2026-01-01-entry.md",
                     f"verified-in={dest}")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "REMOVED=1" in result.stdout
        assert not (ws / "blog" / "2026-01-01-entry.md").exists()
        assert g(ws, "status", "--porcelain") == ""

    def test_refuses_when_the_destination_copy_is_missing(self, tmp_path):
        ws, site, dest = self._published(tmp_path)
        g(site, "rm", "-q", "_notes/2026-01-01-entry.md")
        g(site, "commit", "-q", "-m", "oops")
        before = g(ws, "rev-parse", "HEAD")

        result = run(PUBLISH, "remove-source", str(ws), "files=blog/2026-01-01-entry.md",
                     f"verified-in={dest}")

        assert result.returncode == 1
        assert "ERROR=not_verified" in result.stdout
        assert (ws / "blog" / "2026-01-01-entry.md").exists()
        assert g(ws, "rev-parse", "HEAD") == before

    def test_refuses_when_the_destination_copy_differs(self, tmp_path):
        ws, site, dest = self._published(tmp_path)
        (dest / "2026-01-01-entry.md").write_text("truncated")
        g(site, "commit", "-q", "-am", "damaged")

        result = run(PUBLISH, "remove-source", str(ws), "files=blog/2026-01-01-entry.md",
                     f"verified-in={dest}")

        assert result.returncode == 1
        assert "differs" in result.stdout
        assert (ws / "blog" / "2026-01-01-entry.md").exists()

    def test_refuses_when_the_destination_copy_is_not_committed(self, tmp_path):
        """Copied but uncommitted is one `git clean` away from gone."""
        ws, site, dest = self._published(tmp_path, commit_dest=False)

        result = run(PUBLISH, "remove-source", str(ws), "files=blog/2026-01-01-entry.md",
                     f"verified-in={dest}")

        assert result.returncode == 1
        assert "not committed" in result.stdout
        assert (ws / "blog" / "2026-01-01-entry.md").exists()

    def test_refuses_when_an_image_did_not_reach_the_destination(self, tmp_path):
        ws, site, dest = self._published(tmp_path)
        g(site, "rm", "-q", "_notes/images/diagram.svg")
        g(site, "commit", "-q", "-m", "image lost")

        result = run(PUBLISH, "remove-source", str(ws), "files=blog/2026-01-01-entry.md",
                     f"verified-in={dest}")

        assert result.returncode == 1
        assert "images/diagram.svg" in result.stdout
        assert (ws / "blog" / "2026-01-01-entry.md").exists()

    def test_one_unverified_file_means_nothing_is_removed(self, tmp_path):
        ws, site, dest = self._published(tmp_path)
        (ws / "blog" / "other.md").write_text("never published\n")
        g(ws, "add", ".")
        g(ws, "commit", "-q", "-m", "docs: other")

        result = run(PUBLISH, "remove-source", str(ws),
                     "files=blog/2026-01-01-entry.md,blog/other.md", f"verified-in={dest}")

        assert result.returncode == 1
        assert (ws / "blog" / "2026-01-01-entry.md").exists()
        assert (ws / "blog" / "other.md").exists()

    def test_every_named_destination_must_hold_it(self, tmp_path):
        ws, site, dest = self._published(tmp_path)
        other = init(tmp_path / "other-site")

        result = run(PUBLISH, "remove-source", str(ws), "files=blog/2026-01-01-entry.md",
                     f"verified-in={dest},{other / '_notes'}")

        assert result.returncode == 1
        assert (ws / "blog" / "2026-01-01-entry.md").exists()

    def test_source_repo_on_another_branch_is_not_switched(self, tmp_path):
        ws, site, dest = self._published(tmp_path)
        g(ws, "checkout", "-q", "-b", "issue-1")

        result = run(PUBLISH, "remove-source", str(ws), "files=blog/2026-01-01-entry.md",
                     f"verified-in={dest}")

        assert g(ws, "branch", "--show-current") == "issue-1"
        assert result.returncode == 0, result.stdout + result.stderr
        assert g(ws, "show", "main:blog/2026-01-01-entry.md", check=False) == ""   # removed on main
        assert (ws / "blog" / "2026-01-01-entry.md").exists()                      # checkout untouched
        assert len(g(ws, "worktree", "list").splitlines()) == 1

    def test_a_refused_removal_commit_puts_the_files_back(self, tmp_path):
        ws, site, dest = self._published(tmp_path)
        hook = ws / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)

        result = run(PUBLISH, "remove-source", str(ws), "files=blog/2026-01-01-entry.md",
                     f"verified-in={dest}")

        assert result.returncode == 1
        assert "ERROR=git_commit_failed" in result.stdout
        assert (ws / "blog" / "2026-01-01-entry.md").exists()
        assert g(ws, "status", "--porcelain") == ""


class TestCommitDestination:
    def test_never_switches_the_destination_checkout(self, tmp_path):
        site = init(tmp_path / "site")
        g(site, "checkout", "-q", "-b", "draft")
        (site / "_notes").mkdir()
        (site / "_notes" / "entry.md").write_text("entry\n")

        result = run(PUBLISH, "commit-destination", str(site), "files=_notes/entry.md",
                     "message=chore: publish")

        assert result.returncode == 1
        assert "ERROR=dest_not_on_main" in result.stdout
        assert g(site, "branch", "--show-current") == "draft"

    def test_publishes_through_canonical_sync_and_says_so(self, tmp_path):
        site = init(tmp_path / "site")
        bare = tmp_path / "site.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)],
                       capture_output=True, check=True)
        g(site, "remote", "add", "origin", str(bare))
        g(site, "push", "-q", "-u", "origin", "main")
        (site / "_notes").mkdir()
        (site / "_notes" / "entry.md").write_text("entry\n")

        result = run(PUBLISH, "commit-destination", str(site), "files=_notes/entry.md",
                     "message=chore: publish")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "COMMITTED=yes" in result.stdout
        assert "PUBLISHED=origin" in result.stdout
        assert g(bare, "rev-parse", "main") == g(site, "rev-parse", "main")

    def test_a_failed_publish_is_an_error_with_the_commit_kept(self, tmp_path):
        site = init(tmp_path / "site")
        g(site, "remote", "add", "origin", str(tmp_path / "gone.git"))
        (site / "_notes").mkdir()
        (site / "_notes" / "entry.md").write_text("entry\n")

        result = run(PUBLISH, "commit-destination", str(site), "files=_notes/entry.md",
                     "message=chore: publish")

        assert result.returncode == 1
        assert "COMMITTED=yes" in result.stdout
        assert "PUBLISHED=no" in result.stdout
        assert g(site, "show", "main:_notes/entry.md") == "entry"


