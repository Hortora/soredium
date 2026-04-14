#!/usr/bin/env python3
"""
Integration tests for the full CAPTURE → MERGE → validate cycle.

Uses realistic garden fixtures based on real knowledge-garden data
(entries from the Hortora session: GE-0105 through GE-0124) to exercise
end-to-end workflows: submitting entries, merging them, detecting
duplicates, processing revisions, and running the validator.

All tests use temporary git repos — the real garden is never touched.
"""

import re
import subprocess
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.garden_fixture import GitGarden, git, git_out

VALIDATOR = Path(__file__).parent.parent / "scripts" / "validate_garden.py"


def run_validator(garden_root: Path) -> subprocess.CompletedProcess:
    import sys
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(garden_root)],
        capture_output=True, text=True
    )


# ---------------------------------------------------------------------------
# Realistic garden content based on real entries from the Hortora session
# ---------------------------------------------------------------------------

GIT_GOTCHA_ENTRY = textwrap.dedent("""\
    ## `git restore --staged .` Also Reverts Working Tree Changes

    **ID:** GE-0118
    **Stack:** Git (all versions)
    **Symptom:** Running `git restore --staged .` to unstage files also reverts
    uncommitted working tree modifications. Modified files are silently reverted
    to their last committed state.
    **Context:** Mix of staged moves and unstaged working tree modifications.

    ### What was tried (didn't work)
    - `git restore --staged .` — reverted working tree changes unexpectedly

    ### Root cause
    `git restore --staged .` with a path spec restores both the index and the
    working tree for files with both staged and unstaged changes.

    ### Fix

    ```bash
    # Unstage specific files only (safer)
    git restore --staged path/to/specific/file.java

    # Or reset index for specific files
    git reset HEAD path/to/file.java
    ```

    ### Why this is non-obvious
    `--staged` implies index-only. The working tree revert is a surprise when
    using `.` as the path spec.

    *Score: 10/15 · Included because: --staged strongly implies index-only · Reservation: documented*

    ---
""")

MAVEN_GOTCHA_ENTRY = textwrap.dedent("""\
    ## `maven-compiler-plugin` `<excludes>` Doesn't Prevent Transitive Compilation

    **ID:** GE-0115
    **Stack:** Maven, maven-compiler-plugin 3.13.0, Java
    **Symptom:** Files listed in `<excludes>` still appear in compilation errors.
    Maven debug output shows the file in the excludes list yet javac still compiles it.
    **Context:** Trying to exclude WIP infrastructure files from compilation.

    ### What was tried (didn't work)
    - Added files individually by path — didn't work
    - Added entire directories with `**` glob — didn't work

    ### Root cause
    `<excludes>` only affects the initial source file list. Javac's own dependency
    resolution still pulls in excluded files if included files import them.

    ### Fix
    Move files out of the source root or remove all references first:

    ```xml
    <!-- This does NOT work when included files reference the excluded file -->
    <excludes>
      <exclude>org/example/WipClass.java</exclude>
    </excludes>
    ```

    ### Why this is non-obvious
    Debug output explicitly confirms the exclude is configured. No warning is
    emitted when the excluded file is compiled anyway.

    *Score: 13/15 · Included because: debug output actively misleads · Reservation: none*

    ---
""")

INTELLIJ_GOTCHA_ENTRY = textwrap.dedent("""\
    ## `localInspection` in plugin.xml Requires `implementationClass` and Explicit `shortName`

    **ID:** GE-0110
    **Stack:** IntelliJ Platform (any version), `plugin.xml` registration
    **Symptom:** Plugin starts but inspection never fires. No error thrown.
    **Context:** Any `<localInspection>` registration in `plugin.xml`.

    ### Root cause
    Three separate issues: wrong attribute name (`implementation` vs
    `implementationClass`), missing `shortName` crashes the IDE, and class-based
    test fixture registration requires plugin.xml visibility.

    ### Fix

    ```xml
    <localInspection
        language="JAVA"
        shortName="MyInspectionShortName"
        displayName="My inspection description"
        implementationClass="com.example.MyInspection"/>
    ```

    ### Why this is non-obvious
    All three produce either silent no-op or unrelated-looking exceptions.

    *Score: 13/15 · Included because: three distinct silent failures · Reservation: version-specific*

    ---
""")

DROOLS_TECHNIQUE_ENTRY = textwrap.dedent("""\
    ## Drools as Action Compiler for GOAP — One Session per Tick, Not per A* Node

    **ID:** GE-0105
    **Stack:** Drools Rule Units (drools-ruleunits-api, any version), GOAP, Java
    **Labels:** `#strategy` `#pattern` `#performance`
    **What it achieves:** Integrates Drools with A* without cloning sessions per node.
    **Context:** Any system using a rule engine to define a planning action space.

    ### The technique

    ```java
    // Fire Drools once per tick to produce action library
    RuleUnitInstance<TacticsRuleUnit> instance = ruleUnit.createInstance(data);
    instance.fire();
    List<GoapAction> actions = parseActions(data.getActionDecisions());

    // A* searches using action library — no Drools involvement
    List<GoapAction> plan = planner.plan(group.worldState(), goal, actions);
    ```

    ### Why this is non-obvious
    Developers instinctively call Drools at each A* search node, requiring
    session cloning. Separating Drools (action producer) from A* (action consumer)
    is the key insight.

    ### When to use it
    Any system where a rule engine defines a planning action space.

    *Score: 13/15 · Included because: decoupled boundary is elegant · Reservation: theoretical at submission*

    ---
""")


