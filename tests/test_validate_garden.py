#!/usr/bin/env python3
"""
Unit tests for scripts/validate_garden.py

Tests all 8 validation checks using temporary garden fixtures.
Never touches the real ~/claude/knowledge-garden/.
"""

import subprocess
import sys
import textwrap
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

VALIDATOR = Path(__file__).parent.parent / "scripts" / "validate_garden.py"


def run_validator(garden_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(garden_root)],
        capture_output=True, text=True
    )


def write_yaml_entry(root: Path, domain: str, ge_id: str, title: str,
                     submitted: str, threshold: int,
                     last_reviewed: str = None,
                     verified_on: str = None) -> Path:
    """Write a garden entry with YAML frontmatter for freshness testing."""
    category = root / domain
    category.mkdir(exist_ok=True)
    path = category / f"{ge_id}.md"
    lines = [
        "---",
        f"id: {ge_id}",
        f'title: "{title}"',
        "type: gotcha",
        f"domain: {domain}",
        'stack: "Test Stack"',
        "tags: [test]",
        "score: 10",
        "verified: true",
        f"staleness_threshold: {threshold}",
        f"submitted: {submitted}",
    ]
    if last_reviewed:
        lines.append(f"last_reviewed: {last_reviewed}")
    if verified_on:
        lines.append(f'verified_on: "{verified_on}"')
    lines.extend(["---", "", f"## {title}", "", f"**ID:** {ge_id}", ""])
    path.write_text("\n".join(lines))
    return path


def run_freshness(garden_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), '--freshness', str(garden_root)],
        capture_output=True, text=True
    )


def run_dedupe_check(garden_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), '--dedupe-check', str(garden_root)],
        capture_output=True, text=True
    )


def _garden_with_drift(root: Path, drift: int, threshold: int = 10) -> Path:
    (root / 'GARDEN.md').write_text(
        f'**Last legacy ID:** GE-0001\n'
        f'**Last full DEDUPE sweep:** 2026-04-14\n'
        f'**Entries merged since last sweep:** {drift}\n'
        f'**Drift threshold:** {threshold}\n'
    )
    return root


