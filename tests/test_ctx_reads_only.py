"""Resolving context changes no file in the workspace or project (Hortora/soredium#574)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _d in ("project", "work-slot"):
    sys.path.insert(0, str(ROOT / _d))

import ctx  # noqa: E402


def g(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def tree(directory: Path) -> dict[str, bytes]:
    return {str(p.relative_to(directory)): p.read_bytes()
            for p in sorted(directory.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(directory).parts}


def workspace_with(tmp_path: Path, files: dict[str, str]) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    g(ws, "init", "-q", "-b", "main")
    for name, text in files.items():
        path = ws / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    g(ws, "add", "-A")
    g(ws, "commit", "-q", "-m", "init")
    return ws


PLAN = "- [ ] o/r#1 — Task        ← active\n\n## State\nbranch: \nstate: active\nissue-repo: o/r\n"


def test_a_workspace_with_an_old_plan_file_is_read_and_not_changed(tmp_path, monkeypatch):
    ws = workspace_with(tmp_path, {".plan": PLAN, "notes.md": "n"})
    before = tree(ws)
    monkeypatch.chdir(ws)

    context = ctx.resolve()

    assert tree(ws) == before
    assert g(ws, "status", "--porcelain") == ""
    assert context["HAS_QUEUE"] == "yes" or context.get("HAS_PLAN") == "yes"


def test_a_legacy_design_layout_is_reported_and_not_moved(tmp_path, monkeypatch):
    ws = workspace_with(tmp_path, {"design/.plan": PLAN, "design/JOURNAL.md": "j",
                                   "design/.meta": "covers: 1\n"})
    before = tree(ws)
    monkeypatch.chdir(ws)

    context = ctx.resolve()

    assert tree(ws) == before
    assert context["LEGACY_LAYOUT"] == str(ws / "design")


def test_a_current_workspace_reports_no_legacy_layout(tmp_path, monkeypatch):
    ws = workspace_with(tmp_path, {".queue": PLAN.replace("state:", "status:")})
    before = tree(ws)
    monkeypatch.chdir(ws)
    context = ctx.resolve()
    assert tree(ws) == before
    assert context["LEGACY_LAYOUT"] == ""


def test_stale_workspace_marker_is_not_rewritten(tmp_path, monkeypatch):
    """ctx.py must not write .workspace when it names the wrong project (#610)."""
    proj = tmp_path / "project"
    proj.mkdir()
    g(proj, "init", "-q", "-b", "main")
    (proj / "README.md").write_text("project\n")
    g(proj, "add", "-A")
    g(proj, "commit", "-q", "-m", "init")

    ws = workspace_with(tmp_path, {
        ".workspace": "project: /tmp/wrong-project\ncreated: 2026-01-01\n",
        ".queue": PLAN.replace("state:", "status:"),
    })
    (ws / "proj").symlink_to(proj)
    g(ws, "add", "-A")
    g(ws, "commit", "-q", "-m", "add proj symlink", "--allow-empty")

    before = tree(ws)
    monkeypatch.chdir(ws)

    context = ctx.resolve()

    assert tree(ws) == before, ".workspace file was rewritten by ctx.resolve()"
    assert g(ws, "status", "--porcelain") == ""
    assert context["WORKSPACE_VALID"] == "marker_stale"


def test_the_explicit_command_converts_the_legacy_layout(tmp_path):
    ws = workspace_with(tmp_path, {"design/.plan": PLAN, "design/JOURNAL.md": "j"})
    done = subprocess.run(["python3", str(ROOT / "work-slot" / "plan_migrate.py"), "to-root", str(ws)],
                          capture_output=True, text=True)
    assert done.returncode == 0 and "MIGRATED=yes" in done.stdout
    assert (ws / ".plan").read_text() == PLAN
    assert (ws / "JOURNAL.md").read_text() == "j"
