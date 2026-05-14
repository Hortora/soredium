# Convention Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `type: convention` and `variant:` field to the Hortora garden schema, enforcing grouping consistency at PR-time (validate_pr.py) and garden-wide (validate_garden.py), with templates and skill documentation updated throughout.

**Architecture:** TDD throughout — write failing test, verify it fails, implement, verify it passes, commit. Four code/doc touch points: validate_pr.py (type + variant check), validate_garden.py (whole-garden backup check), submission-formats.md (convention template), forage/SKILL.md (11 enumeration sites + new SWEEP step).

**Tech Stack:** Python 3, PyYAML, pytest; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-14-convention-schema-design.md`
**Issue:** Hortora/soredium#44

---

## File Map

| File | Change |
|------|--------|
| `scripts/validate_pr.py` | Add `convention` to valid types; add `find_same_title_siblings`; add variant consistency check + Jaccard suppression |
| `scripts/validate_garden.py` | Add `import yaml`; add check 8 (same-title variant consistency) |
| `forage/submission-formats.md` | Add `variant:` to Optional Frontmatter Fields table; add Convention Template |
| `forage/SKILL.md` | Update 11 enumeration sites; add SWEEP Step 4; add Proactive Trigger; update garden table + editorial bar; add scoring note |
| `tests/test_validate_pr.py` | New test classes: `TestConventionType`, `TestFindSameTitleSiblings`, `TestVariantConsistencyPR` |
| `tests/test_validate_garden.py` | New test class: `TestVariantConsistencyGarden` |

---

### Task 1: Add `convention` to valid types in validate_pr.py

**Files:**
- Modify: `scripts/validate_pr.py` (line 57)
- Test: `tests/test_validate_pr.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_validate_pr.py`:

```python
CONVENTION_ENTRY_BASE = """\
---
title: "Maven submodule naming"
garden: discovery
type: convention
domain: jvm
stack: "Maven, Quarkus"
tags: [maven]
score: 9
verified: true
staleness_threshold: 3650
submitted: 2026-05-14
---

## Maven submodule naming

### The convention
Use api/runtime/deployment for Quarkus extension modules.

### Why this style
Matches Quarkus extension conventions.

### Trade-offs
Less familiar to Spring developers.

### When not to use it
When adopting Spring Boot layered naming.
"""

CONVENTION_ENTRY_WITH_VARIANT = """\
---
title: "Maven submodule naming"
variant: "api/runtime/deployment — Quarkus extension style"
garden: discovery
type: convention
domain: jvm
stack: "Maven, Quarkus"
tags: [maven]
score: 9
verified: true
staleness_threshold: 3650
submitted: 2026-05-14
---

## api/runtime/deployment — Quarkus extension style

**Topic:** Maven submodule naming
**Alternatives exist:** yes

### The convention
Use api/runtime/deployment for Quarkus extension modules.

### Why this style
Matches Quarkus extension conventions.

### Trade-offs
Less familiar to Spring developers.

### When not to use it
When adopting Spring Boot layered naming.
"""