def build_realistic_garden(garden: GitGarden) -> GitGarden:
    """
    Populate a garden with realistic entries based on real GE-0105 through GE-0124 data.
    Uses a subset for test efficiency.
    """
    # tools/git.md — GE-0118 gotcha
    tools = garden.root / "tools"
    tools.mkdir(exist_ok=True)
    (tools / "git.md").write_text("# git Gotchas and Techniques\n\n" + GIT_GOTCHA_ENTRY)

    # tools/maven.md — GE-0115 gotcha
    (tools / "maven.md").write_text("# Maven Gotchas\n\n" + MAVEN_GOTCHA_ENTRY)

    # intellij-platform/inspections.md — GE-0110 gotcha
    ij = garden.root / "intellij-platform"
    ij.mkdir(exist_ok=True)
    (ij / "inspections.md").write_text(
        "# IntelliJ Platform — Inspection Gotchas\n\n" + INTELLIJ_GOTCHA_ENTRY
    )

    # drools/drools-goap-planning.md — GE-0105 technique
    drools = garden.root / "drools"
    drools.mkdir(exist_ok=True)
    (drools / "drools-goap-planning.md").write_text(
        "# Drools — GOAP and Planning Techniques\n\n" + DROOLS_TECHNIQUE_ENTRY
    )

    # Build GARDEN.md with proper index
    (garden.root / "GARDEN.md").write_text(textwrap.dedent("""\
        **Last assigned ID:** GE-0124
        **Last full DEDUPE sweep:** 2026-04-09
        **Entries merged since last sweep:** 0
        **Drift threshold:** 10

        ## By Technology

        - GE-0105 [Drools as Action Compiler for GOAP](drools/drools-goap-planning.md)
        - GE-0110 [localInspection Requires implementationClass and shortName](intellij-platform/inspections.md)
        - GE-0115 [maven-compiler-plugin excludes Doesn't Prevent Transitive Compilation](tools/maven.md)
        - GE-0118 [git restore --staged Also Reverts Working Tree Changes](tools/git.md)

        ---

        ## By Symptom / Type

        - GE-0110 [localInspection Requires implementationClass and shortName](intellij-platform/inspections.md)
        - GE-0115 [maven-compiler-plugin excludes Doesn't Prevent Transitive Compilation](tools/maven.md)
        - GE-0118 [git restore --staged Also Reverts Working Tree Changes](tools/git.md)

        ---

        ## By Label

        ### #strategy
        - GE-0105 [Drools as Action Compiler for GOAP](drools/drools-goap-planning.md)

        ### #pattern
        - GE-0105 [Drools as Action Compiler for GOAP](drools/drools-goap-planning.md)

        ### #performance
        - GE-0105 [Drools as Action Compiler for GOAP](drools/drools-goap-planning.md)

    """))

    garden.commit_all("init: seed realistic garden (GE-0105, GE-0110, GE-0115, GE-0118)")
    return garden


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRealisticGardenValidates(unittest.TestCase):
    """The realistic fixture should pass the validator out of the box."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = GitGarden(Path(self.tmp.name))
        self.garden.init_garden("GE-0100")
        build_realistic_garden(self.garden)

    def tearDown(self):
        self.tmp.cleanup()

    def test_validator_passes_on_clean_garden(self):
        result = run_validator(self.garden.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_ids_unique(self):
        """No duplicate GE-IDs in the garden files."""
        ids = []
        for f in self.garden.root.rglob("*.md"):
            if any(p in str(f) for p in ["submissions", "GARDEN", "CHECKED", "DISCARDED"]):
                continue
            for m in re.finditer(r"^\*\*ID:\*\*\s+(GE-\d{4})", f.read_text(), re.MULTILINE):
                ids.append(m.group(1))
        self.assertEqual(len(ids), len(set(ids)), f"Duplicate IDs found: {ids}")

    def test_index_references_all_entries(self):
        """Every GE-ID in garden files appears in GARDEN.md index."""
        index_content = self.garden.read_head("GARDEN.md")
        for f in self.garden.root.rglob("*.md"):
            if any(p in str(f) for p in ["submissions", "GARDEN", "CHECKED", "DISCARDED"]):
                continue
            for m in re.finditer(r"^\*\*ID:\*\*\s+(GE-\d{4})", f.read_text(), re.MULTILINE):
                self.assertIn(m.group(1), index_content,
                              f"{m.group(1)} in {f.name} but not in GARDEN.md index")


class TestSingleSubmissionMergeCycle(unittest.TestCase):
    """Full cycle: forage CAPTURE → committed submission → harvest MERGE → validate."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = GitGarden(Path(self.tmp.name))
        self.garden.init_garden("GE-0100")
        build_realistic_garden(self.garden)

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_submission_committed_and_listed(self):
        """A submission written and committed by forage is visible to harvest."""
        # Forage: read counter from HEAD, write submission, commit atomically
        counter = self.garden.current_counter()
        new_id = f"GE-{counter + 1:04d}"

        filename = self.garden.add_submission(
            new_id, "SVG textPath dy unreliable on curves", "cc-praxis",
            sub_type="gotcha"
        )
        self.garden.increment_counter(new_id)
        self.garden.commit(f"submit(cc-praxis): {new_id} 'SVG textPath dy unreliable'",
                           f"submissions/{filename}", "GARDEN.md")

        # Harvest: list submissions via git ls-tree
        submissions = self.garden.list_submissions()
        self.assertEqual(len(submissions), 1)
        self.assertIn(f"submissions/{filename}", submissions)

        # Harvest: read submission content via git show HEAD:
        content = self.garden.read_head(f"submissions/{filename}")
        self.assertIn(new_id, content)
        self.assertIn("SVG textPath", content)
        self.assertIn("**Submission ID:**", content)

    def test_merged_entry_passes_validator(self):
        """After harvest merges a submission, validator still passes."""
        counter = self.garden.current_counter()
        new_id = f"GE-{counter + 1:04d}"

        # Forage submits
        filename = self.garden.add_submission(
            new_id, "SVG textPath dy unreliable on curves", "cc-praxis"
        )
        self.garden.increment_counter(new_id)
        self.garden.commit(f"submit(cc-praxis): {new_id}",
                           f"submissions/{filename}", "GARDEN.md")

        # Harvest merges: write entry to garden file, update index, remove submission
        tools_svg = self.garden.root / "tools" / "svg.md"
        tools_svg.write_text(textwrap.dedent(f"""\
            # SVG Gotchas and Techniques

            ## SVG textPath dy unreliable on curves

            **ID:** {new_id}
            **Stack:** SVG (all browsers)
            **Symptom:** dy attribute on textPath doesn't reliably position text.
            **Context:** Any SVG diagram with circular arc text.

            ### Root cause
            Browser rendering of dy on curved paths is inconsistent.

            ### Fix
            Use inset radius instead of dy attribute.

            ### Why this is non-obvious
            dy works reliably on straight paths but not curved ones.

            *Score: 13/15 · Included because: affects circular diagrams · Reservation: browser-specific*

            ---
        """))

        # Update GARDEN.md index
        garden_md = (self.garden.root / "GARDEN.md").read_text()
        garden_md = garden_md.replace(
            "## By Technology\n\n",
            f"## By Technology\n\n- {new_id} [SVG textPath dy unreliable](tools/svg.md)\n"
        )
        garden_md = re.sub(
            r"Entries merged since last sweep:\*\*\s*\d+",
            "Entries merged since last sweep:** 1",
            garden_md
        )
        (self.garden.root / "GARDEN.md").write_text(garden_md)

        # Remove submission
        git(self.garden.root, "rm", f"submissions/{filename}")

        # Commit
        self.garden.commit_all(f"merge: integrate 1 submission — {new_id} SVG textPath")

        # Validator should pass
        result = run_validator(self.garden.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class TestMultipleSubmissionsFromDifferentProjects(unittest.TestCase):
    """Submissions from permuplate, starcraft, and quarkmind all merge cleanly."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = GitGarden(Path(self.tmp.name))
        self.garden.init_garden("GE-0120")
        build_realistic_garden(self.garden)

    def tearDown(self):
        self.tmp.cleanup()

    def test_three_submissions_from_different_projects(self):
        submissions = []
        entries = [
            ("GE-0121", "mv project folder invalidates Bash tool cwd", "quarkmind", "gotcha"),
            ("GE-0122", "package-private not accessible from sub-packages", "quarkmind", "gotcha"),
            ("GE-0123", "Use Java buffers instead of Drools STREAM mode", "quarkmind", "technique"),
        ]

        for ge_id, title, project, sub_type in entries:
            filename = self.garden.add_submission(ge_id, title, project, sub_type=sub_type)
            self.garden.increment_counter(ge_id)
            self.garden.commit(f"submit({project}): {ge_id} '{title[:30]}'",
                               f"submissions/{filename}", "GARDEN.md")
            submissions.append(filename)

        # All three committed and visible
        listed = self.garden.list_submissions()
        self.assertEqual(len(listed), 3)
        for filename in submissions:
            self.assertIn(f"submissions/{filename}", listed)

    def test_counter_increments_correctly_across_projects(self):
        """Counter advances sequentially regardless of which project submits."""
        for i, (title, project) in enumerate([
            ("First submission", "permuplate"),
            ("Second submission", "starcraft"),
            ("Third submission", "quarkmind"),
        ], start=121):
            ge_id = f"GE-0{i}"
            filename = self.garden.add_submission(ge_id, title, project)
            self.garden.increment_counter(ge_id)
            self.garden.commit(f"submit({project}): {ge_id}",
                               f"submissions/{filename}", "GARDEN.md")

        self.assertEqual(self.garden.current_counter(), 123)


class TestReviseSubmission(unittest.TestCase):
    """Revise submissions are identified by filename and Target ID field."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = GitGarden(Path(self.tmp.name))
        self.garden.init_garden("GE-0124")
        build_realistic_garden(self.garden)

    def tearDown(self):
        self.tmp.cleanup()

    def test_revise_filename_contains_revise(self):
        filename = self.garden.add_submission(
            "GE-0125", "Fix for git restore gotcha", "quarkmind",
            revise=True, target_id="GE-0118"
        )
        self.assertIn("revise", filename)

    def test_revise_submission_has_target_id(self):
        filename = self.garden.add_submission(
            "GE-0125", "Fix for git restore gotcha", "quarkmind",
            revise=True, target_id="GE-0118"
        )
        self.garden.increment_counter("GE-0125")
        self.garden.commit("submit(quarkmind): GE-0125 revise 'git restore' — fix found",
                           f"submissions/{filename}", "GARDEN.md")

        content = self.garden.read_head(f"submissions/{filename}")
        self.assertIn("**Target ID:** GE-0118", content)
        self.assertIn("**Submission ID:** GE-0125", content)

    def test_revise_not_confused_with_new_entry(self):
        """harvest distinguishes revise from new by checking filename for 'revise'."""
        filename_new = self.garden.add_submission("GE-0125", "New gotcha", "proj")
        filename_revise = self.garden.add_submission(
            "GE-0126", "Fix for existing", "proj",
            revise=True, target_id="GE-0118"
        )

        self.assertNotIn("revise", filename_new)
        self.assertIn("revise", filename_revise)


class TestDuplicateDetection(unittest.TestCase):
    """Submissions with same symptom/title as existing entries are flagged by validator."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = GitGarden(Path(self.tmp.name))
        self.garden.init_garden("GE-0124")
        build_realistic_garden(self.garden)

    def tearDown(self):
        self.tmp.cleanup()

    def test_duplicate_id_in_garden_file_fails_validator(self):
        """If harvest accidentally assigns an existing GE-ID, validator catches it."""
        # Simulate harvest erroneously adding a second entry with GE-0118
        tools_git = self.garden.root / "tools" / "git.md"
        current = tools_git.read_text()
        # Append a duplicate entry with the same GE-ID
        duplicate = textwrap.dedent("""\
            ## Some Other Gotcha (accidentally using GE-0118 again)

            **ID:** GE-0118
            **Stack:** Git (all versions)
            **Symptom:** Something else goes wrong.

            *Score: 9/15 · Included because: test · Reservation: none*

            ---
        """)
        tools_git.write_text(current + duplicate)
        self.garden.commit_all("merge: accidentally duplicated GE-0118")

        result = run_validator(self.garden.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("GE-0118", result.stdout)

    def test_entry_missing_from_index_detected(self):
        """If harvest adds an entry to a file but forgets to update the index."""
        tools_git = self.garden.root / "tools" / "git.md"
        current = tools_git.read_text()
        # Add a new entry to the file but don't update GARDEN.md index
        new_entry = textwrap.dedent("""\
            ## Some New Git Gotcha

            **ID:** GE-0125
            **Stack:** Git (all versions)
            **Symptom:** Something unexpected.

            *Score: 9/15 · Included because: test · Reservation: none*

            ---
        """)
        tools_git.write_text(current + new_entry)
        self.garden.commit_all("merge: added entry but forgot to update index")

        result = run_validator(self.garden.root)
        # Entry in file but not in index — error (also missing from By Technology)
        self.assertEqual(result.returncode, 1)
        self.assertIn("GE-0125", result.stdout)

    def test_submission_with_duplicate_title_format_is_valid_for_harvest_review(self):
        """
        A submission that duplicates an existing entry is still a valid submission
        file — it's harvest's job to detect the duplicate during MERGE, not the
        validator's job. The validator only checks structural integrity.
        """
        # Submit something with the same title as GE-0118
        filename = self.garden.add_submission(
            "GE-0125",
            "git restore --staged Also Reverts Working Tree Changes",  # same as GE-0118
            "newproject"
        )
        self.garden.increment_counter("GE-0125")
        self.garden.commit("submit(newproject): GE-0125 'git restore duplicate'",
                           f"submissions/{filename}", "GARDEN.md")

        # Validator should still pass — submissions aren't checked for content duplicates
        result = run_validator(self.garden.root)
        self.assertEqual(result.returncode, 0, result.stdout)


class TestDedupeWorkflow(unittest.TestCase):
    """DEDUPE: within-category pair comparison across existing entries."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = GitGarden(Path(self.tmp.name))
        self.garden.init_garden("GE-0124")
        build_realistic_garden(self.garden)

    def tearDown(self):
        self.tmp.cleanup()

    def test_checked_md_records_pair_comparison(self):
        """After a DEDUPE sweep, CHECKED.md has the compared pairs."""
        # Simulate a DEDUPE session: compare GE-0115 and GE-0118 (both in tools/)
        checked_md = self.garden.root / "CHECKED.md"
        current = checked_md.read_text()
        current += "| GE-0115 × GE-0118 | distinct | 2026-04-09 | different maven vs git topics |\n"
        checked_md.write_text(current)

        # Reset drift counter
        garden_md = (self.garden.root / "GARDEN.md").read_text()
        garden_md = re.sub(
            r"Last full DEDUPE sweep:\*\*\s*[\d-]+",
            "Last full DEDUPE sweep:** 2026-04-09",
            garden_md
        )
        garden_md = re.sub(
            r"Entries merged since last sweep:\*\*\s*\d+",
            "Entries merged since last sweep:** 0",
            garden_md
        )
        (self.garden.root / "GARDEN.md").write_text(garden_md)

        self.garden.commit_all("dedupe: sweep 1 pair — distinct")

        # Validator should pass
        result = run_validator(self.garden.root)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_cross_category_pairs_not_checked(self):
        """GE-0115 (tools/maven.md) and GE-0110 (intellij-platform/) are never compared."""
        # These are in different categories — DEDUPE doesn't cross categories
        checked_content = self.garden.read_head("CHECKED.md")
        # They should NOT be in CHECKED.md (different categories)
        self.assertNotIn("GE-0115 × GE-0110", checked_content)
        self.assertNotIn("GE-0110 × GE-0115", checked_content)

    def test_checked_pairs_with_valid_ids_pass_validator(self):
        """CHECKED.md entries referencing real GE-IDs pass validation."""
        checked_md = self.garden.root / "CHECKED.md"
        current = checked_md.read_text()
        # Both GE-0115 and GE-0118 are real entries in tools/
        current += "| GE-0115 × GE-0118 | distinct | 2026-04-09 | |\n"
        checked_md.write_text(current)
        self.garden.commit_all("dedupe: log pair comparison")

        result = run_validator(self.garden.root)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_checked_pairs_with_invalid_id_triggers_warning(self):
        """CHECKED.md entries referencing a non-existent GE-ID trigger a warning."""
        checked_md = self.garden.root / "CHECKED.md"
        current = checked_md.read_text()
        current += "| GE-0115 × GE-9999 | distinct | 2026-04-09 | |\n"
        checked_md.write_text(current)
        self.garden.commit_all("dedupe: log pair with bad ID")

        result = run_validator(self.garden.root)
        self.assertIn(result.returncode, (1, 2))
        self.assertIn("GE-9999", result.stdout)


class TestGardenDriftCounter(unittest.TestCase):
    """Drift counter increments with each merge and resets after DEDUPE."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = GitGarden(Path(self.tmp.name))
        self.garden.init_garden("GE-0100")

    def tearDown(self):
        self.tmp.cleanup()

    def test_drift_counter_starts_at_zero(self):
        content = self.garden.read_head("GARDEN.md")
        m = re.search(r"Entries merged since last sweep:\*\*\s*(\d+)", content)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), 0)

    def test_drift_counter_increments_after_merge(self):
        # Simulate harvest incrementing the counter after a merge
        garden_md = (self.garden.root / "GARDEN.md").read_text()
        garden_md = re.sub(
            r"Entries merged since last sweep:\*\*\s*\d+",
            "Entries merged since last sweep:** 5",
            garden_md
        )
        (self.garden.root / "GARDEN.md").write_text(garden_md)
        self.garden.commit_all("merge: integrate 5 submissions")

        content = self.garden.read_head("GARDEN.md")
        m = re.search(r"Entries merged since last sweep:\*\*\s*(\d+)", content)
        self.assertEqual(int(m.group(1)), 5)

    def test_drift_counter_resets_after_dedupe(self):
        # Set to 15 (above threshold)
        garden_md = (self.garden.root / "GARDEN.md").read_text()
        garden_md = re.sub(
            r"Entries merged since last sweep:\*\*\s*\d+",
            "Entries merged since last sweep:** 15",
            garden_md
        )
        (self.garden.root / "GARDEN.md").write_text(garden_md)
        self.garden.commit_all("merge: integrate batch")

        # DEDUPE resets to 0
        garden_md = (self.garden.root / "GARDEN.md").read_text()
        garden_md = re.sub(
            r"Entries merged since last sweep:\*\*\s*\d+",
            "Entries merged since last sweep:** 0",
            garden_md
        )
        (self.garden.root / "GARDEN.md").write_text(garden_md)
        self.garden.commit_all("dedupe: sweep complete — drift counter reset")

        content = self.garden.read_head("GARDEN.md")
        m = re.search(r"Entries merged since last sweep:\*\*\s*(\d+)", content)
        self.assertEqual(int(m.group(1)), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ── Phase 4 E2E: integrate → drift → scan → record ───────────────────────────

import json as _json
import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from integrate_entry import integrate as _integrate
from unittest.mock import patch as _patch

_INTEGRATE_SCRIPT = Path(__file__).parent.parent / 'scripts' / 'integrate_entry.py'
_SCANNER_SCRIPT   = Path(__file__).parent.parent / 'scripts' / 'dedupe_scanner.py'
_VALIDATOR_SCRIPT = Path(__file__).parent.parent / 'scripts' / 'validate_garden.py'


def _run_scanner(*args) -> subprocess.CompletedProcess:
    import sys as _s
    return subprocess.run(
        [_s.executable, str(_SCANNER_SCRIPT)] + list(args),
        capture_output=True, text=True
    )


def _run_dedupe_check(garden: Path) -> subprocess.CompletedProcess:
    import sys as _s
    return subprocess.run(
        [_s.executable, str(_VALIDATOR_SCRIPT), '--dedupe-check', str(garden)],
        capture_output=True, text=True
    )


def _integrate_entry(entry: Path, garden: Path) -> dict:
    """Run integrate_entry.integrate() with git/validate mocked."""
    with _patch('integrate_entry.run_validate'), _patch('integrate_entry.git_commit'):
        return _integrate(str(entry), str(garden))


YAML_ENTRY_A = textwrap.dedent("""\
    ---
    id: GE-20260414-aaaa01
    title: "YAML frontmatter regex silently skips CRLF line endings"
    type: gotcha
    domain: python
    stack: "Python (all versions), re module"
    tags: [regex, yaml, crlf, parsing]
    score: 12
    verified: true
    staleness_threshold: 730
    submitted: 2026-04-14
    ---

    ## YAML frontmatter regex silently skips CRLF line endings

    **ID:** GE-20260414-aaaa01
    **Stack:** Python (all versions), re module
    **Symptom:** Files silently skipped.
    **Context:** YAML parsing on Windows.

    ### Root cause
    CRLF vs LF mismatch in regex.

    ### Fix
    Normalise with .replace('\\r\\n', '\\n').

    ### Why this is non-obvious
    No error, just silence.

    *Score: 12/15 · Included because: silent failure · Reservation: none*
""")

YAML_ENTRY_B = textwrap.dedent("""\
    ---
    id: GE-20260414-bbbb02
    title: "Regex date validation insufficient for calendar values in fromisoformat"
    type: gotcha
    domain: python
    stack: "Python 3.7+, datetime.date"
    tags: [regex, datetime, validation, parsing]
    score: 11
    verified: true
    staleness_threshold: 730
    submitted: 2026-04-14
    ---

    ## Regex date validation insufficient for calendar values in fromisoformat

    **ID:** GE-20260414-bbbb02
    **Stack:** Python 3.7+, datetime.date
    **Symptom:** ValueError on valid-format dates.
    **Context:** Date parsing with regex pre-validation.

    ### Root cause
    Regex checks shape not calendar validity.

    ### Fix
    Wrap fromisoformat in try/except ValueError.

    ### Why this is non-obvious
    Regex feels complete but is not.

    *Score: 11/15 · Included because: natural assumption · Reservation: none*
""")

YAML_ENTRY_C = textwrap.dedent("""\
    ---
    id: GE-20260414-cccc03
    title: "Structure architecture docs as property claims with guarantees"
    type: technique
    domain: tools
    stack: "Technical documentation (cross-cutting)"
    tags: [documentation, architecture, strategy, pattern]
    score: 14
    verified: true
    staleness_threshold: 1460
    submitted: 2026-04-14
    ---

    ## Structure architecture docs as property claims with guarantees

    **ID:** GE-20260414-cccc03
    **Stack:** Technical documentation
    **Labels:** #strategy #documentation

    ### The technique
    Use property claims as headings with Guarantees and Graceful Degradation.

    ### Why this is non-obvious
    Most developers write component tours, not property evaluations.

    *Score: 14/15 · Included because: high impact · Reservation: none*
""")


def _setup_yaml_garden(tmp_path: Path):
    """Set up a minimal garden with GARDEN.md, CHECKED.md, domain dirs."""
    (tmp_path / 'python').mkdir()
    (tmp_path / 'python' / 'INDEX.md').write_text(
        '| GE-ID | Title | Type | Score |\n|-------|-------|------|-------|\n'
    )
    (tmp_path / 'tools').mkdir()
    (tmp_path / 'tools' / 'INDEX.md').write_text(
        '| GE-ID | Title | Type | Score |\n|-------|-------|------|-------|\n'
    )
    (tmp_path / '_index').mkdir()
    (tmp_path / '_index' / 'global.md').write_text('| Domain | Index |\n|--------|-------|\n')
    (tmp_path / 'GARDEN.md').write_text(
        '**Last legacy ID:** GE-0001\n'
        '**Last full DEDUPE sweep:** 2026-04-14\n'
        '**Entries merged since last sweep:** 0\n'
        '**Drift threshold:** 3\n'
        '**Last staleness review:** never\n'
    )
    (tmp_path / 'CHECKED.md').write_text(
        '| Pair | Result | Date | Notes |\n|------|--------|------|-------|\n'
    )
    entry_a = tmp_path / 'python' / 'GE-20260414-aaaa01.md'
    entry_b = tmp_path / 'python' / 'GE-20260414-bbbb02.md'
    entry_c = tmp_path / 'tools' / 'GE-20260414-cccc03.md'
    entry_a.write_text(YAML_ENTRY_A)
    entry_b.write_text(YAML_ENTRY_B)
    entry_c.write_text(YAML_ENTRY_C)
    return entry_a, entry_b, entry_c


class TestE2EDedupeScanner(unittest.TestCase):
    """E2E: integrate entries → drift → scan → record → re-scan."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = Path(self.tmp.name)
        self.entry_a, self.entry_b, self.entry_c = _setup_yaml_garden(self.garden)

    def tearDown(self):
        self.tmp.cleanup()

    def test_happy_path_related_pair(self):
        """Integrate 2 similar entries → drift=2 → scan shows pair → record → re-scan empty."""
        import re
        _integrate_entry(self.entry_a, self.garden)
        _integrate_entry(self.entry_b, self.garden)

        # Drift should be 2
        content = (self.garden / 'GARDEN.md').read_text()
        m = re.search(r'\*\*Entries merged since last sweep:\*\*\s*(\d+)', content)
        self.assertEqual(int(m.group(1)), 2)

        # Scanner shows the python pair
        result = _run_scanner(str(self.garden), '--domain', 'python')
        self.assertIn('GE-20260414-aaaa01', result.stdout)
        self.assertIn('GE-20260414-bbbb02', result.stdout)

        # Pair has non-zero score (both share 'regex' and 'parsing')
        result_json = _run_scanner(str(self.garden), '--domain', 'python', '--json')
        data = _json.loads(result_json.stdout)
        self.assertEqual(len(data), 1)
        self.assertGreater(data[0]['score'], 0.0)

        # Record as related
        _run_scanner(str(self.garden), '--record',
                     'GE-20260414-aaaa01 × GE-20260414-bbbb02', 'related',
                     'both regex validation gaps')

        # Re-scan — pair absent
        result2 = _run_scanner(str(self.garden), '--domain', 'python')
        self.assertIn('No unchecked pairs', result2.stdout)

    def test_happy_path_no_cross_domain_pairs(self):
        """Entry A (python) and Entry C (tools) — no cross-domain pairs generated."""
        # Remove entry_b so only entry_a is in the python domain
        self.entry_b.unlink()
        _integrate_entry(self.entry_a, self.garden)
        _integrate_entry(self.entry_c, self.garden)

        # python has 1 entry, tools has 1 entry — no within-domain pairs
        result = _run_scanner(str(self.garden))
        self.assertIn('No unchecked pairs', result.stdout)

    def test_happy_path_drift_triggers_dedupe_check(self):
        """Integrate 3 entries → drift=3 >= threshold=3 → --dedupe-check warns."""
        _integrate_entry(self.entry_a, self.garden)
        _integrate_entry(self.entry_b, self.garden)
        _integrate_entry(self.entry_c, self.garden)

        result = _run_dedupe_check(self.garden)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('DEDUPE recommended', result.stdout)

    def test_happy_path_bulk_import_all_pairs_generated(self):
        """3 entries in same domain → 3 pairs (3×2/2) generated by scanner."""
        entry_d = self.garden / 'python' / 'GE-20260414-dddd04.md'
        entry_d.write_text(
            YAML_ENTRY_A.replace('GE-20260414-aaaa01', 'GE-20260414-dddd04')
                        .replace('silently skips CRLF', 'raises ValueError on invalid')
        )
        # 3 python entries: aaaa01, bbbb02, dddd04
        result_json = _run_scanner(str(self.garden), '--domain', 'python', '--json')
        data = _json.loads(result_json.stdout)
        self.assertEqual(len(data), 3)

    def test_happy_path_top_flag_in_e2e_context(self):
        """--top 1 returns only the highest-scoring pair from scanner."""
        entry_d = self.garden / 'python' / 'GE-20260414-dddd04.md'
        # Make dddd04 identical to aaaa01 so they score 1.0
        entry_d.write_text(
            YAML_ENTRY_A.replace('GE-20260414-aaaa01', 'GE-20260414-dddd04')
        )

        result_all = _run_scanner(str(self.garden), '--domain', 'python', '--json')
        result_top1 = _run_scanner(str(self.garden), '--domain', 'python', '--json', '--top', '1')

        all_data = _json.loads(result_all.stdout)
        top_data = _json.loads(result_top1.stdout)

        self.assertEqual(len(top_data), 1)
        # Top result should be the highest-scoring pair
        self.assertEqual(top_data[0]['score'], all_data[0]['score'])


# ── Phase 5 E2E: init_garden pipeline ─────────────────────────────────────────

_INIT     = Path(__file__).parent.parent / 'scripts' / 'init_garden.py'
_SCHEMA_V = Path(__file__).parent.parent / 'scripts' / 'validate_schema.py'


def _run_init_garden(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_sys.executable, str(_INIT)] + list(args),
        capture_output=True, text=True
    )


