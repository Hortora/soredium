#!/usr/bin/env python3
"""
issue_setup.py — GitHub issue workflow operations

Subcommands:
  create-labels <repo>                          Create standard issue labels
  install-hooks <project>                       Install commit-msg hook
  create-epic <repo> title=<t> body-file=<path> Create epic issue
  create-issue <repo> title=<t> body-file=<path> labels=<csv> Create issue
  update-scope <repo> epic=<N> body-file=<path> Update epic body

All commands output KEY=VALUE pairs on stdout for easy parsing.
"""

import subprocess
import sys
from pathlib import Path


# Standard GitHub labels (name, color, description)
STANDARD_LABELS = [
    ("epic", "7057ff", "Parent issue grouping related work"),
    ("enhancement", "84b6eb", "New feature or improvement"),
    ("bug", "d73a4a", "Something is broken"),
    ("documentation", "0075ca", "Documentation only"),
    ("performance", "e4e669", "Performance improvement"),
    ("security", "e11d48", "Security fix or hardening"),
    ("refactor", "6e6e6e", "Code change without user-visible effect"),
]

# Scale and complexity labels
SCALE_LABELS = [
    ("scale: XS", "d4edda", "Lines of change"),
    ("scale: S", "a8d5b5", "Single class / small file"),
    ("scale: M", "f0c27f", "Multi-class / multi-file"),
    ("scale: L", "e8956d", "Substantial feature"),
    ("scale: XL", "c0392b", "Major rework"),
]

COMPLEXITY_LABELS = [
    ("complexity: Low", "dbeafe", "Clear path, no unknowns"),
    ("complexity: Med", "93c5fd", "Some design or unknowns"),
    ("complexity: High", "1d4ed8", "Significant unknowns, design required"),
]

ALL_LABELS = STANDARD_LABELS + SCALE_LABELS + COMPLEXITY_LABELS


