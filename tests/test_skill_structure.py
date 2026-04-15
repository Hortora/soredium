#!/usr/bin/env python3
"""
Structural validation tests for forage/SKILL.md and harvest/SKILL.md.

Checks:
- YAML frontmatter present with required fields
- description starts with "Use when"
- Required workflow sections are present
- submission-formats.md exists alongside forage/SKILL.md
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
FORAGE_SKILL = REPO_ROOT / "forage" / "SKILL.md"
HARVEST_SKILL = REPO_ROOT / "harvest" / "SKILL.md"
FORAGE_FORMATS = REPO_ROOT / "forage" / "submission-formats.md"


def parse_frontmatter(content: str) -> dict[str, str]:
    """Extract YAML frontmatter fields as a dict of raw strings."""
    m = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not m:
        return {}
    fields = {}
    for line in m.group(1).splitlines():
        if ':' in line and not line.startswith(' '):
            key, _, val = line.partition(':')
            fields[key.strip()] = val.strip()
    return fields


def get_description(content: str) -> str:
    """Extract the full description value (may span multiple lines after >)."""
    m = re.search(r'^description:\s*>\s*\n((?:[ \t]+.+\n?)+)', content, re.MULTILINE)
    if m:
        return ' '.join(line.strip() for line in m.group(1).splitlines())
    m = re.search(r'^description:\s*(.+)', content, re.MULTILINE)
    return m.group(1).strip() if m else ""


class TestSkillFileExists(unittest.TestCase):

    def test_forage_skill_md_exists(self):
        self.assertTrue(FORAGE_SKILL.exists(), f"Missing: {FORAGE_SKILL}")

    def test_harvest_skill_md_exists(self):
        self.assertTrue(HARVEST_SKILL.exists(), f"Missing: {HARVEST_SKILL}")

    def test_forage_submission_formats_exists(self):
        self.assertTrue(FORAGE_FORMATS.exists(), f"Missing: {FORAGE_FORMATS}")


class TestForageFrontmatter(unittest.TestCase):

    def setUp(self):
        self.content = FORAGE_SKILL.read_text()
        self.fm = parse_frontmatter(self.content)

    def test_has_frontmatter(self):
        self.assertTrue(self.fm, "No YAML frontmatter found in forage/SKILL.md")

    def test_has_name_field(self):
        self.assertIn("name", self.fm)
        self.assertEqual(self.fm["name"], "forage")

    def test_has_description_field(self):
        self.assertIn("description", self.fm)

    def test_description_starts_with_use_when(self):
        description = get_description(self.content)
        self.assertTrue(
            description.startswith("Use when"),
            f"description should start with 'Use when', got: {description[:60]!r}"
        )

    def test_description_under_500_chars(self):
        description = get_description(self.content)
        self.assertLessEqual(
            len(description), 500,
            f"description is {len(description)} chars (max 500)"
        )


class TestHarvestFrontmatter(unittest.TestCase):

    def setUp(self):
        self.content = HARVEST_SKILL.read_text()
        self.fm = parse_frontmatter(self.content)

    def test_has_frontmatter(self):
        self.assertTrue(self.fm, "No YAML frontmatter found in harvest/SKILL.md")

    def test_has_name_field(self):
        self.assertIn("name", self.fm)
        self.assertEqual(self.fm["name"], "harvest")

    def test_has_description_field(self):
        self.assertIn("description", self.fm)

    def test_description_starts_with_use_when(self):
        description = get_description(self.content)
        self.assertTrue(
            description.startswith("Use when"),
            f"description should start with 'Use when', got: {description[:60]!r}"
        )

    def test_description_under_500_chars(self):
        description = get_description(self.content)
        self.assertLessEqual(
            len(description), 500,
            f"description is {len(description)} chars (max 500)"
        )


class TestForageRequiredSections(unittest.TestCase):

    def setUp(self):
        self.content = FORAGE_SKILL.read_text()

    def _has_section(self, heading: str) -> bool:
        return bool(re.search(rf'^###?\s+{re.escape(heading)}', self.content, re.MULTILINE))

    def test_has_capture_workflow(self):
        self.assertTrue(self._has_section("CAPTURE"), "Missing ### CAPTURE section")

    def test_has_sweep_workflow(self):
        self.assertTrue(self._has_section("SWEEP"), "Missing ### SWEEP section")

    def test_has_revise_workflow(self):
        self.assertTrue(self._has_section("REVISE"), "Missing ### REVISE section")

    def test_has_search_workflow(self):
        self.assertTrue(self._has_section("SEARCH"), "Missing ### SEARCH section")

    def test_has_import_workflow(self):
        self.assertTrue(self._has_section("IMPORT"), "Missing ### IMPORT section")

    def test_has_common_pitfalls(self):
        self.assertIn("Common Pitfalls", self.content)

    def test_has_success_criteria(self):
        self.assertIn("Success Criteria", self.content)

    def test_has_skill_chaining(self):
        self.assertIn("Skill Chaining", self.content)

    def test_references_submission_formats(self):
        self.assertIn("submission-formats.md", self.content,
                      "forage/SKILL.md should reference submission-formats.md")

    def test_references_harvest_for_merge(self):
        self.assertIn("harvest", self.content.lower(),
                      "forage/SKILL.md should mention harvest for MERGE/DEDUPE")

    def test_search_documents_upstream_chain_walk(self):
        self.assertIn("upstream chain", self.content.lower(),
                      "SEARCH should document upstream chain walk for child gardens")

    def test_search_documents_peer_search(self):
        self.assertIn("peer", self.content.lower(),
                      "SEARCH should document peer garden search")

    def test_search_documents_garden_label(self):
        # Entries from non-local gardens should be labelled with their source
        self.assertIn("[upstream:", self.content,
                      "SEARCH should show [upstream: <name>] label on results from parent gardens")

    def test_search_references_route_submission(self):
        self.assertIn("route_submission.py", self.content,
                      "SEARCH should reference route_submission.py for domain routing")


class TestHarvestRequiredSections(unittest.TestCase):

    def setUp(self):
        self.content = HARVEST_SKILL.read_text()

    def _has_section(self, heading: str) -> bool:
        return bool(re.search(rf'^###?\s+{re.escape(heading)}', self.content, re.MULTILINE))

    def test_has_merge_workflow(self):
        # Merge/consolidation workflow is documented within DEDUPE — verify the discard
        # artifact is referenced, which proves the duplicate resolution process is present
        self.assertIn("DISCARDED.md", self.content,
                      "harvest should document the duplicate discard log (DISCARDED.md)")

    def test_has_dedupe_workflow(self):
        self.assertTrue(self._has_section("DEDUPE"), "Missing ### DEDUPE section")

    def test_has_common_pitfalls(self):
        self.assertIn("Common Pitfalls", self.content)

    def test_has_success_criteria(self):
        self.assertIn("Success Criteria", self.content)

    def test_has_skill_chaining(self):
        self.assertIn("Skill Chaining", self.content)

    def test_references_validator(self):
        self.assertIn("validate_garden.py", self.content,
                      "harvest/SKILL.md should reference validate_garden.py in success criteria")

    def test_does_not_have_capture(self):
        self.assertFalse(self._has_section("CAPTURE"),
                         "harvest/SKILL.md should not contain CAPTURE (that's forage)")

    def test_does_not_have_sweep(self):
        self.assertFalse(self._has_section("SWEEP"),
                         "harvest/SKILL.md should not contain SWEEP (that's forage)")

    def test_references_forage_for_session_ops(self):
        self.assertIn("forage", self.content.lower(),
                      "harvest/SKILL.md should mention forage for session-time operations")


class TestSubmissionFormatsContent(unittest.TestCase):

    def setUp(self):
        self.content = FORAGE_FORMATS.read_text()

    def test_has_gotcha_template(self):
        self.assertIn("Gotcha Template", self.content)

    def test_has_technique_template(self):
        self.assertIn("Technique Template", self.content)

    def test_has_undocumented_template(self):
        self.assertIn("Undocumented Template", self.content)

    def test_has_revise_template(self):
        self.assertIn("Revise Template", self.content)

    def test_has_scoring_dimensions(self):
        self.assertIn("Scoring Dimensions", self.content)

    def test_has_ge_id_in_templates(self):
        self.assertIn("GE-XXXX", self.content)

    def test_has_submission_id_field(self):
        self.assertIn("Submission ID", self.content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
