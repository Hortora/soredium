"""scripts/slot_backup_setup.py: move existing slots and workspace repos onto the backup path."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import slot_backup_setup as setup  # noqa: E402


def g(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def init(path: Path) -> Path:
    path.mkdir(parents=True)
    g(path, "init", "-q", "-b", "main")
    g(path, "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
    return path


def hook(clone: Path) -> Path:
    return clone / ".git" / "hooks" / "post-commit"


@pytest.fixture
def family(tmp_path):
    root = tmp_path / "family"
    canon = init(root / "engine")
    slot = root / "slots" / "7"
    slot.mkdir(parents=True)
    (slot / ".slot").write_text("# Slot 7\n")

    def clone(name: str, local: bool = True) -> Path:
        dest = slot / name
        subprocess.run(["git", "clone", "-q", str(canon), str(dest)], capture_output=True, check=True)
        if local:
            g(dest, "remote", "rename", "origin", "local")
        else:
            g(dest, "remote", "remove", "origin")
        return dest

    return root, clone


def lines(capsys) -> list[str]:
    return capsys.readouterr().out.splitlines()


class TestHooks:
    def test_dry_run_reports_and_changes_nothing(self, family, capsys):
        root, clone = family
        old = clone("old")
        hook(old).write_text(setup.OLD_HOOK)

        assert setup.main(["hooks", str(root)]) == 0

        out = lines(capsys)
        assert out[0] == "MODE=dry-run"
        assert "REPLACE=7/old" in out
        assert hook(old).read_text() == setup.OLD_HOOK

    def test_apply_replaces_old_installs_missing_and_leaves_custom(self, family, capsys):
        root, clone = family
        old, missing, custom, current = clone("a-old"), clone("b-missing"), clone("c-custom"), clone("d-current")
        hook(old).write_text(setup.OLD_HOOK)
        hook(custom).write_text("#!/bin/sh\necho mine\n")
        setup.slot_git.install_post_commit_hook(current)
        if hook(missing).exists():
            hook(missing).unlink()

        assert setup.main(["hooks", str(root), "--apply"]) == 0

        out = lines(capsys)
        assert {"REPLACED=7/a-old", "INSTALLED=7/b-missing", "CUSTOM_LEFT=7/c-custom", "OK=7/d-current"} <= set(out)
        for repo in (old, missing):
            assert "canonical_sync.py" in hook(repo).read_text()
            assert "git push" not in hook(repo).read_text()
        assert hook(custom).read_text() == "#!/bin/sh\necho mine\n"
        assert out[-1] == "SUMMARY=CUSTOM_LEFT:1, INSTALLED:1, OK:1, REPLACED:1"

    def test_clone_with_no_canonical_keeps_its_hook(self, family, capsys):
        root, clone = family
        stray = clone("stray", local=False)
        hook(stray).write_text(setup.OLD_HOOK)

        setup.main(["hooks", str(root), "--apply"])

        assert any(line.startswith("NO_CANONICAL=7/stray hook=old") for line in lines(capsys))
        assert hook(stray).read_text() == setup.OLD_HOOK

    def test_attic_and_non_numbered_directories_are_ignored(self, family, capsys):
        root, _ = family
        attic = init(root / "slots" / "attic" / "3" / "engine")
        hook(attic).write_text(setup.OLD_HOOK)

        setup.main(["hooks", str(root), "--apply"])

        assert hook(attic).read_text() == setup.OLD_HOOK
        assert not any("attic" in line for line in lines(capsys))


class TestRemotes:
    def _workspace(self, path: Path, remotes: dict[str, str]) -> Path:
        repo = init(path)
        (repo / ".workspace").write_text("project: x\n")
        for name, url in remotes.items():
            g(repo, "remote", "add", name, url)
        return repo

    def test_single_remote_workspace_gets_it_as_backup_remote(self, tmp_path, capsys):
        root = tmp_path / "public"
        repo = self._workspace(root / "fam" / "engine", {"origin": "https://github.com/me/ws.git"})

        setup.main(["remotes", str(root)])
        assert "SET=fam/engine remote=origin url=https://github.com/me/ws.git" in lines(capsys)

        setup.main(["remotes", str(root), "--apply"])
        assert any(line.startswith("SET_DONE=fam/engine") for line in lines(capsys))
        assert g(repo, "config", "--get", "soredium.backupRemote") == "origin"

        setup.main(["remotes", str(root), "--apply"])
        assert "OK=fam/engine remote=origin" in lines(capsys)

    def test_dry_run_sets_nothing(self, tmp_path, capsys):
        root = tmp_path / "public"
        repo = self._workspace(root / "engine", {"origin": "https://github.com/me/ws.git"})
        setup.main(["remotes", str(root)])
        assert subprocess.run(["git", "-C", str(repo), "config", "--get", "soredium.backupRemote"],
                              capture_output=True).returncode != 0

    def test_credentials_in_a_url_are_never_printed(self, tmp_path, capsys):
        root = tmp_path / "public"
        self._workspace(root / "engine", {"origin": "https://someone:s3cr3t-token@github.com/me/ws.git"})
        setup.main(["remotes", str(root)])
        out = capsys.readouterr().out
        assert "s3cr3t-token" not in out and "someone" not in out
        assert "url=https://github.com/me/ws.git" in out

    def test_owner_filter_leaves_other_peoples_remotes_alone(self, tmp_path, capsys):
        root = tmp_path / "public"
        mine = self._workspace(root / "mine", {"origin": "https://tok3n@github.com/Me/ws.git"})
        ssh = self._workspace(root / "ssh", {"origin": "git@github.com:me/other.git"})
        shared = self._workspace(root / "shared", {"origin": "https://github.com/org/ws.git"})

        setup.main(["remotes", str(root), "owner=me", "--apply"])

        out = lines(capsys)
        assert any(line.startswith("SET_DONE=mine") for line in out)
        assert any(line.startswith("SET_DONE=ssh") for line in out)
        assert "OTHER_OWNER=shared remote=origin url=https://github.com/org/ws.git" in out
        assert g(mine, "config", "--get", "soredium.backupRemote") == "origin"
        assert g(ssh, "config", "--get", "soredium.backupRemote") == "origin"
        assert subprocess.run(["git", "-C", str(shared), "config", "--get", "soredium.backupRemote"],
                              capture_output=True).returncode != 0

    def test_workspace_with_a_fork_is_left_to_the_default(self, tmp_path, capsys):
        root = tmp_path / "public"
        repo = self._workspace(root / "engine", {"origin": "https://github.com/org/ws.git",
                                                 "fork": "https://github.com/me/ws.git"})
        setup.main(["remotes", str(root), "--apply"])
        assert "FORK=engine remote=fork" in lines(capsys)
        assert subprocess.run(["git", "-C", str(repo), "config", "--get", "soredium.backupRemote"],
                              capture_output=True).returncode != 0

    def test_repos_without_the_workspace_marker_are_not_touched(self, tmp_path, capsys):
        root = tmp_path / "public"
        project = init(root / "project")
        g(project, "remote", "add", "origin", "https://github.com/org/shared.git")
        setup.main(["remotes", str(root), "--apply"])
        assert lines(capsys)[-1] == "SUMMARY=no workspace repos"


def test_usage_error():
    assert setup.main(["hooks"]) == 2
