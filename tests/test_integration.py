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
