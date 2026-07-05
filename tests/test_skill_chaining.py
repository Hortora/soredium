#!/usr/bin/env python3
"""Cross-reference consistency tests for Skill Chaining sections.

Parses every SKILL.md's Skill Chaining section and verifies:
- Invoked by / Invokes pairs are symmetric
- Complements references exist in the target skill
- No dangling references to skills that don't exist
- The "debugging toolkit" framing appears identically in all three toolkit skills

Refs #76
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

INFRA_DIRS = {
    "docs", "engine", "hooks", "registry", "scripts", "target",
    "tests", "wksp", ".claude", ".claude-plugin", ".git", "__pycache__",
}


def discover_skills() -> dict[str, Path]:
    """Return {skill_name: SKILL.md path} for all skill directories."""
    skills = {}
    for d in sorted(REPO_ROOT.iterdir()):
        if not d.is_dir() or d.name in INFRA_DIRS or d.name.startswith("."):
            continue
        skill_md = d / "SKILL.md"
        if skill_md.exists():
            skills[d.name] = skill_md
    return skills


def extract_skill_chaining(content: str) -> str:
    """Extract the Skill Chaining section from a SKILL.md."""
    m = re.search(r"^##\s+Skill Chaining\s*\n(.*?)(?=\n##\s|\Z)", content, re.MULTILINE | re.DOTALL)
    return m.group(1) if m else ""


def extract_skill_refs(text: str) -> set[str]:
    """Extract skill name references from a section of text.

    Matches patterns like:
    - [`skill-name`]
    - `skill-name` (when preceded by invocation context)
    - skill-name — (in list items)
    """
    refs = set()
    backtick_refs = re.findall(r"`([a-z][a-z0-9-]+)`", text)
    for ref in backtick_refs:
        if ref in ALL_SKILLS:
            refs.add(ref)
    return refs


def extract_field_refs(chaining_text: str, field: str) -> set[str]:
    """Extract skill references from a specific field (Invoked by, Invokes, Complements, etc.)."""
    pattern = rf"\*\*{re.escape(field)}[:\*].*?\*\*\s*(.*?)(?=\n\*\*|\n##|\Z)"
    m = re.search(pattern, chaining_text, re.DOTALL | re.IGNORECASE)
    if not m:
        return set()
    return extract_skill_refs(m.group(1))


def extract_debugging_toolkit_block(content: str) -> str:
    """Extract the debugging toolkit block if present."""
    m = re.search(
        r"\*\*The debugging toolkit:\*\*\s*(.*?)(?=\n\n|\n\*\*|\n##|\Z)",
        content, re.DOTALL,
    )
    return m.group(0).strip() if m else ""


ALL_SKILLS: dict[str, Path] = {}
CHAINING_SECTIONS: dict[str, str] = {}


def setUpModule():
    global ALL_SKILLS, CHAINING_SECTIONS
    ALL_SKILLS = discover_skills()
    for name, path in ALL_SKILLS.items():
        content = path.read_text()
        CHAINING_SECTIONS[name] = extract_skill_chaining(content)


class TestNoDanglingReferences(unittest.TestCase):
    """Every skill referenced in a Skill Chaining section must exist as a directory."""

    def test_no_dangling_refs(self):
        dangling = []
        for skill_name, section in CHAINING_SECTIONS.items():
            if not section:
                continue
            refs = extract_skill_refs(section)
            for ref in refs:
                if ref not in ALL_SKILLS and ref != skill_name:
                    dangling.append(f"{skill_name} references non-existent skill `{ref}`")
        self.assertEqual(dangling, [], "\n".join(dangling))


class TestInvokesSymmetry(unittest.TestCase):
    """If A says 'Invokes: B', then B should say 'Invoked by: A' (or mention A somewhere)."""

    def test_invokes_has_invoked_by(self):
        asymmetric = []
        for skill_name, section in CHAINING_SECTIONS.items():
            if not section:
                continue
            invokes = extract_field_refs(section, "Invokes")
            for target in invokes:
                if target == skill_name:
                    continue
                target_section = CHAINING_SECTIONS.get(target, "")
                if not target_section:
                    continue
                target_refs = extract_skill_refs(target_section)
                if skill_name not in target_refs:
                    asymmetric.append(
                        f"`{skill_name}` invokes `{target}`, but `{target}` "
                        f"does not reference `{skill_name}` in its Skill Chaining"
                    )
        if asymmetric:
            self.fail("Asymmetric Invokes/Invoked-by:\n" + "\n".join(asymmetric))


class TestInvokedBySymmetry(unittest.TestCase):
    """If A says 'Invoked by: B', then B should mention A somewhere in its chaining section."""

    def test_invoked_by_has_mention(self):
        asymmetric = []
        for skill_name, section in CHAINING_SECTIONS.items():
            if not section:
                continue
            invoked_by = extract_field_refs(section, "Invoked by")
            for source in invoked_by:
                if source == skill_name:
                    continue
                source_section = CHAINING_SECTIONS.get(source, "")
                if not source_section:
                    continue
                source_refs = extract_skill_refs(source_section)
                if skill_name not in source_refs:
                    asymmetric.append(
                        f"`{skill_name}` says invoked by `{source}`, but `{source}` "
                        f"does not reference `{skill_name}` in its Skill Chaining"
                    )
        if asymmetric:
            self.fail("Asymmetric Invoked-by:\n" + "\n".join(asymmetric))


class TestComplementsExist(unittest.TestCase):
    """Every skill listed in Complements must exist and should mention the referencing skill."""

    def test_complements_bidirectional(self):
        asymmetric = []
        for skill_name, section in CHAINING_SECTIONS.items():
            if not section:
                continue
            complements = extract_field_refs(section, "Complements")
            for target in complements:
                if target == skill_name:
                    continue
                if target not in ALL_SKILLS:
                    asymmetric.append(
                        f"`{skill_name}` complements non-existent `{target}`"
                    )
                    continue
                target_section = CHAINING_SECTIONS.get(target, "")
                if not target_section:
                    continue
                target_refs = extract_skill_refs(target_section)
                if skill_name not in target_refs:
                    asymmetric.append(
                        f"`{skill_name}` complements `{target}`, but `{target}` "
                        f"does not reference `{skill_name}` in its Skill Chaining"
                    )
        if asymmetric:
            self.fail("Asymmetric Complements:\n" + "\n".join(asymmetric))


class TestDebuggingToolkitConsistency(unittest.TestCase):
    """The debugging toolkit framing must appear identically in all three toolkit skills."""

    TOOLKIT_SKILLS = ["systematic-debugging", "dispatching-parallel-agents", "fix-ci"]

    def test_all_three_have_toolkit_block(self):
        for skill in self.TOOLKIT_SKILLS:
            path = ALL_SKILLS.get(skill)
            self.assertIsNotNone(path, f"Missing skill: {skill}")
            content = path.read_text()
            block = extract_debugging_toolkit_block(content)
            self.assertTrue(
                block, f"`{skill}` is missing the debugging toolkit block"
            )

    def test_toolkit_framing_consistent(self):
        blocks = {}
        for skill in self.TOOLKIT_SKILLS:
            path = ALL_SKILLS.get(skill)
            if not path:
                continue
            content = path.read_text()
            block = extract_debugging_toolkit_block(content)
            normalized = re.sub(r"\(this skill\)\s*", "", block)
            normalized = re.sub(r"\s+", " ", normalized).strip()
            blocks[skill] = normalized

        unique = set(blocks.values())
        if len(unique) > 1:
            details = "\n".join(f"  {k}: {v[:120]}..." for k, v in blocks.items())
            self.fail(
                f"Debugging toolkit framing differs across skills:\n{details}"
            )


class TestAllSkillsHaveChaining(unittest.TestCase):
    """Every skill SKILL.md should have a Skill Chaining section."""

    EXEMPT = {"using-superpowers", "ide-tooling", "ide-index-mcp"}

    def test_chaining_section_present(self):
        missing = []
        for skill_name in ALL_SKILLS:
            if skill_name in self.EXEMPT:
                continue
            if not CHAINING_SECTIONS.get(skill_name):
                missing.append(skill_name)
        if missing:
            self.fail(
                f"{len(missing)} skill(s) missing Skill Chaining section: "
                + ", ".join(sorted(missing))
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