class TestConventionType(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, stem: str, content: str) -> Path:
        p = self.dir / f"{stem}.md"
        p.write_text(content)
        return p

    def test_convention_accepted_in_discovery_garden(self):
        path = self._write("GE-20260514-aaaaaa", CONVENTION_ENTRY_BASE)
        result = validate(str(path))
        self.assertFalse(
            any("convention" in c.lower() and "invalid" in c.lower()
                for c in result['criticals']),
            f"Unexpected CRITICAL: {result['criticals']}"
        )

    def test_convention_rejected_in_patterns_garden(self):
        entry = CONVENTION_ENTRY_BASE.replace("garden: discovery", "garden: patterns")
        path = self._write("GE-20260514-aaaaaa", entry)
        result = validate(str(path))
        self.assertTrue(
            any("convention" in c.lower() for c in result['criticals']),
            f"Expected type-rejection CRITICAL, got: {result['criticals']}"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/claude/hortora/soredium
python3 -m pytest tests/test_validate_pr.py::TestConventionType -v
```

Expected: both tests FAIL — `test_convention_accepted` will fail because `convention` triggers a type-invalid CRITICAL; `test_convention_rejected` will FAIL because `convention` is unexpected for patterns too (currently any unknown type fails, which might make the test pass by accident — if so, the first test drives the change).

- [ ] **Step 3: Add `convention` to discovery valid types**

In `scripts/validate_pr.py`, find:

```python
    'discovery': {
        'valid_types': ['gotcha', 'technique', 'undocumented'],
```

Replace with:

```python
    'discovery': {
        'valid_types': ['gotcha', 'technique', 'undocumented', 'convention'],
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_validate_pr.py::TestConventionType -v
```

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/claude/hortora/soredium
git add scripts/validate_pr.py tests/test_validate_pr.py
git commit -m "feat(validate_pr): add convention to discovery valid types (soredium#44)"
```

---

### Task 2: Add `find_same_title_siblings` + variant consistency check to validate_pr.py

**Files:**
- Modify: `scripts/validate_pr.py`
- Test: `tests/test_validate_pr.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_validate_pr.py` (after the previous additions). Add this import at the top of the file if not already present:

```python
from validate_pr import validate, detect_mode, find_same_title_siblings
```

Then append these test classes:

```python
class TestFindSameTitleSiblings(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = Path(self.tmp.name)
        self.domain_dir = self.garden / "jvm"
        self.domain_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_entry(self, stem: str, title: str) -> Path:
        path = self.domain_dir / f"{stem}.md"
        path.write_text(
            f'---\ntitle: "{title}"\ntype: convention\ndomain: jvm\n'
            f'stack: "Test"\ntags: [test]\nscore: 9\nverified: true\n'
            f'staleness_threshold: 730\nsubmitted: 2026-05-14\n---\n'
        )
        return path

    def test_returns_stems_with_matching_title(self):
        self._write_entry("GE-20260514-aaaaaa", "Maven submodule naming")
        self._write_entry("GE-20260514-bbbbbb", "Maven submodule naming")
        result = find_same_title_siblings(
            "Maven submodule naming", "jvm", self.garden, "GE-20260514-cccccc"
        )
        self.assertIn("GE-20260514-aaaaaa", result)
        self.assertIn("GE-20260514-bbbbbb", result)

    def test_excludes_self(self):
        self._write_entry("GE-20260514-aaaaaa", "Maven submodule naming")
        result = find_same_title_siblings(
            "Maven submodule naming", "jvm", self.garden, "GE-20260514-aaaaaa"
        )
        self.assertNotIn("GE-20260514-aaaaaa", result)

    def test_empty_domain_returns_empty(self):
        result = find_same_title_siblings(
            "Anything", "nonexistent", self.garden, "GE-xxx"
        )
        self.assertEqual(result, [])

    def test_title_mismatch_not_returned(self):
        self._write_entry("GE-20260514-aaaaaa", "Different title")
        result = find_same_title_siblings(
            "Maven submodule naming", "jvm", self.garden, "GE-xxx"
        )
        self.assertEqual(result, [])

    def test_unparseable_file_skipped_silently(self):
        bad = self.domain_dir / "GE-20260514-cccccc.md"
        bad.write_text("not valid yaml at all {\n")
        self._write_entry("GE-20260514-aaaaaa", "Maven submodule naming")
        result = find_same_title_siblings(
            "Maven submodule naming", "jvm", self.garden, "GE-20260514-zzzzzz"
        )
        self.assertIn("GE-20260514-aaaaaa", result)
        self.assertNotIn("GE-20260514-cccccc", result)


class TestVariantConsistencyPR(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = Path(self.tmp.name)
        self.domain = self.garden / "jvm"
        self.domain.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, stem: str, content: str) -> Path:
        path = self.domain / f"{stem}.md"
        path.write_text(content)
        return path

    def test_solo_convention_no_variant_passes(self):
        """Single convention entry with no sibling — no CRITICAL or variant WARNING."""
        path = self._write("GE-20260514-aaaaaa", CONVENTION_ENTRY_BASE)
        result = validate(str(path), str(self.garden))
        self.assertFalse(
            any("variant" in c.lower() for c in result['criticals']),
            f"Unexpected CRITICAL: {result['criticals']}"
        )
        orphan_warnings = [w for w in result['warnings'] if "variant" in w.lower()]
        self.assertEqual(orphan_warnings, [], f"Unexpected variant WARNING: {orphan_warnings}")

    def test_sibling_exists_no_variant_is_critical(self):
        """Convention entry + same-title sibling in domain, no variant: → CRITICAL."""
        self._write("GE-20260514-bbbbbb", CONVENTION_ENTRY_BASE)
        path = self._write("GE-20260514-aaaaaa", CONVENTION_ENTRY_BASE)
        result = validate(str(path), str(self.garden))
        self.assertTrue(
            any("variant" in c.lower() for c in result['criticals']),
            f"Expected CRITICAL about variant:, got: {result['criticals']}"
        )

    def test_sibling_exists_with_variant_passes(self):
        """Convention entry with variant: + sibling → no CRITICAL."""
        self._write("GE-20260514-bbbbbb", CONVENTION_ENTRY_BASE)
        path = self._write("GE-20260514-aaaaaa", CONVENTION_ENTRY_WITH_VARIANT)
        result = validate(str(path), str(self.garden))
        self.assertFalse(
            any("variant" in c.lower() for c in result['criticals']),
            f"Unexpected CRITICAL: {result['criticals']}"
        )

    def test_orphan_variant_no_sibling_is_warning(self):
        """Convention entry with variant: but no sibling → WARNING, not CRITICAL."""
        path = self._write("GE-20260514-aaaaaa", CONVENTION_ENTRY_WITH_VARIANT)
        result = validate(str(path), str(self.garden))
        self.assertFalse(
            any("variant" in c.lower() for c in result['criticals']),
            f"Unexpected CRITICAL: {result['criticals']}"
        )
        self.assertTrue(
            any("variant" in w.lower() for w in result['warnings']),
            f"Expected orphan-variant WARNING, got: {result['warnings']}"
        )

    def test_non_convention_same_title_sibling_is_warning_not_critical(self):
        """Non-convention type with same-title sibling → WARNING, no CRITICAL."""
        technique = CONVENTION_ENTRY_BASE.replace("type: convention", "type: technique")
        self._write("GE-20260514-bbbbbb", technique)
        path = self._write("GE-20260514-aaaaaa", technique)
        result = validate(str(path), str(self.garden))
        self.assertFalse(
            any("add 'variant:'" in c for c in result['criticals']),
            f"Unexpected CRITICAL: {result['criticals']}"
        )
        self.assertTrue(
            any("same title" in w.lower() for w in result['warnings']),
            f"Expected same-title WARNING, got: {result['warnings']}"
        )

    def test_convention_siblings_jaccard_warning_suppressed(self):
        """Convention entry with variant: + sibling → Jaccard 'possible duplicate' moved to info."""
        self._write("GE-20260514-bbbbbb", CONVENTION_ENTRY_BASE)
        path = self._write("GE-20260514-aaaaaa", CONVENTION_ENTRY_WITH_VARIANT)
        result = validate(str(path), str(self.garden))
        duplicate_warnings = [
            w for w in result['warnings']
            if "possible duplicate" in w and "GE-20260514-bbbbbb" in w
        ]
        self.assertEqual(
            duplicate_warnings, [],
            f"Expected no 'possible duplicate' warning for convention sibling, got: {duplicate_warnings}"
        )
        convention_infos = [i for i in result['infos'] if "convention sibling" in i]
        self.assertGreater(
            len(convention_infos), 0,
            f"Expected 'convention sibling' info, got infos: {result['infos']}"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_validate_pr.py::TestFindSameTitleSiblings tests/test_validate_pr.py::TestVariantConsistencyPR -v
```

Expected: all tests FAIL with `ImportError: cannot import name 'find_same_title_siblings'`.

- [ ] **Step 3: Add `find_same_title_siblings` to validate_pr.py**

In `scripts/validate_pr.py`, find the line `def validate(entry_path: str, garden_root: str = None, upstream_gardens: list = None) -> dict:` and insert the new function immediately before it:

```python
def find_same_title_siblings(title: str, domain: str, garden_root: Path, exclude_stem: str) -> list:
    """Return stems of GE-*.md files in domain whose title matches (case-sensitive)."""
    results = []
    domain_path = garden_root / domain
    if not domain_path.exists():
        return results
    for f in domain_path.glob('GE-*.md'):
        if f.stem == exclude_stem:
            continue
        try:
            fm, _, _ = parse_entry(f)
            if fm.get('title', '') == title:
                results.append(f.stem)
        except Exception:
            continue
    return results


```

- [ ] **Step 4: Add variant consistency check inside `validate()`**

In `scripts/validate_pr.py`, find the vocabulary check block (it ends with the last `result['warnings'].append(...)` inside the `if garden_root:` block). The full vocabulary block looks like:

```python
        # Vocabulary check
        labels_path = Path(garden_root) / 'labels'
        if labels_path.exists():
            known = {f.stem for f in labels_path.glob('*.md')}
            for tag in fm.get('tags', []):
                if tag not in known:
                    result['warnings'].append(
                        f"Tag '{tag}' not in controlled vocabulary (labels/)"
                    )
```

After that block (still inside `if garden_root:`), add:

```python
        # Variant: consistency check (type-gated on 'convention')
        _title = fm.get('title', '')
        _siblings = find_same_title_siblings(_title, domain, Path(garden_root), path.stem)
        _has_variant = 'variant' in fm
        if entry_type == 'convention':
            if _siblings and not _has_variant:
                result['criticals'].append(
                    f"Convention shares title {_title!r} with {', '.join(_siblings)}: "
                    f"add 'variant:' to distinguish this entry"
                )
            elif _has_variant and not _siblings:
                result['warnings'].append(
                    f"'variant:' is set but no sibling with title {_title!r} found in "
                    f"domain {domain!r} — verify title matches, or omit 'variant:'"
                )
            if _siblings and _has_variant:
                _sibling_set = set(_siblings)
                _updated_warnings = []
                for w in result['warnings']:
                    if 'possible duplicate' in w and any(f'with {s}:' in w for s in _sibling_set):
                        result['infos'].append(
                            w.replace('possible duplicate', 'convention sibling — expected overlap')
                        )
                    else:
                        _updated_warnings.append(w)
                result['warnings'] = _updated_warnings
        elif _siblings:
            result['warnings'].append(
                f"Same title as {', '.join(_siblings)} in domain {domain!r} — "
                f"verify this is intentional or use 'variant:' to distinguish"
            )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_validate_pr.py::TestFindSameTitleSiblings tests/test_validate_pr.py::TestVariantConsistencyPR -v
```

Expected: all tests PASS.

- [ ] **Step 6: Run full validate_pr test suite to check for regressions**

```bash
python3 -m pytest tests/test_validate_pr.py -v
```

Expected: all existing tests still PASS.

- [ ] **Step 7: Commit**

```bash
cd ~/claude/hortora/soredium
git add scripts/validate_pr.py tests/test_validate_pr.py
git commit -m "feat(validate_pr): add find_same_title_siblings + variant consistency check (soredium#44)"
```

---

### Task 3: Add check 8 (same-title variant consistency) to validate_garden.py

**Files:**
- Modify: `scripts/validate_garden.py`
- Test: `tests/test_validate_garden.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_validate_garden.py`. Add this import at the top if not already present (it should already be there):

```python
from pathlib import Path
from tempfile import TemporaryDirectory
```

Append this class and its helper:

```python
class TestVariantConsistencyGarden(unittest.TestCase):
    """Check 8: same-title entries in the same domain must all have variant:."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        GardenFixture(self.root)  # creates garden.db, submissions/, _index/

    def tearDown(self):
        self.tmp.cleanup()

    def _write_entry(self, ge_id: str, title: str, domain: str,
                     variant: str = None) -> Path:
        """Write a YAML-frontmatter entry, optionally with variant:."""
        domain_dir = self.root / domain
        domain_dir.mkdir(exist_ok=True)
        path = domain_dir / f"{ge_id}.md"
        lines = [
            "---",
            f"id: {ge_id}",
            f'title: "{title}"',
            "type: convention",
            f"domain: {domain}",
            'stack: "Test Stack"',
            "tags: [test]",
            "score: 9",
            "verified: true",
            "staleness_threshold: 3650",
            "submitted: 2026-05-14",
        ]
        if variant:
            lines.append(f'variant: "{variant}"')
        lines += ["---", "", f"## {title}", ""]
        path.write_text("\n".join(lines))
        return path

    def _garden_md(self, entries):
        """Write GARDEN.md with entries listed in By Technology section.

        entries = [(ge_id, title, domain), ...]
        get_by_technology_ids() requires content between '## By Technology\\n'
        and '\\n---', so we include a trailing '\\n---'.
        """
        last_id = entries[-1][0] if entries else "GE-20260514-000000"
        lines = [
            f"**Last assigned ID:** {last_id}",
            "**Last full DEDUPE sweep:** 2026-05-14",
            "**Entries merged since last sweep:** 0",
            "**Drift threshold:** 10",
            "",
            "## By Technology",
            "",
        ]
        for ge_id, title, domain in entries:
            lines.append(f"- {ge_id} [{title}]({domain}/{ge_id}.md)")
        lines += ["", "---", "", "## By Symptom / Type", "", "---", "", "## By Label", ""]
        (self.root / "GARDEN.md").write_text("\n".join(lines))

    def test_solo_convention_no_variant_passes(self):
        """Single convention entry with no sibling — no variant: required."""
        self._write_entry("GE-20260514-aaaaaa", "Maven submodule naming", "jvm")
        self._garden_md([("GE-20260514-aaaaaa", "Maven submodule naming", "jvm")])
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 0,
                         f"Expected clean garden:\n{result.stdout}\n{result.stderr}")

    def test_sibling_pair_both_have_variant_passes(self):
        """Two same-title entries in same domain, both with variant: → clean."""
        self._write_entry("GE-20260514-aaaaaa", "Maven submodule naming", "jvm",
                          variant="api/runtime/deployment — Quarkus style")
        self._write_entry("GE-20260514-bbbbbb", "Maven submodule naming", "jvm",
                          variant="core/web/persistence — Spring style")
        self._garden_md([
            ("GE-20260514-aaaaaa", "Maven submodule naming", "jvm"),
            ("GE-20260514-bbbbbb", "Maven submodule naming", "jvm"),
        ])
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 0,
                         f"Expected clean garden:\n{result.stdout}\n{result.stderr}")

    def test_sibling_missing_variant_is_error(self):
        """One of two same-title entries missing variant: → ERROR listing that GE-ID."""
        self._write_entry("GE-20260514-aaaaaa", "Maven submodule naming", "jvm",
                          variant="api/runtime/deployment — Quarkus style")
        self._write_entry("GE-20260514-bbbbbb", "Maven submodule naming", "jvm")
        self._garden_md([
            ("GE-20260514-aaaaaa", "Maven submodule naming", "jvm"),
            ("GE-20260514-bbbbbb", "Maven submodule naming", "jvm"),
        ])
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 1,
                         f"Expected error exit:\n{result.stdout}\n{result.stderr}")
        self.assertIn("GE-20260514-bbbbbb", result.stdout)
        self.assertIn("variant", result.stdout)

    def test_both_siblings_missing_variant_error_lists_both(self):
        """Both same-title entries missing variant: → ERROR listing both GE-IDs."""
        self._write_entry("GE-20260514-aaaaaa", "Maven submodule naming", "jvm")
        self._write_entry("GE-20260514-bbbbbb", "Maven submodule naming", "jvm")
        self._garden_md([
            ("GE-20260514-aaaaaa", "Maven submodule naming", "jvm"),
            ("GE-20260514-bbbbbb", "Maven submodule naming", "jvm"),
        ])
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 1,
                         f"Expected error exit:\n{result.stdout}\n{result.stderr}")
        self.assertIn("GE-20260514-aaaaaa", result.stdout)
        self.assertIn("GE-20260514-bbbbbb", result.stdout)

    def test_same_title_different_domains_not_grouped(self):
        """Same title in different domains — no relationship, no variant: required."""
        self._write_entry("GE-20260514-aaaaaa", "Maven submodule naming", "jvm")
        self._write_entry("GE-20260514-bbbbbb", "Maven submodule naming", "tools")
        self._garden_md([
            ("GE-20260514-aaaaaa", "Maven submodule naming", "jvm"),
            ("GE-20260514-bbbbbb", "Maven submodule naming", "tools"),
        ])
        result = run_validator(self.root)
        self.assertEqual(result.returncode, 0,
                         f"Expected clean garden:\n{result.stdout}\n{result.stderr}")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_validate_garden.py::TestVariantConsistencyGarden -v
```

Expected: `test_solo_convention_no_variant_passes`, `test_sibling_pair_both_have_variant_passes`, and `test_same_title_different_domains_not_grouped` PASS (check 8 doesn't exist yet so no spurious error). `test_sibling_missing_variant_is_error` and `test_both_siblings_missing_variant_error_lists_both` FAIL because they expect `returncode == 1` but currently get 0.

- [ ] **Step 3: Add `import yaml` to validate_garden.py**

In `scripts/validate_garden.py`, find the main module-level imports block (line ~199):

```python
import os
# Garden root: first non-flag positional argument, $HORTORA_GARDEN env var, or default
```

Insert before that block:

```python
try:
    import yaml as _yaml
except ImportError:
    _yaml = None

```

- [ ] **Step 4: Add check 8 to `validate()` in validate_garden.py**

In `scripts/validate_garden.py`, find the end of check 7 (the submissions check):

```python
    # 7. Check submissions have IDs
    if SUBMISSIONS_DIR.exists():
        sub_files = list(SUBMISSIONS_DIR.glob("*.md"))
        missing_id = [f.name for f in sub_files
                      if not re.search(r'\*\*Submission ID:\*\*', f.read_text())]
        if missing_id:
            log_warning(f"Submissions missing Submission ID header: {', '.join(missing_id)}")

    # Report
```

Insert the new check 8 between the check 7 block and the `# Report` comment:

```python
    # 8. Check variant: consistency for same-title entries
    if _yaml is None:
        log_warning("PyYAML not installed — skipping variant consistency check (pip install pyyaml)")
    else:
        from collections import defaultdict
        _title_groups: dict = defaultdict(list)   # (domain, title) -> [ge_ids]
        _variant_by_id: dict = {}                  # ge_id -> bool
        _vskip = {'GARDEN.md', 'CHECKED.md', 'DISCARDED.md'}
        for _vpath in GARDEN_ROOT.rglob('*.md'):
            if any(part in EXCLUDE_DIRS for part in _vpath.parts):
                continue
            if _vpath.name in _vskip:
                continue
            _vraw = _vpath.read_text(encoding='utf-8')
            if not _vraw.startswith('---'):
                continue
            _vfm_end = _vraw.find('\n---', 3)
            if _vfm_end < 0:
                continue
            try:
                _vfm = _yaml.safe_load(_vraw[3:_vfm_end]) or {}
            except Exception:
                continue
            _vge_id = _vfm.get('id')
            _vtitle = _vfm.get('title')
            _vdomain = _vfm.get('domain')
            if not _vge_id or not _vtitle or not _vdomain:
                continue
            _title_groups[(_vdomain, _vtitle)].append(_vge_id)
            _variant_by_id[_vge_id] = 'variant' in _vfm
        for (_vdomain, _vtitle), _vge_ids in _title_groups.items():
            if len(_vge_ids) > 1:
                _missing = [gid for gid in _vge_ids if not _variant_by_id.get(gid)]
                if _missing:
                    log_error(
                        f"Same-title entries in domain {_vdomain!r} share title {_vtitle!r} "
                        f"but lack 'variant:': {', '.join(sorted(_missing))}"
                    )

```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_validate_garden.py::TestVariantConsistencyGarden -v
```

Expected: all 5 tests PASS.

- [ ] **Step 6: Run full validate_garden test suite to check for regressions**

```bash
python3 -m pytest tests/test_validate_garden.py -v
```

Expected: all existing tests still PASS.

- [ ] **Step 7: Commit**

```bash
cd ~/claude/hortora/soredium
git add scripts/validate_garden.py tests/test_validate_garden.py
git commit -m "feat(validate_garden): add check 8 — same-title variant consistency (soredium#44)"
```

---

### Task 4: Update submission-formats.md

**Files:**
- Modify: `forage/submission-formats.md`

No TDD for documentation. Validate manually by reading the result.

- [ ] **Step 1: Add `variant:` to Optional Frontmatter Fields table**

In `forage/submission-formats.md`, find the last row of the Optional Frontmatter Fields table:

```
| `invalidation_triggers` | string or list | What changes would make this entry wrong. ...
```

After that row (before the closing blank line of the table), insert:

```
| `variant` | string | Distinguishes this entry from same-title alternatives in the same domain. Required when two or more entries share `title:` in the same domain. Omit for a solo entry with no known alternatives — add it (and add it to the existing sibling via REVISE) when a second entry for this title is submitted. Staleness: conventions use `staleness_threshold: 3650` (10 years); style choices change slowly. |
```

- [ ] **Step 2: Add Convention Template after the Undocumented template**

In `forage/submission-formats.md`, find the end of the Undocumented template section. It ends with:

```
### Caveats
Any limitations, version constraints, or risks from relying on undocumented behaviour.

*Score: N/15 · Included because: [why this belongs] · Reservation: [none / brief reason]*
```

Then there is `---` followed by `## Revise Template`. Insert the following Convention Template section between those two:

```markdown
---

## Convention Template

A deliberate style choice where alternatives exist and are equally valid. Not universally true — another project could legitimately choose a different style.

**Editorial bar:** Is this a deliberate style choice that another project could meaningfully adopt? Is there at least one known valid alternative?

**Staleness note:** Conventions use `staleness_threshold: 3650` (10 years). This intentionally overrides the discovery garden default of 730 — style conventions change slowly.

```markdown
---
id: GE-YYYYMMDD-xxxxxx
garden: discovery
title: "The decision space — e.g. Maven submodule naming"
variant: "This specific style — e.g. api/runtime/deployment (Quarkus extension)"
# Omit variant: if this is the only entry for this title in the domain.
# Add it (and REVISE the sibling to add its variant:) when a second entry is submitted.
type: convention
domain: jvm
stack: "Technology, Version"
tags: [tag1, tag2]
score: N
verified: true
staleness_threshold: 3650
submitted: YYYY-MM-DD
author: mdp
---

## [variant title — same as the variant: field above]

**Topic:** [title]
**Alternatives exist:** yes — see other entries with title `[title]`

Note: convention entries use the variant as the H1 (not the title) so that two entries
for the same topic have distinguishable headings.

### The convention
Concrete description. What to name/structure/configure and how.

### Why this style
What problem does it solve? What does it optimise for?

### Trade-offs
What does this make harder? When would you choose a different style?

### When not to use it
Conditions where an alternative convention is better.

*Score: N/15 · Included because: [why this convention is worth recording] · Reservation: [none / brief reason]*
```

```

- [ ] **Step 3: Commit**

```bash
cd ~/claude/hortora/soredium
git add forage/submission-formats.md
git commit -m "docs(submission-formats): add variant: field and Convention Template (soredium#44)"
```

---

### Task 5: Update forage/SKILL.md (11 enumeration sites + new content)

**Files:**
- Modify: `forage/SKILL.md`

Apply all edits in order. Each is a surgical find-and-replace.

- [ ] **Step 1: Update intro — "three kinds" → "four kinds" + convention bullet**

Find:
```
A cross-project, machine-wide library of hard-won technical knowledge —
three kinds of entries:

- **Gotchas** — bugs that silently fail, behaviours that contradict documentation, and workarounds that took hours to find
- **Techniques** — the umbrella for all non-obvious positive knowledge: specific how-to methods, strategic design philosophy, cross-cutting patterns. A skilled developer wouldn't naturally reach for it, but would immediately value it once shown.
- **Undocumented** — behaviours, options, or features that exist and work but simply aren't written down anywhere; only discoverable via source code, trial and error, or word of mouth
```

Replace with:
```
A cross-project, machine-wide library of hard-won technical knowledge —
four kinds of entries:

- **Gotchas** — bugs that silently fail, behaviours that contradict documentation, and workarounds that took hours to find
- **Techniques** — the umbrella for all non-obvious positive knowledge: specific how-to methods, strategic design philosophy, cross-cutting patterns. A skilled developer wouldn't naturally reach for it, but would immediately value it once shown.
- **Undocumented** — behaviours, options, or features that exist and work but simply aren't written down anywhere; only discoverable via source code, trial and error, or word of mouth
- **Conventions** — deliberate style choices where alternatives exist and are equally valid (e.g. Maven submodule naming: `api/runtime/deployment` vs `core/web/persistence`). Not universally true — another project could legitimately choose differently.
```

- [ ] **Step 2: Add "The bar for conventions" after the existing bar lines**

Find:
```
**The bar for undocumented:** Does it exist, does it work, and would you have no reasonable way to discover it from the official docs? If yes — it belongs.
```

Replace with:
```
**The bar for undocumented:** Does it exist, does it work, and would you have no reasonable way to discover it from the official docs? If yes — it belongs.

**The bar for conventions:** Is this a deliberate style choice that another project could meaningfully adopt? Is there at least one known valid alternative? If yes — it belongs. Convention entries typically score lower on Pain/Impact and Non-obviousness than gotchas — a score of 6–9 is expected for a well-articulated convention. Apply the editorial bar rather than the score gate mechanically.
```

- [ ] **Step 3: Update entry format block type field**

Find:
```
type: gotcha | technique | undocumented
```

Replace with:
```
type: gotcha | technique | undocumented | convention
```

- [ ] **Step 4: Update Step 1 classification to include convention**

Find:
```
Classify the type: **gotcha**, **technique**, or **undocumented**.
```

Replace with:
```
Classify the type: **gotcha**, **technique**, **undocumented**, or **convention**.

**Convention:** A deliberate style choice where alternatives exist and are equally valid. Not universally true — another project could legitimately choose a different style. Examples: naming schemes, module structures, config strategy choices. If same-title alternatives will exist, each entry carries `variant:`. Solo convention entries (first of their title) omit `variant:` and add it via REVISE when a second entry is submitted.
```

- [ ] **Step 5: Update Step 4 garden table — discovery row description**

Find:
```
| Non-obvious behaviour, silent failure, undocumented feature | `discovery` |
```

Replace with:
```
| Non-obvious behaviour, silent failure, undocumented feature, or deliberate style choice with known alternatives | `discovery` |
```

- [ ] **Step 6: Update Step 4 editorial bar — discovery row**

Find:
```
| `discovery` | Would a skilled developer familiar with the technology still have spent significant time on this? |
```

Replace with:
```
| `discovery` | Gotcha/technique/undocumented: Would a skilled developer familiar with the technology still have spent significant time on this? Convention: Is this a deliberate style choice another project could meaningfully adopt, with at least one known valid alternative? |
```

- [ ] **Step 7: Insert SWEEP Step 4 (Convention scan) and renumber steps 4→5, 5→6, 6→7**

Find the SWEEP section's Step 4 header:
```
**Step 4 — Submit confirmed entries (batched delivery)**
```

Replace it (and only the header line) with:
```
**Step 4 — Scan for Conventions** (deliberate style choices with known alternatives)

Review the session for:
- Naming or structuring decisions made deliberately where a different valid choice existed
- Patterns adopted as a team/project style that another project could consciously adopt or reject
- Moments where alternatives were compared and one was chosen for explicit reasons

For each candidate, compute the Garden Score then present:
*"We chose [X] for [concern] — an alternative is [Y]. Scored [N]/15 — worth submitting as a convention entry?"*

**Step 5 — Submit confirmed entries (batched delivery)**
```

Then find (now it's Step 5):
```
**Step 5 — Staleness spot-check (domain-filtered)**
```
Replace with:
```
**Step 6 — Staleness spot-check (domain-filtered)**
```

Then find:
```
**Step 6 — Report**
```
Replace with:
```
**Step 7 — Report**
```

- [ ] **Step 8: Update SWEEP header and intro — "three" → "four"**

Find:
```
### SWEEP (scan the current session for all three entry types)

Use when: "sweep", "garden sweep", "scan for garden entries", or at the end of a session.

Unlike CAPTURE (where you provide the specific knowledge), SWEEP reviews the session from conversation memory and proposes findings. It covers all three categories explicitly.
```

Replace with:
```
### SWEEP (scan the current session for all four entry types)

Use when: "sweep", "garden sweep", "scan for garden entries", or at the end of a session.

Unlike CAPTURE (where you provide the specific knowledge), SWEEP reviews the session from conversation memory and proposes findings. It covers all four categories explicitly.
```

- [ ] **Step 9: Update SWEEP report line — "undocumented items" → add conventions**

Find:
```
- If nothing was found: "Nothing garden-worthy surfaced in this session across gotchas, techniques, or undocumented items."
```

Replace with:
```
- If nothing was found: "Nothing garden-worthy surfaced in this session across gotchas, techniques, undocumented items, or conventions."
```

- [ ] **Step 10: Add Proactive Trigger for conventions**

Find:
```
**Also fire for REVISE** when a solution surfaces for a previously-unsolved gotcha:
> "This looks like a solution to an existing garden entry — want me to submit a REVISE to enrich '[entry title]' with the fix?"
```

Replace with:
```
**Also fire for REVISE** when a solution surfaces for a previously-unsolved gotcha:
> "This looks like a solution to an existing garden entry — want me to submit a REVISE to enrich '[entry title]' with the fix?"

**For conventions:** a naming or structural choice was discussed with alternatives considered. User says "we always do it this way", "we chose X over Y", "that's our style for this".

Offer, don't assume:
> "That looks like a deliberate style choice — want me to record it as a convention entry in the garden?"
```

- [ ] **Step 11: Update Proactive Trigger offer line — add convention**

Find:
```
> "This was non-obvious — want me to submit it to the garden as a [gotcha / technique / undocumented]?"
```

Replace with:
```
> "This was non-obvious — want me to submit it to the garden as a [gotcha / technique / undocumented / convention]?"
```

- [ ] **Step 12: Update Common Pitfalls — SWEEP row**

Find:
```
| SWEEP: only checking gotchas | Techniques and undocumented items are easy to miss | Always check all three categories explicitly |
```

Replace with:
```
| SWEEP: only checking gotchas | Techniques, undocumented items, and conventions are easy to miss | Always check all four categories explicitly |
```

- [ ] **Step 13: Update Common Pitfalls — CAPTURE type list**

Find:
```
| CAPTURE: using gotcha/technique/undocumented in non-discovery garden | Type vocabulary is per-garden | patterns uses architectural/migration/integration/testing; examples uses code |
```

Replace with:
```
| CAPTURE: using gotcha/technique/undocumented/convention in non-discovery garden | Type vocabulary is per-garden | patterns uses architectural/migration/integration/testing; examples uses code; convention belongs in discovery |
```

- [ ] **Step 14: Update SWEEP success criterion — "three" → "four"**

Find:
```
- ✅ All three categories checked from session memory
```

Replace with:
```
- ✅ All four categories checked from session memory (gotchas, techniques, undocumented, conventions)
```

- [ ] **Step 15: Commit**

```bash
cd ~/claude/hortora/soredium
git add forage/SKILL.md
git commit -m "docs(forage): add convention type to SKILL.md — all 11 enumeration sites + SWEEP Step 4 (soredium#44)"
```

---

### Task 6: Run full test suite + sync-local

- [ ] **Step 1: Run full test suite**

```bash
cd ~/claude/hortora/soredium
python3 -m pytest tests/ -v
```

Expected: all 836+ tests PASS (new tests bring the total higher). Zero failures.

- [ ] **Step 2: Run validate_pr.py against the six pending convention entries in the garden**

These entries are waiting at `~/.hortora/garden/jvm/` and similar locations. List them:

```bash
GARDEN="${HORTORA_GARDEN:-$HOME/.hortora/garden}"
git -C "$GARDEN" ls-files --others --exclude-standard | grep "GE-"
```

For each pending convention entry, run:

```bash
python3 ~/claude/hortora/soredium/scripts/validate_pr.py \
  "$GARDEN/<domain>/<ge-id>.md" "$GARDEN"
```

Expected: no CRITICALs (solo entries with no sibling should pass; variant: warnings are expected if any were written with variant: before siblings exist).

- [ ] **Step 3: Sync skills to installed location**

```bash
cd ~/claude/hortora/soredium
sync-local
```

This propagates `forage/SKILL.md` and `forage/submission-formats.md` changes to `~/.claude/skills/forage/`.

- [ ] **Step 4: Smoke-test the installed skill**

Open a new Claude Code session and invoke:
```
/forage CAPTURE
```

Verify that Step 1 mentions "convention" as a fourth type alongside gotcha, technique, undocumented.

---

## Self-Review

**Spec coverage check:**

| Spec section | Task |
|---|---|
| Add `convention` to `discovery.valid_types` | Task 1, Step 3 |
| `find_same_title_siblings` | Task 2, Step 3 |
| Sibling + no `variant:` → CRITICAL (convention only) | Task 2, Step 4 |
| `variant:` + no sibling → WARNING | Task 2, Step 4 |
| Non-convention same-title sibling → WARNING only | Task 2, Step 4 |
| Jaccard suppression for confirmed convention siblings | Task 2, Step 4 |
| `import yaml` in validate_garden.py | Task 3, Step 3 |
| Check 8 — same-title variant consistency (ERROR) | Task 3, Step 4 |
| Same domain required for grouping | Task 3 tests (test_same_title_different_domains) |
| `variant:` in Optional Frontmatter Fields table | Task 4, Step 1 |
| Convention Template in submission-formats.md | Task 4, Step 2 |
| `staleness_threshold: 3650` note + divergence from 730 | Task 4, Step 2 |
| Conditional `variant:` note in template | Task 4, Step 2 |
| Score footer line in convention template | Task 4, Step 2 |
| "four kinds" intro | Task 5, Step 1 |
| "The bar for conventions" | Task 5, Step 2 |
| Entry format block type field | Task 5, Step 3 |
| Step 1 classification + convention definition | Task 5, Step 4 |
| Step 4 discovery row description | Task 5, Step 5 |
| Step 4 editorial bar | Task 5, Step 6 |
| SWEEP Step 4 — convention scan | Task 5, Step 7 |
| SWEEP steps renumbered 4→5, 5→6, 6→7 | Task 5, Step 7 |
| SWEEP "all four entry types" | Task 5, Step 8 |
| SWEEP report "nothing found" line | Task 5, Step 9 |
| Proactive Trigger for conventions | Task 5, Step 10 |
| Proactive offer line | Task 5, Step 11 |
| Common Pitfalls — SWEEP row | Task 5, Step 12 |
| Common Pitfalls — CAPTURE type list | Task 5, Step 13 |
| SWEEP success criterion | Task 5, Step 14 |
| Scoring note for conventions (low Pain/Impact expected) | Task 5, Step 2 (bar for conventions para) |
| Full test suite green | Task 6, Step 1 |
| sync-local to propagate skill changes | Task 6, Step 3 |

All spec requirements are covered.