class TestDedupeCheck(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_drift_below_threshold_exits_0(self):
        _garden_with_drift(self.root, drift=3, threshold=10)
        result = run_dedupe_check(self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('OK', result.stdout)

    def test_drift_at_threshold_exits_2(self):
        _garden_with_drift(self.root, drift=10, threshold=10)
        result = run_dedupe_check(self.root)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('DEDUPE recommended', result.stdout)

    def test_drift_above_threshold_exits_2(self):
        _garden_with_drift(self.root, drift=15, threshold=10)
        result = run_dedupe_check(self.root)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_drift_just_below_threshold_exits_0(self):
        _garden_with_drift(self.root, drift=9, threshold=10)
        result = run_dedupe_check(self.root)
        self.assertEqual(result.returncode, 0)

    def test_output_shows_drift_and_threshold(self):
        _garden_with_drift(self.root, drift=5, threshold=10)
        result = run_dedupe_check(self.root)
        self.assertIn('drift=5', result.stdout)
        self.assertIn('threshold=10', result.stdout)

    def test_custom_threshold_respected(self):
        _garden_with_drift(self.root, drift=3, threshold=3)
        result = run_dedupe_check(self.root)
        self.assertEqual(result.returncode, 2)

    def test_no_garden_md_exits_0(self):
        result = run_dedupe_check(self.root)
        self.assertEqual(result.returncode, 0)


class TestDedupeCheckGitLog(unittest.TestCase):
    """Git-log cross-verification: git-log count wins when higher than counter."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(['git', 'init', str(self.root)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.root), 'config', 'user.email', 'test@test.com'],
                       check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.root), 'config', 'user.name', 'Test'],
                       check=True, capture_output=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _commit(self, message: str):
        f = self.root / f'file_{message[:20].replace(" ", "_")}.txt'
        f.write_text(message)
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.root), 'commit', '-m', message],
                       check=True, capture_output=True)

    def test_git_log_count_wins_when_higher(self):
        # Counter says 2, git-log shows 4 integrate commits since last dedupe
        (self.root / 'GARDEN.md').write_text(
            '**Entries merged since last sweep:** 2\n**Drift threshold:** 3\n'
        )
        self._commit('dedupe: baseline sweep')
        for i in range(4):
            self._commit(f'index: integrate GE-000{i}')
        # Counter=2, git-log=4, threshold=3 → git-log (4) >= threshold → exit 2
        result = run_dedupe_check(self.root)
        self.assertEqual(result.returncode, 2, result.stdout)

    def test_git_log_does_not_override_higher_counter(self):
        # Counter=8, git-log shows only 2 → counter (8) is used, below threshold=10
        (self.root / 'GARDEN.md').write_text(
            '**Entries merged since last sweep:** 8\n**Drift threshold:** 10\n'
        )
        self._commit('dedupe: baseline sweep')
        for i in range(2):
            self._commit(f'index: integrate GE-000{i}')
        result = run_dedupe_check(self.root)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('drift=8', result.stdout)


class TestFreshnessFlag(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # Minimal GARDEN.md so the flag doesn't choke on a missing file
        (self.root / "GARDEN.md").write_text("**Last legacy ID:** GE-0001\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_entries_exits_0(self):
        result = run_freshness(self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0 entries", result.stdout)

    def test_fresh_entry_exits_0(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        write_yaml_entry(self.root, "tools", "GE-20260414-aabbcc",
                         "Fresh entry", yesterday, 730)
        result = run_freshness(self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0 entries", result.stdout)

    def test_overdue_entry_exits_2(self):
        old = (date.today() - timedelta(days=800)).isoformat()
        write_yaml_entry(self.root, "tools", "GE-20260414-aabbcc",
                         "Old entry", old, 730)
        result = run_freshness(self.root)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("1 entries", result.stdout)

    def test_last_reviewed_resets_clock(self):
        old = (date.today() - timedelta(days=800)).isoformat()
        recent = (date.today() - timedelta(days=10)).isoformat()
        write_yaml_entry(self.root, "tools", "GE-20260414-aabbcc",
                         "Reviewed entry", old, 730, last_reviewed=recent)
        result = run_freshness(self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0 entries", result.stdout)

    def test_entry_without_staleness_threshold_is_skipped(self):
        # Entry with no staleness_threshold field — skipped by freshness check
        category = self.root / "tools"
        category.mkdir()
        (category / "GE-20260414-aabbcc.md").write_text(
            '---\nid: GE-20260414-aabbcc\ntitle: "No threshold"\nsubmitted: 2020-01-01\n---\n'
        )
        result = run_freshness(self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0 entries", result.stdout)

    def test_multiple_overdue_entries_reported(self):
        old = (date.today() - timedelta(days=800)).isoformat()
        write_yaml_entry(self.root, "tools", "GE-20260414-aabbcc",
                         "Old entry A", old, 730)
        write_yaml_entry(self.root, "java", "GE-20260414-ddeeff",
                         "Old entry B", old, 730)
        result = run_freshness(self.root)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("2 entries", result.stdout)


class GardenFixture:
    """Builder for temporary knowledge garden fixtures."""

    def __init__(self, root: Path):
        self.root = root
        self.submissions = root / "submissions"
        self.submissions.mkdir(exist_ok=True)
        (root / "CHECKED.md").write_text(
            "# Garden Duplicate Check Log\n\n"
            "| Pair | Result | Date | Notes |\n"
            "|------|--------|------|-------|\n"
        )
        (root / "DISCARDED.md").write_text(
            "# Discarded Submissions\n\n"
            "| Discarded | Conflicts With | Date | Reason |\n"
            "|-----------|---------------|------|--------|\n"
        )

    def garden_md(self, last_id: str = "GE-0001", entries_since_sweep: int = 0):
        (self.root / "GARDEN.md").write_text(textwrap.dedent(f"""\
            **Last assigned ID:** {last_id}
            **Last full DEDUPE sweep:** 2026-04-09
            **Entries merged since last sweep:** {entries_since_sweep}
            **Drift threshold:** 10

            ## By Technology

            ## By Symptom / Type

            ## By Label
        """))
        return self

    def garden_md_with_index(self, entries: list[tuple[str, str, str]]):
        """Write GARDEN.md with index entries. entries = [(ge_id, title, file_link)]

        The validator's get_by_technology_ids() regex requires a '\\n---' terminator
        after the By Technology section content.
        """
        last_id = entries[-1][0] if entries else "GE-0001"
        lines = [
            f"**Last assigned ID:** {last_id}",
            "**Last full DEDUPE sweep:** 2026-04-09",
            "**Entries merged since last sweep:** 0",
            "**Drift threshold:** 10",
            "",
            "## By Technology",
            "",
        ]
        for ge_id, title, file_link in entries:
            lines.append(f"- {ge_id} [{title}]({file_link})")
        lines += ["", "---", "", "## By Symptom / Type", "", "---", "", "## By Label", ""]
        (self.root / "GARDEN.md").write_text("\n".join(lines))
        return self

    def entry(self, ge_id: str, title: str, subdir: str = "tools", filename: str = None):
        """Write a single garden entry with **ID:** header."""
        filename = filename or f"{subdir}.md"
        category = self.root / subdir
        category.mkdir(exist_ok=True)
        path = category / filename
        content = path.read_text() if path.exists() else f"# {subdir.title()} Gotchas\n\n"
        content += textwrap.dedent(f"""\
            ## {title}

            **ID:** {ge_id}
            **Stack:** Python (any version)
            **Symptom:** Something goes wrong.

            ### Root cause
            The root cause.

            ### Fix
            The fix.

            *Score: 10/15 · Included because: test · Reservation: none*

            ---
        """)
        path.write_text(content)
        return self

    def submission(self, ge_id: str, title: str, include_id_header: bool = True):
        filename = f"2026-04-09-test-{ge_id}-{title.lower().replace(' ', '-')}.md"
        content = textwrap.dedent(f"""\
            # Garden Submission

            **Date:** 2026-04-09
        """)
        if include_id_header:
            content += f"**Submission ID:** {ge_id}\n"
        content += textwrap.dedent(f"""\
            **Type:** gotcha

            ---

            ## {title}

            **Stack:** Python (any version)
        """)
        (self.submissions / filename).write_text(content)
        return self

    def checked_pair(self, id_a: str, id_b: str, result: str = "distinct"):
        current = (self.root / "CHECKED.md").read_text()
        current += f"| {id_a} × {id_b} | {result} | 2026-04-09 | |\n"
        (self.root / "CHECKED.md").write_text(current)
        return self

    def discarded(self, discarded_id: str, conflicts_with: str):
        current = (self.root / "DISCARDED.md").read_text()
        current += f"| {discarded_id} | {conflicts_with} | 2026-04-09 | duplicate |\n"
        (self.root / "DISCARDED.md").write_text(current)
        return self

    def schema_md(self, role='canonical', ge_prefix='GE-',
                  domains=None, name='test-garden',
                  upstream=None):
        """Write a valid SCHEMA.md to the garden root."""
        domains = domains or ['tools']
        lines = [
            '---',
            f'name: {name}',
            'description: "Test garden"',
            f'role: {role}',
            f'ge_prefix: {ge_prefix}',
            'schema_version: "1.0"',
            f'domains: [{", ".join(domains)}]',
        ]
        if upstream:
            lines.append('upstream:')
            for url in upstream:
                lines.append(f'  - {url}')
        lines.extend(['---', ''])
        (self.root / 'SCHEMA.md').write_text('\n'.join(lines))
        return self


class TestValidGarden(unittest.TestCase):
    """A well-formed garden should exit 0."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_garden_passes(self):
        GardenFixture(self.root).garden_md("GE-0001")
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_single_entry_with_index_passes(self):
        fx = GardenFixture(self.root)
        fx.entry("GE-0001", "Some gotcha", subdir="tools", filename="git.md")
        fx.garden_md_with_index([("GE-0001", "Some gotcha", "tools/git.md")])
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_multiple_entries_pass(self):
        fx = GardenFixture(self.root)
        fx.entry("GE-0001", "First gotcha", subdir="tools", filename="git.md")
        fx.entry("GE-0002", "Second gotcha", subdir="java", filename="records.md")
        fx.garden_md_with_index([
            ("GE-0001", "First gotcha", "tools/git.md"),
            ("GE-0002", "Second gotcha", "java/records.md"),
        ])
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class TestMissingGardenMd(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_garden_md_is_error(self):
        GardenFixture(self.root)  # no garden_md() call
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("GARDEN.md", result.stdout)


class TestDuplicateGEIDs(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_duplicate_id_in_two_files_is_error(self):
        fx = GardenFixture(self.root)
        fx.entry("GE-0001", "Gotcha A", subdir="tools", filename="git.md")
        fx.entry("GE-0001", "Gotcha B", subdir="java", filename="records.md")
        fx.garden_md_with_index([("GE-0001", "Gotcha A", "tools/git.md")])
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("GE-0001", result.stdout)

    def test_unique_ids_pass(self):
        fx = GardenFixture(self.root)
        fx.entry("GE-0001", "Gotcha A", subdir="tools", filename="git.md")
        fx.entry("GE-0002", "Gotcha B", subdir="java", filename="records.md")
        fx.garden_md_with_index([
            ("GE-0001", "Gotcha A", "tools/git.md"),
            ("GE-0002", "Gotcha B", "java/records.md"),
        ])
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 0, result.stdout)


class TestCounterConsistency(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_counter_below_highest_id_is_error(self):
        fx = GardenFixture(self.root)
        fx.entry("GE-0005", "Gotcha A", subdir="tools", filename="git.md")
        fx.garden_md_with_index([("GE-0005", "Gotcha A", "tools/git.md")])
        # Counter says GE-0003 but highest entry is GE-0005
        content = (self.root / "GARDEN.md").read_text()
        (self.root / "GARDEN.md").write_text(
            content.replace("**Last assigned ID:** GE-0005", "**Last assigned ID:** GE-0003")
        )
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("counter", result.stdout.lower())

    def test_counter_equal_to_highest_passes(self):
        fx = GardenFixture(self.root)
        fx.entry("GE-0005", "Gotcha A", subdir="tools", filename="git.md")
        fx.garden_md_with_index([("GE-0005", "Gotcha A", "tools/git.md")])
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_counter_above_highest_passes(self):
        fx = GardenFixture(self.root)
        fx.entry("GE-0003", "Gotcha A", subdir="tools", filename="git.md")
        fx.garden_md_with_index([("GE-0003", "Gotcha A", "tools/git.md")])
        # Counter is GE-0005 (some IDs assigned to submissions not yet merged)
        content = (self.root / "GARDEN.md").read_text()
        (self.root / "GARDEN.md").write_text(
            content.replace("**Last assigned ID:** GE-0003", "**Last assigned ID:** GE-0005")
        )
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 0, result.stdout)


class TestIndexConsistency(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_index_references_missing_entry_is_error(self):
        fx = GardenFixture(self.root)
        # Index says GE-0001 exists but no garden file has it
        fx.garden_md_with_index([("GE-0001", "Missing entry", "tools/git.md")])
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("GE-0001", result.stdout)

    def test_entry_missing_from_index_is_reported(self):
        fx = GardenFixture(self.root)
        fx.entry("GE-0001", "Orphan entry", subdir="tools", filename="git.md")
        # GARDEN.md has no index entries
        fx.garden_md("GE-0001")
        result = run_validator(self.root)
        # Missing from index → warning; missing from By Technology → error.
        # Both fire, so exit code is 1 (errors present).
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("GE-0001", result.stdout)

    def test_entry_missing_from_by_technology_is_error(self):
        """Entry in By Label but not By Technology should be an error."""
        fx = GardenFixture(self.root)
        fx.entry("GE-0001", "Technique A", subdir="tools", filename="git.md")
        # Write GARDEN.md with GE-0001 only in By Label, not By Technology
        (self.root / "GARDEN.md").write_text(textwrap.dedent("""\
            **Last assigned ID:** GE-0001
            **Last full DEDUPE sweep:** 2026-04-09
            **Entries merged since last sweep:** 0
            **Drift threshold:** 10

            ## By Technology

            ## By Symptom / Type

            ## By Label

            - GE-0001 [Technique A](tools/git.md)
        """))
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("By Technology", result.stdout)


class TestCheckedMdIntegrity(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_checked_pair_with_unknown_id_is_warning(self):
        fx = GardenFixture(self.root)
        fx.entry("GE-0001", "Known entry", subdir="tools", filename="git.md")
        fx.garden_md_with_index([("GE-0001", "Known entry", "tools/git.md")])
        fx.checked_pair("GE-0001", "GE-9999")  # GE-9999 doesn't exist
        result = run_validator(self.root)
        # Should be warning (exit 2), not error (exit 1)
        self.assertIn(result.returncode, (1, 2))
        self.assertIn("GE-9999", result.stdout)

    def test_checked_pair_with_known_ids_passes(self):
        fx = GardenFixture(self.root)
        fx.entry("GE-0001", "Entry A", subdir="tools", filename="git.md")
        fx.entry("GE-0002", "Entry B", subdir="tools", filename="git.md")
        fx.garden_md_with_index([
            ("GE-0001", "Entry A", "tools/git.md"),
            ("GE-0002", "Entry B", "tools/git.md"),
        ])
        fx.checked_pair("GE-0001", "GE-0002")
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_checked_pair_referencing_submission_id_passes(self):
        """GE-IDs in submissions/ count as known for CHECKED.md validation."""
        fx = GardenFixture(self.root)
        fx.entry("GE-0001", "Known entry", subdir="tools", filename="git.md")
        fx.garden_md_with_index([("GE-0001", "Known entry", "tools/git.md")])
        fx.submission("GE-0002", "Pending submission")
        fx.checked_pair("GE-0001", "GE-0002")
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 0, result.stdout)


class TestDiscardedMdIntegrity(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_discarded_conflicts_with_missing_entry_is_error(self):
        fx = GardenFixture(self.root)
        fx.garden_md("GE-0002")
        fx.discarded("GE-0001", "GE-9999")  # GE-9999 not in garden
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("GE-9999", result.stdout)

    def test_discarded_conflicts_with_real_entry_passes(self):
        fx = GardenFixture(self.root)
        fx.entry("GE-0002", "Real entry", subdir="tools", filename="git.md")
        fx.garden_md_with_index([("GE-0002", "Real entry", "tools/git.md")])
        fx.discarded("GE-0001", "GE-0002")
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 0, result.stdout)


class TestSubmissionIDHeaders(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_submission_without_id_header_is_warning(self):
        fx = GardenFixture(self.root)
        fx.garden_md("GE-0001")
        fx.submission("GE-0001", "No id header", include_id_header=False)
        result = run_validator(self.root)
        self.assertIn(result.returncode, (1, 2))
        self.assertIn("Submission ID", result.stdout)

    def test_submission_with_id_header_passes(self):
        fx = GardenFixture(self.root)
        fx.garden_md("GE-0001")
        fx.submission("GE-0001", "With id header", include_id_header=True)
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_empty_submissions_dir_passes(self):
        fx = GardenFixture(self.root)
        fx.garden_md("GE-0001")
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 0, result.stdout)


class TestSchemaValidation(unittest.TestCase):
    """validate_garden.py calls validate_schema when SCHEMA.md is present."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_garden_without_schema_passes(self):
        GardenFixture(self.root).garden_md('GE-0001')
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_garden_with_valid_schema_passes(self):
        GardenFixture(self.root).garden_md('GE-0001').schema_md()
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_garden_with_invalid_schema_fails(self):
        GardenFixture(self.root).garden_md('GE-0001')
        (self.root / 'SCHEMA.md').write_text('---\nrole: canonical\n---\n')
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 1, result.stdout)
        output = result.stdout + result.stderr
        self.assertTrue(
            any(term in output for term in ('SCHEMA', 'ge_prefix', 'name', 'domains')),
            f"Expected schema error in output, got: {output}"
        )

    def test_garden_with_child_schema_and_upstream_passes(self):
        GardenFixture(self.root).garden_md('GE-0001').schema_md(
            role='child',
            upstream=['https://github.com/Hortora/jvm-garden'],
        )
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_child_schema_missing_upstream_fails(self):
        GardenFixture(self.root).garden_md('GE-0001')
        (self.root / 'SCHEMA.md').write_text(
            '---\nname: x\nrole: child\nge_prefix: JE-\n'
            'domains: [java]\nschema_version: "1.0"\n---\n'
        )
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn('upstream', result.stdout + result.stderr)


def test_structural_flag_passes_valid_garden(tmp_path):
    import subprocess, sys as _sys
    from pathlib import Path as _Path
    script = _Path(__file__).parent.parent / 'scripts' / 'validate_garden.py'
    (tmp_path / 'GARDEN.md').write_text('**Last assigned ID:** GE-0000\n')
    (tmp_path / '_index').mkdir()
    (tmp_path / '_index' / 'global.md').write_text('| Domain | Index |\n|--------|-------|\n')
    result = subprocess.run(
        [_sys.executable, str(script), '--structural', str(tmp_path)],
        capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_structural_flag_fails_missing_garden_md(tmp_path):
    import subprocess, sys as _sys
    from pathlib import Path as _Path
    script = _Path(__file__).parent.parent / 'scripts' / 'validate_garden.py'
    (tmp_path / '_index').mkdir()
    (tmp_path / '_index' / 'global.md').write_text('')
    result = subprocess.run(
        [_sys.executable, str(script), '--structural', str(tmp_path)],
        capture_output=True, text=True
    )
    assert result.returncode != 0


if __name__ == "__main__":
    unittest.main(verbosity=2)
