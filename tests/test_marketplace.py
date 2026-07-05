#!/usr/bin/env python3
"""Marketplace completeness tests.

Verifies that every committed skill directory with a non-DEV-ONLY SKILL.md has
an entry in marketplace.json, and every marketplace.json entry has a committed
skill directory.

Refs #76
"""

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
MARKETPLACE_JSON = REPO_ROOT / ".claude-plugin" / "marketplace.json"

INFRA_DIRS = {
    "docs", "engine", "hooks", "registry", "scripts", "target",
    "tests", "wksp", ".claude", ".claude-plugin", ".git", "__pycache__",
}


def is_dev_only(skill_md: Path) -> bool:
    """Check if a SKILL.md is marked as DEV-ONLY."""
    content = skill_md.read_text()
    return "DEV-ONLY" in content[:500]


def discover_skill_dirs() -> set[str]:
    """Return names of all skill directories with non-DEV-ONLY SKILL.md."""
    skills = set()
    for d in REPO_ROOT.iterdir():
        if not d.is_dir() or d.name in INFRA_DIRS or d.name.startswith("."):
            continue
        skill_md = d / "SKILL.md"
        if skill_md.exists() and not is_dev_only(skill_md):
            skills.add(d.name)
    return skills


def load_marketplace_entries() -> dict[str, str]:
    """Return {plugin_name: source_path} from marketplace.json."""
    if not MARKETPLACE_JSON.exists():
        return {}
    data = json.loads(MARKETPLACE_JSON.read_text())
    entries = {}
    for plugin in data.get("plugins", []):
        name = plugin.get("name", "")
        source = plugin.get("source", "")
        entries[name] = source
    return entries


class TestMarketplaceCompleteness(unittest.TestCase):

    def setUp(self):
        self.skill_dirs = discover_skill_dirs()
        self.marketplace = load_marketplace_entries()
        self.marketplace_names = set(self.marketplace.keys())

    def test_marketplace_json_exists(self):
        self.assertTrue(
            MARKETPLACE_JSON.exists(),
            f"Missing: {MARKETPLACE_JSON}",
        )

    def test_every_skill_in_marketplace(self):
        missing = self.skill_dirs - self.marketplace_names
        if missing:
            self.fail(
                f"{len(missing)} skill(s) have SKILL.md but no marketplace.json entry: "
                + ", ".join(sorted(missing))
            )

    def test_every_marketplace_entry_has_skill(self):
        orphaned = self.marketplace_names - self.skill_dirs
        if orphaned:
            self.fail(
                f"{len(orphaned)} marketplace.json entry/entries have no skill directory: "
                + ", ".join(sorted(orphaned))
            )

    def test_marketplace_source_paths_valid(self):
        bad_paths = []
        for name, source in self.marketplace.items():
            expected = f"./{name}"
            if source != expected:
                bad_paths.append(f"{name}: source={source!r}, expected={expected!r}")
            skill_dir = REPO_ROOT / name
            if not skill_dir.is_dir():
                bad_paths.append(f"{name}: directory does not exist")
        if bad_paths:
            self.fail("Invalid marketplace source paths:\n" + "\n".join(bad_paths))

    def test_marketplace_descriptions_match_frontmatter(self):
        """Marketplace description should be a prefix of the SKILL.md frontmatter description."""
        mismatches = []
        for name in self.marketplace_names & self.skill_dirs:
            skill_md = REPO_ROOT / name / "SKILL.md"
            content = skill_md.read_text()
            m = re.search(r"^description:\s*>\s*\n((?:[ \t]+.+\n?)+)", content, re.MULTILINE)
            if m:
                frontmatter_desc = " ".join(line.strip() for line in m.group(1).splitlines())
            else:
                m = re.search(r"^description:\s*(.+)", content, re.MULTILINE)
                frontmatter_desc = m.group(1).strip() if m else ""

            marketplace_desc = self.marketplace.get(name, "")
            mp_entry = None
            data = json.loads(MARKETPLACE_JSON.read_text())
            for p in data.get("plugins", []):
                if p.get("name") == name:
                    mp_entry = p
                    break
            if not mp_entry:
                continue
            mp_desc = mp_entry.get("description", "")

            if frontmatter_desc and mp_desc:
                if not frontmatter_desc.startswith(mp_desc[:50]):
                    if not mp_desc.startswith(frontmatter_desc[:50]):
                        mismatches.append(
                            f"{name}:\n"
                            f"  frontmatter: {frontmatter_desc[:80]}...\n"
                            f"  marketplace: {mp_desc[:80]}..."
                        )
        if mismatches:
            self.fail(
                f"{len(mismatches)} description mismatch(es):\n" + "\n".join(mismatches)
            )


class TestMarketplaceStructure(unittest.TestCase):

    def test_has_required_top_level_fields(self):
        data = json.loads(MARKETPLACE_JSON.read_text())
        for field in ("name", "description", "owner", "plugins"):
            self.assertIn(field, data, f"Missing top-level field: {field}")

    def test_plugins_have_required_fields(self):
        data = json.loads(MARKETPLACE_JSON.read_text())
        for plugin in data.get("plugins", []):
            for field in ("name", "source", "description", "version"):
                self.assertIn(
                    field, plugin,
                    f"Plugin {plugin.get('name', '?')} missing field: {field}",
                )

    def test_no_duplicate_plugin_names(self):
        data = json.loads(MARKETPLACE_JSON.read_text())
        names = [p.get("name") for p in data.get("plugins", [])]
        dupes = [n for n in names if names.count(n) > 1]
        self.assertEqual(
            list(set(dupes)), [],
            f"Duplicate plugin names: {set(dupes)}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