def _run_schema_validator(garden: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_sys.executable, str(_SCHEMA_V), str(garden)],
        capture_output=True, text=True
    )


_E2E_ENTRY = textwrap.dedent("""\
    ---
    id: GE-20260414-e2e001
    title: "E2E test entry for init_garden pipeline"
    type: gotcha
    domain: java
    stack: "Java (all versions)"
    tags: [java, testing]
    score: 10
    verified: true
    staleness_threshold: 730
    submitted: 2026-04-14
    ---

    ## E2E test entry for init_garden pipeline

    **ID:** GE-20260414-e2e001
    **Stack:** Java (all versions)
    **Symptom:** Test symptom.
    **Context:** E2E test.

    ### What was tried (didn't work)
    - tried X — failed

    ### Root cause
    E2E root cause.

    ### Fix
    E2E fix.

    ### Why this is non-obvious
    Used in E2E tests.

    *Score: 10/15 · Included because: test coverage · Reservation: none*
""")


class TestE2EInitGardenPipeline(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = Path(self.tmp.name) / 'test-jvm-garden'

    def tearDown(self):
        self.tmp.cleanup()

    def _init(self, role='canonical', ge_prefix='JE-',
              domains=None, upstream=None):
        domains = domains or ['java', 'quarkus']
        args = [
            str(self.garden),
            '--name', 'test-jvm-garden',
            '--description', 'Test JVM garden',
            '--role', role,
            '--ge-prefix', ge_prefix,
            '--domains', *domains,
        ]
        if upstream:
            args += ['--upstream', *upstream]
        return _run_init_garden(*args)

    def _git_init(self):
        for cmd in [
            ['git', 'init', str(self.garden)],
            ['git', '-C', str(self.garden), 'config', 'user.email', 'test@test.com'],
            ['git', '-C', str(self.garden), 'config', 'user.name', 'Test'],
            ['git', '-C', str(self.garden), 'add', '.'],
            ['git', '-C', str(self.garden), 'commit', '-m', 'init'],
        ]:
            subprocess.run(cmd, check=True, capture_output=True)

    def test_init_exits_0(self):
        result = self._init()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_schema_validates_after_init(self):
        self._init()
        result = _run_schema_validator(self.garden)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_garden_structure_complete_after_init(self):
        self._init()
        for path in [
            'GARDEN.md', 'SCHEMA.md', 'CHECKED.md', 'DISCARDED.md',
            '.github/workflows/validate_pr.yml',
            'java/INDEX.md', 'quarkus/INDEX.md',
        ]:
            self.assertTrue((self.garden / path).exists(), f"Missing {path}")

    def test_validate_pr_accepts_entry_on_pr_branch(self):
        """Full pipeline: init → git init → add entry on branch → validate_pr passes."""
        self._init()
        self._git_init()

        subprocess.run(
            ['git', '-C', str(self.garden), 'checkout', '-b', 'submit/GE-20260414-e2e001'],
            check=True, capture_output=True
        )
        entry_path = self.garden / 'java' / 'GE-20260414-e2e001.md'
        entry_path.write_text(_E2E_ENTRY)
        subprocess.run(['git', '-C', str(self.garden), 'add', '.'],
                       check=True, capture_output=True)
        subprocess.run(
            ['git', '-C', str(self.garden), 'commit', '-m', 'submit: e2e test entry'],
            check=True, capture_output=True
        )

        VALIDATE_PR_SCRIPT = Path(__file__).parent.parent / 'scripts' / 'validate_pr.py'
        result = subprocess.run(
            [_sys.executable, str(VALIDATE_PR_SCRIPT), str(entry_path), str(self.garden)],
            capture_output=True, text=True, cwd=str(self.garden)
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_child_garden_schema_validates(self):
        self._init(
            role='child', ge_prefix='ME-',
            domains=['java'],
            upstream=['https://github.com/Hortora/jvm-garden'],
        )
        result = _run_schema_validator(self.garden)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_idempotent_second_init_does_not_corrupt(self):
        self._init()
        self._init()
        result = _run_schema_validator(self.garden)
        self.assertEqual(result.returncode, 0)
