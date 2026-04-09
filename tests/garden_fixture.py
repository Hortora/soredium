"""
Shared helpers for building git-backed knowledge garden fixtures.

Creates a real git repository with realistic garden entries so tests
can exercise the actual git operations (git show HEAD:, git ls-tree,
commit conflict, rebase) rather than just file I/O.
"""

import subprocess
import textwrap
from pathlib import Path


def git(garden: Path, *args, check=True) -> subprocess.CompletedProcess:
    """Run a git command in the garden repo."""
    return subprocess.run(
        ["git", "-C", str(garden), *args],
        capture_output=True, text=True, check=check
    )


def git_out(garden: Path, *args) -> str:
    """Run a git command and return stripped stdout."""
    return git(garden, *args).stdout.strip()


class GitGarden:
    """
    A temporary git-backed knowledge garden.

    Provides helpers that mirror the commands forage and harvest use:
      - read_head(path)       → git show HEAD:<path>
      - list_submissions()    → git ls-tree --name-only HEAD submissions/
      - commit(msg, *paths)   → git add + git commit
      - rebase()              → git rebase HEAD (conflict recovery)

    Fixtures are based on the real knowledge-garden structure and the
    entries processed in the Hortora session (GE-0105 through GE-0124).
    """

    def __init__(self, root: Path):
        self.root = root
        self.submissions = root / "submissions"
        self.submissions.mkdir(parents=True, exist_ok=True)

        # Initialise git repo with a test identity
        git(root, "init")
        git(root, "config", "user.email", "test@hortora.test")
        git(root, "config", "user.name", "Test Hortora")

    # ------------------------------------------------------------------
    # Core git operations (mirrors the skill commands)
    # ------------------------------------------------------------------

    def read_head(self, path: str) -> str:
        """git show HEAD:<path> — reads committed state only."""
        return git_out(self.root, "show", f"HEAD:{path}")

    def list_submissions(self) -> list[str]:
        """git ls-tree --name-only HEAD submissions/ — committed files only."""
        result = git(self.root, "ls-tree", "--name-only", "HEAD", "submissions/", check=False)
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.strip().splitlines() if line]

    def commit(self, message: str, *paths: str) -> bool:
        """Stage paths and commit. Returns True on success, False on conflict."""
        for path in paths:
            git(self.root, "add", path)
        result = git(self.root, "commit", "-m", message, check=False)
        return result.returncode == 0

    def commit_all(self, message: str) -> bool:
        """Stage all changes and commit."""
        git(self.root, "add", ".")
        result = git(self.root, "commit", "-m", message, check=False)
        return result.returncode == 0

    def rebase(self) -> bool:
        """git rebase HEAD — conflict recovery after a rejected commit."""
        result = git(self.root, "rebase", "HEAD", check=False)
        return result.returncode == 0

    def current_counter(self) -> int:
        """Read GE-ID counter from committed GARDEN.md (as forage does)."""
        import re
        content = self.read_head("GARDEN.md")
        m = re.search(r"\*\*Last assigned ID:\*\*\s*GE-(\d{4})", content)
        return int(m.group(1)) if m else 0

    def head_sha(self) -> str:
        return git_out(self.root, "rev-parse", "HEAD")

    # ------------------------------------------------------------------
    # Fixture builders
    # ------------------------------------------------------------------

    def init_garden(self, last_id: str = "GE-0100") -> "GitGarden":
        """Write a minimal GARDEN.md + support files and make the initial commit."""
        (self.root / "GARDEN.md").write_text(textwrap.dedent(f"""\
            **Last assigned ID:** {last_id}
            **Last full DEDUPE sweep:** 2026-04-09
            **Entries merged since last sweep:** 0
            **Drift threshold:** 10

            ## By Technology

            ---

            ## By Symptom / Type

            ---

            ## By Label

        """))
        (self.root / "CHECKED.md").write_text(
            "# Garden Duplicate Check Log\n\n"
            "| Pair | Result | Date | Notes |\n"
            "|------|--------|------|-------|\n"
        )
        (self.root / "DISCARDED.md").write_text(
            "# Discarded Submissions\n\n"
            "| Discarded | Conflicts With | Date | Reason |\n"
            "|-----------|---------------|------|--------|\n"
        )
        self.commit_all("init: seed knowledge garden")
        return self

    def add_entry(self, ge_id: str, title: str, subdir: str,
                  filename: str, entry_type: str = "gotcha",
                  labels: str = "") -> "GitGarden":
        """Add a realistic garden entry and update the index, then commit."""
        category = self.root / subdir
        category.mkdir(exist_ok=True)
        path = category / filename

        # Append entry to file (create with header if new)
        if not path.exists():
            path.write_text(f"# {subdir.replace('-', ' ').title()} Gotchas and Techniques\n\n")

        entry = self._make_entry(ge_id, title, entry_type, labels)
        with open(path, "a") as f:
            f.write(entry)

        # Update GARDEN.md index
        self._add_to_index(ge_id, title, f"{subdir}/{filename}", entry_type, labels)

        self.commit_all(f"merge: add {ge_id} — {title[:40]}")
        return self

    def _make_entry(self, ge_id: str, title: str,
                    entry_type: str, labels: str) -> str:
        if entry_type == "technique":
            return textwrap.dedent(f"""\
                ## {title}

                **ID:** {ge_id}
                **Stack:** Python (any version), git
                **Labels:** {labels or "#pattern"}
                **What it achieves:** Demonstrates the pattern.
                **Context:** Any session using this approach.

                ### The technique

                ```bash
                # example command
                git show HEAD:path/to/file.md
                ```

                ### Why this is non-obvious
                Most developers would read from the filesystem directly.

                *Score: 11/15 · Included because: test fixture · Reservation: none*

                ---
            """)
        else:
            return textwrap.dedent(f"""\
                ## {title}

                **ID:** {ge_id}
                **Stack:** Python (any version)
                **Symptom:** Something goes wrong with no obvious error.
                **Context:** Any session hitting this issue.

                ### What was tried (didn't work)
                - Tried the obvious approach — failed

                ### Root cause
                The underlying mechanism explains the failure.

                ### Fix

                ```bash
                # the fix
                git -C ~/garden show HEAD:GARDEN.md
                ```

                ### Why this is non-obvious
                The symptom misleads about the root cause.

                *Score: 10/15 · Included because: test fixture · Reservation: none*

                ---
            """)

    def _add_to_index(self, ge_id: str, title: str, file_link: str,
                      entry_type: str, labels: str) -> None:
        content = (self.root / "GARDEN.md").read_text()
        entry_line = f"- {ge_id} [{title}]({file_link})"

        # Add to By Technology
        content = content.replace(
            "## By Technology\n\n---",
            f"## By Technology\n\n{entry_line}\n\n---"
        )

        if entry_type == "gotcha":
            content = content.replace(
                "## By Symptom / Type\n\n---",
                f"## By Symptom / Type\n\n{entry_line}\n\n---"
            )
        elif entry_type == "technique" and labels:
            for label in labels.split():
                content = content.replace(
                    "## By Label\n\n",
                    f"## By Label\n\n### {label}\n{entry_line}\n\n"
                )

        (self.root / "GARDEN.md").write_text(content)

    def add_submission(self, ge_id: str, title: str, project: str,
                       sub_type: str = "gotcha", labels: str = "",
                       target_id: str = "", revise: bool = False,
                       include_id_header: bool = True) -> str:
        """Write a submission file (NOT yet committed — caller commits)."""
        date = "2026-04-09"
        slug = title.lower().replace(" ", "-").replace("(", "").replace(")", "")[:40]
        if revise:
            filename = f"{date}-{project}-{ge_id}-revise-{slug}.md"
        else:
            filename = f"{date}-{project}-{ge_id}-{slug}.md"

        content = "# Garden Submission\n\n"
        content += f"**Date:** {date}\n"
        if include_id_header:
            content += f"**Submission ID:** {ge_id}\n"
        content += f"**Type:** {sub_type}\n"
        if revise:
            content += f"**Revision kind:** solution\n"
            content += f"**Target ID:** {target_id}\n"
        content += f"**Source project:** {project}\n"
        if sub_type == "technique":
            content += f"**Labels:** {labels or '#pattern'}\n"
        content += textwrap.dedent(f"""\
            **Suggested target:** tools/git.md

            ---

            ## {title}

            **Stack:** Python (any version)
        """)
        if sub_type == "gotcha":
            content += "**Symptom:** Something goes wrong.\n"
        elif sub_type == "technique":
            content += "**What it achieves:** Achieves the goal.\n"

        if revise:
            content += f"\n## What this adds\nThis solution fixes the problem in {target_id}.\n"
            content += "\n## Content\n```bash\n# the fix\n```\n"

        content += textwrap.dedent("""\

            ---

            ## Garden Score

            | Dimension | Score (1–3) |
            |-----------|-------------|
            | Non-obviousness | 3 |
            | Discoverability | 3 |
            | Breadth | 2 |
            | Pain / Impact | 2 |
            | Longevity | 2 |
            | **Total** | **12/15** |

            **Case for inclusion:** Test fixture.
            **Case against inclusion:** None identified.
        """)

        path = self.submissions / filename
        path.write_text(content)
        return filename

    def increment_counter(self, new_id: str) -> None:
        """Update the GARDEN.md counter in the working tree."""
        import re
        content = (self.root / "GARDEN.md").read_text()
        content = re.sub(
            r"\*\*Last assigned ID:\*\*\s*GE-\d{4}",
            f"**Last assigned ID:** {new_id}",
            content
        )
        (self.root / "GARDEN.md").write_text(content)