def run_gh(args: list[str]) -> tuple[int, str, str]:
    """Run gh command, return (exit_code, stdout, stderr)."""
    result = subprocess.run(
        ["gh"] + args,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def create_labels(repo: str) -> None:
    """Create all standard labels. Skip existing."""
    created = 0
    for name, color, desc in ALL_LABELS:
        args = [
            "label", "create", name,
            "--repo", repo,
            "--color", color,
            "--description", desc,
        ]
        exit_code, _, stderr = run_gh(args)
        # gh label create returns 0 on success, non-zero if label exists
        # We treat existing labels as success (idempotent)
        if exit_code == 0:
            created += 1
    print(f"CREATED={created}")


def install_hooks(project: str) -> None:
    """Install commit-msg hook to .githooks/ and configure git."""
    project_path = Path(project).resolve()
    if not project_path.is_dir():
        print(f"ERROR=project_not_found path={project_path}")
        sys.exit(1)

    # Find the hook source — skill directory is parent of this script
    skill_dir = Path(__file__).parent
    hook_src = skill_dir / "hooks" / "commit-msg"

    if not hook_src.is_file():
        print(f"ERROR=hook_source_missing path={hook_src}")
        sys.exit(1)

    githooks_dir = project_path / ".githooks"
    hook_dest = githooks_dir / "commit-msg"

    if hook_dest.exists():
        print("INSTALLED=skipped")
        return

    # Create .githooks/ and copy hook
    githooks_dir.mkdir(exist_ok=True)
    hook_dest.write_text(hook_src.read_text())
    hook_dest.chmod(0o755)

    # Configure git to use .githooks/
    try:
        subprocess.run(
            ["git", "-C", str(project_path), "config", "core.hooksPath", ".githooks"],
            capture_output=True, text=True, check=True,
        )

        # Stage and commit the hook
        subprocess.run(
            ["git", "-C", str(project_path), "add", ".githooks/commit-msg"],
            capture_output=True, text=True, check=True,
        )
        # Use no-issue bypass since we're installing the hook that requires issues
        subprocess.run(
            [
                "git", "-C", str(project_path), "commit", "-m",
                "chore: add commit-msg hook — require issue ref on every commit  no-issue: hook setup"
            ],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"ERROR=install_failed")
        return

    print("INSTALLED=yes")


def create_epic(repo: str, title: str | None, body_file: str | None) -> None:
    """Create epic issue."""
    if not title:
        print("ERROR=missing_title")
        sys.exit(1)

    if not body_file:
        print("ERROR=missing_body_file")
        sys.exit(1)

    body_path = Path(body_file)
    if not body_path.is_file():
        print(f"ERROR=body_file_not_found path={body_file}")
        sys.exit(1)

    with body_path.open() as f:
        body = f.read()

    args = [
        "issue", "create",
        "--repo", repo,
        "--title", title,
        "--label", "epic",
        "--body", body,
    ]
    exit_code, stdout, stderr = run_gh(args)

    if exit_code != 0:
        print(f"ERROR=gh_failed stderr={stderr.strip()}")
        sys.exit(1)

    # Extract issue number from URL in stdout
    # Format: https://github.com/owner/repo/issues/123
    for line in stdout.splitlines():
        if "/issues/" in line:
            issue_num = line.rstrip("/").split("/")[-1]
            print(f"ISSUE_NUMBER={issue_num}")
            return

    print("ERROR=could_not_parse_issue_number")
    sys.exit(1)


def create_issue(repo: str, title: str | None, body_file: str | None, labels: str | None) -> None:
    """Create child issue with labels."""
    if not title:
        print("ERROR=missing_title")
        sys.exit(1)

    if not body_file:
        print("ERROR=missing_body_file")
        sys.exit(1)

    if not labels:
        print("ERROR=missing_labels")
        sys.exit(1)

    body_path = Path(body_file)
    if not body_path.is_file():
        print(f"ERROR=body_file_not_found path={body_file}")
        sys.exit(1)

    with body_path.open() as f:
        body = f.read()

    # Split labels by comma and pass each as separate --label
    label_list = [lbl.strip() for lbl in labels.split(",")]
    args = [
        "issue", "create",
        "--repo", repo,
        "--title", title,
        "--body", body,
    ]
    for lbl in label_list:
        args.extend(["--label", lbl])

    exit_code, stdout, stderr = run_gh(args)

    if exit_code != 0:
        print(f"ERROR=gh_failed stderr={stderr.strip()}")
        sys.exit(1)

    # Extract issue number
    for line in stdout.splitlines():
        if "/issues/" in line:
            issue_num = line.rstrip("/").split("/")[-1]
            print(f"ISSUE_NUMBER={issue_num}")
            return

    print("ERROR=could_not_parse_issue_number")
    sys.exit(1)


def update_scope(repo: str, epic: str | None, body_file: str | None) -> None:
    """Update epic body."""
    if not epic:
        print("ERROR=missing_epic_number")
        sys.exit(1)

    if not body_file:
        print("ERROR=missing_body_file")
        sys.exit(1)

    body_path = Path(body_file)
    if not body_path.is_file():
        print(f"ERROR=body_file_not_found path={body_file}")
        sys.exit(1)

    with body_path.open() as f:
        body = f.read()

    args = [
        "issue", "edit", epic,
        "--repo", repo,
        "--body", body,
    ]
    exit_code, stdout, stderr = run_gh(args)

    if exit_code != 0:
        print(f"ERROR=gh_failed stderr={stderr.strip()}")
        sys.exit(1)

    print("UPDATED=yes")


def parse_args() -> dict[str, str]:
    """Parse command-line arguments into a dict."""
    parsed = {}
    for arg in sys.argv[1:]:
        if "=" in arg:
            key, val = arg.split("=", 1)
            parsed[key] = val
        else:
            # Positional args (subcommand, repo, project)
            if "subcommand" not in parsed:
                parsed["subcommand"] = arg
            elif "target" not in parsed:
                parsed["target"] = arg
    return parsed


def main() -> None:
    """Main entry point."""
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    args = parse_args()
    subcommand = args.get("subcommand")

    if subcommand == "create-labels":
        repo = args.get("target")
        if not repo:
            print("ERROR=missing_repo")
            sys.exit(1)
        create_labels(repo)

    elif subcommand == "install-hooks":
        project = args.get("target")
        if not project:
            print("ERROR=missing_project_path")
            sys.exit(1)
        install_hooks(project)

    elif subcommand == "create-epic":
        repo = args.get("target")
        if not repo:
            print("ERROR=missing_repo")
            sys.exit(1)
        title = args.get("title")
        body_file = args.get("body-file")
        create_epic(repo, title, body_file)

    elif subcommand == "create-issue":
        repo = args.get("target")
        if not repo:
            print("ERROR=missing_repo")
            sys.exit(1)
        title = args.get("title")
        body_file = args.get("body-file")
        labels = args.get("labels")
        create_issue(repo, title, body_file, labels)

    elif subcommand == "update-scope":
        repo = args.get("target")
        if not repo:
            print("ERROR=missing_repo")
            sys.exit(1)
        epic = args.get("epic")
        body_file = args.get("body-file")
        update_scope(repo, epic, body_file)

    else:
        print(f"ERROR=unknown_subcommand subcommand={subcommand}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
