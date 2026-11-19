#!/usr/bin/env python3
"""
Blog publishing operations for publish-blog skill.

Externalised from SKILL.md Step 6, 7, 8 OPERATION blocks.

Three rules hold throughout (#483, #515):
  - an image the source has travels with the document that refers to it, and the
    copy fails if it does not arrive;
  - nothing is removed from a source until every named destination is verified
    to hold it, committed, byte for byte, images included;
  - no checkout is switched, and the only thing that reaches a remote is the
    destination's base branch, through project/canonical_sync.py.
"""

import shutil
import sys
import subprocess
from pathlib import Path

_skills_root = Path(__file__).resolve().parent.parent
for _entry in (str(_skills_root), str(_skills_root / "project")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from verification.repo_checks import extract_image_refs  # noqa: E402
import canonical_sync  # noqa: E402
from canonical_sync import SyncError  # noqa: E402


def _trace(action: str, **details) -> None:
    """Record in the worklog; never fails the publish."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "project"))
        import worktrace
        worktrace.record(action, **details)
    except Exception as error:
        print(f"WARN=worklog_not_recorded action={action} detail={error}", file=sys.stderr)


def _image_dest(md_dest_dir: Path, raw_ref: str) -> Path:
    return md_dest_dir / raw_ref.lstrip("/")


def copy_entry(source_path: str, dest_dir: str) -> None:
    """
    Copy a single blog entry file, and the images it refers to, to a destination directory.

    Output:
        COPIED=yes on success
        IMAGE_COPIED=<ref> for each image written
        IMAGES_VERIFIED=<n> images the source has that are now at the destination
        WARN=image_not_found: <ref> for a reference the source itself does not have
        ERROR=source_not_found if source doesn't exist
        ERROR=copy_failed on copy error
        ERROR=image_not_copied: <ref> when an image the source has did not arrive
    """
    src = Path(source_path)
    if not src.exists():
        print("ERROR=source_not_found", flush=True)
        sys.exit(1)

    dest = Path(dest_dir)
    try:
        dest.mkdir(parents=True, exist_ok=True)
        dest_file = dest / src.name
        dest_file.write_bytes(src.read_bytes())
    except Exception as e:
        print(f"ERROR=copy_failed: {e}", flush=True)
        sys.exit(1)

    verified = 0
    for raw_ref, resolved_src in extract_image_refs(src):
        if not resolved_src.is_file():
            # Nothing to lose: the source never had it (example syntax, or never drawn).
            print(f"WARN=image_not_found: {raw_ref}", flush=True)
            continue
        img_dest = _image_dest(dest, raw_ref)
        try:
            img_dest.parent.mkdir(parents=True, exist_ok=True)
            if not img_dest.is_file() or img_dest.read_bytes() != resolved_src.read_bytes():
                shutil.copy2(str(resolved_src), str(img_dest))
                print(f"IMAGE_COPIED={raw_ref}", flush=True)
        except Exception as e:
            print(f"ERROR=image_not_copied: {raw_ref}: {e}", flush=True)
            sys.exit(1)
        if not img_dest.is_file() or img_dest.read_bytes() != resolved_src.read_bytes():
            print(f"ERROR=image_not_copied: {raw_ref}", flush=True)
            sys.exit(1)
        verified += 1

    print(f"IMAGES_VERIFIED={verified}", flush=True)
    print("COPIED=yes", flush=True)


def _current_branch(repo: str) -> str:
    result = subprocess.run(
        ["git", "-C", repo, "branch", "--show-current"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def commit_destination(dest_repo: str, files_csv: str, message: str) -> None:
    """
    Add and commit files in the destination repo, then publish its base branch.

    The destination must already be on its base branch: the entries were copied
    into its working tree, and switching branches underneath them is not this
    script's call. Publishing goes through canonical_sync (fetch, settle on the
    remote, plain push; never forced).

    Output:
        COMMITTED=yes
        PUBLISHED=<remote>|none|no     (none: the repo has no remote)
        ERROR=dest_not_on_main branch=<name>
        ERROR=publish_failed: <detail>  (the commit is kept)
    """
    repo_path = Path(dest_repo)
    files = [f.strip() for f in files_csv.split(",") if f.strip()]

    try:
        base = canonical_sync.locate(dest_repo).base
    except SyncError as error:
        print(f"ERROR=no_canonical: {error.detail}", flush=True)
        sys.exit(1)
    branch = _current_branch(dest_repo)
    if branch != base:
        print(f"ERROR=dest_not_on_main branch={branch or 'DETACHED'}", flush=True)
        print(f"ERROR_DETAIL={repo_path.name} must be on {base} to receive published entries; "
              f"it was not switched", flush=True)
        sys.exit(1)

    for file in files:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "add", file],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"ERROR=git_add_failed: {result.stderr}", flush=True)
            sys.exit(1)

    result = subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-m", message],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR=git_commit_failed: {result.stderr or result.stdout}", flush=True)
        sys.exit(1)
    print("COMMITTED=yes", flush=True)

    try:
        published = canonical_sync.publish_base(dest_repo)
    except SyncError as error:
        print("PUBLISHED=no", flush=True)
        print(f"ERROR=publish_failed: {error.detail}", flush=True)
        sys.exit(1)
    print(f"PUBLISHED={published.published}", flush=True)
    _trace("blog-publish", repo=dest_repo, files=files, remote=published.published,
           sha=published.sha)
    for warning in published.warnings:
        print(f"WARN={warning}", flush=True)


def _committed_bytes(path: Path) -> bytes | None:
    """The bytes git has committed for `path` at HEAD of the repo it is in, None when it
    is not committed there (missing, untracked, or only staged)."""
    top = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    if top.returncode != 0:
        return None
    try:
        rel = path.resolve().relative_to(Path(top.stdout.strip()).resolve())
    except ValueError:
        return None
    shown = subprocess.run(["git", "-C", top.stdout.strip(), "show", f"HEAD:{rel.as_posix()}"],
                           capture_output=True)
    return shown.stdout if shown.returncode == 0 else None


def unverified(source_file: Path, destinations: list[Path]) -> list[str]:
    """Why `source_file` may not be removed yet: one line per shortfall, empty when every
    destination holds it and its images, committed and identical."""
    problems: list[str] = []
    content = source_file.read_bytes()
    images = [(ref, src) for ref, src in extract_image_refs(source_file) if src.is_file()]
    for dest_dir in destinations:
        copy = dest_dir / source_file.name
        if not dest_dir.is_dir() or not copy.is_file():
            problems.append(f"{source_file.name}: missing from {dest_dir}")
            continue
        committed = _committed_bytes(copy)
        if committed is None:
            problems.append(f"{source_file.name}: not committed in {dest_dir}")
        elif committed != content:
            problems.append(f"{source_file.name}: differs from the copy in {dest_dir}")
        for raw_ref, src in images:
            image_copy = _image_dest(dest_dir, raw_ref)
            image_committed = _committed_bytes(image_copy) if image_copy.is_file() else None
            if image_committed is None:
                problems.append(f"{source_file.name}: image {raw_ref} missing or not "
                                f"committed in {dest_dir}")
            elif image_committed != src.read_bytes():
                problems.append(f"{source_file.name}: image {raw_ref} differs in {dest_dir}")
    return problems


def remove_source(source_repo: str, files_csv: str, verified_in: str = "") -> None:
    """
    Remove published entries from the source repo, once every named destination is
    verified to hold them.

    Args:
        source_repo: Path to source git repository
        files_csv: Comma-separated list of files to remove (relative to repo)
        verified_in: Comma-separated destination directories that must each hold
            every file, committed and byte-identical, with the images it refers to

    If any file falls short anywhere, nothing at all is removed. The removal is a
    commit on the source repo's base branch, made without switching its checkout.

    Output:
        REMOVED=<count>
        ERROR=not_verified, with one NOT_VERIFIED=<reason> line per shortfall
        ERROR=verified_in_required
    """
    repo_path = Path(source_repo)
    files = [f.strip() for f in files_csv.split(",") if f.strip()]
    destinations = [Path(d.strip()) for d in verified_in.split(",") if d.strip()]
    if not destinations:
        print("ERROR=verified_in_required", flush=True)
        print("ERROR_DETAIL=name the destination directories that hold the entries: "
              "verified-in=<dir>[,<dir>]. Nothing was removed.", flush=True)
        sys.exit(1)

    problems: list[str] = []
    for file in files:
        source_file = repo_path / file
        if not source_file.is_file():
            problems.append(f"{file}: not found in {repo_path.name}")
            continue
        problems += unverified(source_file, destinations)
    if problems:
        print("ERROR=not_verified", flush=True)
        for problem in problems:
            print(f"NOT_VERIFIED={problem}", flush=True)
        print("ERROR_DETAIL=nothing was removed", flush=True)
        sys.exit(1)

    try:
        base = canonical_sync.locate(source_repo).base
        with canonical_sync.checked_out(source_repo, base) as tree:
            result = subprocess.run(["git", "-C", str(tree), "rm", "-q", "--", *files],
                                    capture_output=True, text=True)
            if result.returncode != 0:
                print(f"ERROR=git_rm_failed: {result.stderr}", flush=True)
                sys.exit(1)
            result = subprocess.run(
                ["git", "-C", str(tree), "commit", "-m", "chore: remove published blog entries",
                 "-m", "no-issue: verified present in every destination before removal"],
                capture_output=True, text=True)
            if result.returncode != 0:
                # Put back exactly what this call removed; nothing else is touched.
                subprocess.run(["git", "-C", str(tree), "reset", "-q", "HEAD", "--", *files],
                               capture_output=True)
                subprocess.run(["git", "-C", str(tree), "checkout", "-q", "--", *files],
                               capture_output=True)
                print(f"ERROR=git_commit_failed: {result.stderr or result.stdout}", flush=True)
                sys.exit(1)
    except SyncError as error:
        print(f"ERROR={error.code}: {error.detail}", flush=True)
        sys.exit(1)

    print(f"REMOVED={len(files)}", flush=True)


def check_present_fn(entry_path: str, dest_dir: str) -> bool:
    src = Path(entry_path)
    dest = Path(dest_dir) / src.name
    return dest.exists()


def check_present(entry_path: str, dest_dir: str) -> None:
    present = check_present_fn(entry_path, dest_dir)
    print(f"PRESENT={'yes' if present else 'no'}", flush=True)


def verify_parity_fn(routing_yaml: str) -> list[dict]:
    import yaml
    config = yaml.safe_load(Path(routing_yaml).read_text())
    destinations = config.get("destinations", {})
    defaults = config.get("defaults", {}).get("destinations", [])
    if len(defaults) < 2:
        return []
    dest_entries: dict[str, set[str]] = {}
    for name in defaults:
        dest_config = destinations.get(name, {})
        dest_path = Path(dest_config.get("path", "")).expanduser()
        subdir = dest_config.get("subdir", "")
        full_path = dest_path / subdir if subdir else dest_path
        if full_path.is_dir():
            dest_entries[name] = {f.name for f in full_path.iterdir()
                                  if f.is_file() and f.suffix == ".md"}
        else:
            dest_entries[name] = set()
    all_entries = set()
    for entries in dest_entries.values():
        all_entries |= entries
    missing = []
    for entry in sorted(all_entries):
        for name in defaults:
            if entry not in dest_entries.get(name, set()):
                missing.append({"entry": entry, "missing_dest": name})
    return missing


def verify_parity(routing_yaml: str) -> None:
    missing = verify_parity_fn(routing_yaml)
    if not missing:
        print("PARITY=yes", flush=True)
        print("MISSING_COUNT=0", flush=True)
        return
    print("PARITY=no", flush=True)
    print(f"MISSING_COUNT={len(missing)}", flush=True)
    for i, m in enumerate(missing, 1):
        print(f"MISSING_{i}={m['entry']} dest={m['missing_dest']}", flush=True)


def main() -> None:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: blog_publish.py <subcommand> [args...]", file=sys.stderr)
        print("Subcommands:", file=sys.stderr)
        print("  plan <project-or-workspace> [routing=<path>]", file=sys.stderr)
        print("  copy-entry <source-path> <dest-dir>", file=sys.stderr)
        print("  commit-destination <dest-repo> files=<csv> message=<msg>",
              file=sys.stderr)
        print("  remove-source <source-repo> files=<csv> verified-in=<dir>[,<dir>]",
              file=sys.stderr)
        sys.exit(1)

    subcommand = sys.argv[1]

    if subcommand == "plan":
        if len(sys.argv) < 3:
            print("Usage: plan <project-or-workspace> [routing=<path>]",
                  file=sys.stderr)
            sys.exit(1)
        from blog_routing import plan_cli
        routing = None
        for arg in sys.argv[3:]:
            if arg.startswith("routing="):
                routing = arg[8:]
        plan_cli(sys.argv[2], routing)

    elif subcommand == "copy-entry":
        if len(sys.argv) != 4:
            print("Usage: copy-entry <source-path> <dest-dir>", file=sys.stderr)
            sys.exit(1)
        copy_entry(sys.argv[2], sys.argv[3])

    elif subcommand == "commit-destination":
        if len(sys.argv) != 5:
            print("Usage: commit-destination <dest-repo> files=<csv> message=<msg>",
                  file=sys.stderr)
            sys.exit(1)
        dest_repo = sys.argv[2]
        files_arg = sys.argv[3]
        message_arg = sys.argv[4]

        if not files_arg.startswith("files="):
            print("ERROR: Second arg must be files=<csv>", file=sys.stderr)
            sys.exit(1)
        if not message_arg.startswith("message="):
            print("ERROR: Third arg must be message=<msg>", file=sys.stderr)
            sys.exit(1)

        files_csv = files_arg[6:]  # Strip "files="
        message = message_arg[8:]  # Strip "message="
        commit_destination(dest_repo, files_csv, message)

    elif subcommand == "remove-source":
        if len(sys.argv) not in (4, 5):
            print("Usage: remove-source <source-repo> files=<csv> verified-in=<dir>[,<dir>]",
                  file=sys.stderr)
            sys.exit(1)
        source_repo = sys.argv[2]
        files_arg = sys.argv[3]

        if not files_arg.startswith("files="):
            print("ERROR: Second arg must be files=<csv>", file=sys.stderr)
            sys.exit(1)
        verified_in = ""
        if len(sys.argv) == 5:
            if not sys.argv[4].startswith("verified-in="):
                print("ERROR: Third arg must be verified-in=<dir>[,<dir>]", file=sys.stderr)
                sys.exit(1)
            verified_in = sys.argv[4][len("verified-in="):]

        files_csv = files_arg[6:]  # Strip "files="
        remove_source(source_repo, files_csv, verified_in)

    elif subcommand == "check-present":
        if len(sys.argv) != 4:
            print("Usage: check-present <entry-path> <dest-dir>", file=sys.stderr)
            sys.exit(1)
        check_present(sys.argv[2], sys.argv[3])

    elif subcommand == "verify-parity":
        if len(sys.argv) != 3:
            print("Usage: verify-parity <routing-yaml>", file=sys.stderr)
            sys.exit(1)
        verify_parity(sys.argv[2])

    else:
        print(f"ERROR: Unknown subcommand '{subcommand}'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
