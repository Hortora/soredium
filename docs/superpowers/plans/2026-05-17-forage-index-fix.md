# forage Index Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `integrate_entry.py` into forage CAPTURE Step 8 and SWEEP Step 5 Deliver so that all garden indexes are updated on every submission.

**Architecture:** Add `--skip-validate` and `--skip-commit` flags to `integrate_entry.py`, making it composable. CAPTURE stages the entry file then calls `integrate_entry.py --skip-validate` (one commit, entry + indexes). SWEEP calls `integrate_entry.py --skip-validate --skip-commit` per entry (indexes on disk only), then issues one batch commit. Validation already happens in Step 7; `integrate_entry.py` is the single integration point.

**Tech Stack:** Python 3, pytest, unittest.mock, subprocess, GitGarden fixture (`tests/garden_fixture.py`)

**Issue:** Hortora/soredium#54
**Epic:** epic-forage-index-fix
**Spec:** `docs/superpowers/specs/2026-05-17-forage-index-fix-design.md`

---

## File Map

| File | Action | What changes |
|------|--------|-------------|
| `scripts/integrate_entry.py` | Modify | Add `skip_validate`/`skip_commit` params to `integrate()`, add CLI flags to `main()` |
| `tests/test_integrate_entry.py` | Modify | Add `TestSkipFlags` class (7 unit tests) |
| `tests/test_integration.py` | Modify | Add `TestCaptureDeliverFlow` and `TestSweepDeliverFlow` classes (5 integration tests) |
| `forage/SKILL.md` | Modify | Update CAPTURE Step 8 and SWEEP Step 5 Deliver |

---

## Task 1: Write failing unit tests for `--skip-validate` / `--skip-commit`

**Files:**
- Modify: `tests/test_integrate_entry.py`

Append a new `TestSkipFlags` class after the existing `TestEntriesIndexIntegration` class. These tests call `integrate()` with the new keyword arguments that don't exist yet — they will fail with `TypeError`.

- [ ] **Step 1: Append `TestSkipFlags` to `tests/test_integrate_entry.py`**

Add the following imports at the top of the file (after existing imports):

```python
import json
import subprocess
from tempfile import TemporaryDirectory
```

Then append this class at the end of the file:

```python
INTEGRATE_SCRIPT = Path(__file__).parent.parent / 'scripts' / 'integrate_entry.py'


class TestSkipFlags:
    """Tests for --skip-validate and --skip-commit flags on integrate()."""

    def test_no_flags_calls_both(self, garden, entry):
        with patch('integrate_entry.run_validate') as mock_validate, \
             patch('integrate_entry.git_commit') as mock_commit:
            integrate(str(entry), str(garden))
        mock_validate.assert_called_once()
        mock_commit.assert_called_once()

    def test_skip_validate_only(self, garden, entry):
        with patch('integrate_entry.run_validate') as mock_validate, \
             patch('integrate_entry.git_commit') as mock_commit:
            integrate(str(entry), str(garden), skip_validate=True)
        mock_validate.assert_not_called()
        mock_commit.assert_called_once()

    def test_skip_commit_only(self, garden, entry):
        with patch('integrate_entry.run_validate') as mock_validate, \
             patch('integrate_entry.git_commit') as mock_commit:
            integrate(str(entry), str(garden), skip_commit=True)
        mock_validate.assert_called_once()
        mock_commit.assert_not_called()

    def test_both_flags_skip_both(self, garden, entry):
        with patch('integrate_entry.run_validate') as mock_validate, \
             patch('integrate_entry.git_commit') as mock_commit:
            integrate(str(entry), str(garden), skip_validate=True, skip_commit=True)
        mock_validate.assert_not_called()
        mock_commit.assert_not_called()

    def test_skip_commit_still_updates_indexes(self, tmp_path):
        garden = _garden_with_drift(tmp_path, drift=0)
        entry = garden / 'quarkus' / 'cdi' / 'GE-0123.md'
        entry.write_text(VALID_ENTRY)
        with patch('integrate_entry.run_validate'), \
             patch('integrate_entry.git_commit'):
            integrate(str(entry), str(garden), skip_commit=True)
        assert (garden / '_summaries' / 'quarkus' / 'cdi' / 'GE-0123.md').exists()
        assert 'GE-0123' in (garden / 'quarkus' / 'cdi' / 'INDEX.md').read_text()
        assert (garden / 'labels' / 'quarkus.md').exists()
        content = (garden / 'GARDEN.md').read_text()
        assert re.search(r'\*\*Entries merged since last sweep:\*\*\s*1', content)

    def test_cli_both_skip_flags_exits_0(self, tmp_path):
        """Both flags together: CLI exits 0 and returns valid JSON (no git needed)."""
        garden = _garden_with_drift(tmp_path, drift=0)
        entry = garden / 'quarkus' / 'cdi' / 'GE-0123.md'
        entry.write_text(VALID_ENTRY)
        result = subprocess.run(
            [sys.executable, str(INTEGRATE_SCRIPT),
             str(entry), str(garden), '--skip-validate', '--skip-commit'],
            capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data == {'status': 'ok', 'ge_id': 'GE-0123', 'domain': 'quarkus/cdi'}

    def test_cli_skip_validate_flag_accepted(self, tmp_path):
        """--skip-validate is accepted by argparse (exit != 2 means not an argparse error)."""
        result = subprocess.run(
            [sys.executable, str(INTEGRATE_SCRIPT), '/nonexistent.md', '--skip-validate'],
            capture_output=True, text=True
        )
        assert result.returncode != 2, f"argparse rejected --skip-validate: {result.stderr}"

    def test_cli_skip_commit_flag_accepted(self, tmp_path):
        """--skip-commit is accepted by argparse (exit != 2 means not an argparse error)."""
        result = subprocess.run(
            [sys.executable, str(INTEGRATE_SCRIPT), '/nonexistent.md', '--skip-commit'],
            capture_output=True, text=True
        )
        assert result.returncode != 2, f"argparse rejected --skip-commit: {result.stderr}"
```

- [ ] **Step 2: Run the new tests to confirm they fail**

```bash
cd /path/to/soredium
python -m pytest tests/test_integrate_entry.py::TestSkipFlags -v 2>&1 | head -40
```

Expected: All 7 tests FAIL with `TypeError: integrate() got an unexpected keyword argument 'skip_validate'` (or similar). The CLI flag tests may fail with argparse error exit 2.

---

## Task 2: Implement `skip_validate` and `skip_commit` in `integrate_entry.py`

**Files:**
- Modify: `scripts/integrate_entry.py`

Two changes: (1) add parameters to `integrate()`, (2) replace `main()` with argparse-based version.

- [ ] **Step 1: Update `integrate()` signature and body**

Replace the current `integrate()` function:

```python
def integrate(entry_path: str, garden_root: str = None) -> dict:
    path = Path(entry_path)
    garden = Path(garden_root) if garden_root else path.parent.parent
    fm, _ = parse_entry(path)
    domain = fm.get('domain', '')
    ge_id = fm.get('id') or path.stem  # frontmatter id wins; filename stem is fallback only

    update_summaries(domain, ge_id, fm, garden)
    update_domain_index(domain, ge_id, fm, garden)
    update_labels(fm, ge_id, garden)
    update_global_index(domain, garden)
    increment_drift_counter(garden)
    upsert_entry_index(garden, path, domain)
    run_validate(garden)
    git_commit(garden, ge_id)

    return {'status': 'ok', 'ge_id': ge_id, 'domain': domain}
```

With:

```python
def integrate(entry_path: str, garden_root: str = None,
              skip_validate: bool = False, skip_commit: bool = False) -> dict:
    path = Path(entry_path)
    garden = Path(garden_root) if garden_root else path.parent.parent
    fm, _ = parse_entry(path)
    domain = fm.get('domain', '')
    ge_id = fm.get('id') or path.stem  # frontmatter id wins; filename stem is fallback only

    update_summaries(domain, ge_id, fm, garden)
    update_domain_index(domain, ge_id, fm, garden)
    update_labels(fm, ge_id, garden)
    update_global_index(domain, garden)
    increment_drift_counter(garden)
    upsert_entry_index(garden, path, domain)
    if not skip_validate:
        run_validate(garden)
    if not skip_commit:
        git_commit(garden, ge_id)

    return {'status': 'ok', 'ge_id': ge_id, 'domain': domain}
```

- [ ] **Step 2: Replace `main()` with argparse version**

Replace the current `main()` function:

```python
def main():
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'Usage: integrate_entry.py <entry_file> [garden_root]'}))
        sys.exit(1)
    result = integrate(
        sys.argv[1],
        sys.argv[2] if len(sys.argv) > 2 else None,
    )
    print(json.dumps(result, indent=2))
```

With:

```python
def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='Update all garden indexes after an entry is submitted.'
    )
    parser.add_argument('entry_file', help='Path to the garden entry file')
    parser.add_argument('garden_root', nargs='?',
                        help='Path to the garden root (default: parent.parent of entry_file)')
    parser.add_argument('--skip-validate', action='store_true',
                        help='Skip structural validation (already done by validate_pr.py)')
    parser.add_argument('--skip-commit', action='store_true',
                        help='Update indexes on disk without committing (caller handles commit)')
    args = parser.parse_args()
    result = integrate(
        args.entry_file,
        args.garden_root,
        skip_validate=args.skip_validate,
        skip_commit=args.skip_commit,
    )
    print(json.dumps(result, indent=2))
```

- [ ] **Step 3: Run unit tests to confirm all 7 pass**

```bash
python -m pytest tests/test_integrate_entry.py::TestSkipFlags -v
```

Expected: All 7 PASS.

- [ ] **Step 4: Run full existing test suite to confirm no regressions**

```bash
python -m pytest tests/test_integrate_entry.py -v
```

Expected: All existing tests still PASS (backwards-compatible — no flags = original behaviour).

- [ ] **Step 5: Commit**

```bash
git -C /path/to/soredium add scripts/integrate_entry.py tests/test_integrate_entry.py
git -C /path/to/soredium commit -m "feat(integrate_entry): add --skip-validate and --skip-commit flags — Refs #54"
```

---

## Task 3: Write CAPTURE integration tests

**Files:**
- Modify: `tests/test_integration.py`

Add `TestCaptureDeliverFlow` using `GitGarden` (real git repo, no mocks). These tests verify that staging the entry then calling `integrate(skip_validate=True)` produces a single commit containing both the entry file and all index updates.

- [ ] **Step 1: Add imports to `test_integration.py`**

At the top of `test_integration.py`, after the existing imports, add:

```python
import sys as _sys2
_sys2.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from integrate_entry import integrate as _integrate_direct
```

(The file already imports `_integrate` via a different path at the bottom — use `_integrate_direct` to avoid collision.)

- [ ] **Step 2: Append `TestCaptureDeliverFlow` at the end of `test_integration.py`**

```python
_CAPTURE_ENTRY = textwrap.dedent("""\
    ---
    id: GE-20260517-cap001
    title: "CAPTURE flow integration test entry"
    type: gotcha
    domain: python
    score: 10
    tags: [python, testing, integration]
    submitted: 2026-05-17
    staleness_threshold: 730
    ---

    ## CAPTURE flow integration test entry

    **ID:** GE-20260517-cap001
    **Stack:** Python (all versions)
    **Symptom:** Test symptom for CAPTURE flow.
    **Context:** Integration test only.

    ### Root cause
    Integration test root cause.

    ### Fix
    Integration test fix.

    ### Why this is non-obvious
    Used only in integration tests.

    *Score: 10/15 · Included because: test coverage · Reservation: none*
""")


class TestCaptureDeliverFlow(unittest.TestCase):
    """
    Integration tests for the revised CAPTURE Step 8 deliver flow.

    Verifies that staging an entry file then calling integrate(skip_validate=True)
    produces a single commit containing both the entry and all index files.
    Uses a real git repository — no mocks.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = GitGarden(Path(self.tmp.name))
        self.garden.init_garden("GE-0100")
        domain = self.garden.root / 'python'
        domain.mkdir()
        (domain / 'INDEX.md').write_text(
            '| GE-ID | Title | Type | Score |\n|-------|-------|------|-------|\n'
        )
        (self.garden.root / '_index').mkdir()
        (self.garden.root / '_index' / 'global.md').write_text(
            '| Domain | Index |\n|--------|-------|\n'
        )
        self.garden.commit_all("init: add python domain")

    def tearDown(self):
        self.tmp.cleanup()

    def test_entry_and_indexes_land_in_same_commit(self):
        """Stage entry → integrate(skip_validate=True) → one commit with entry + all index files."""
        entry = self.garden.root / 'python' / 'GE-20260517-cap001.md'
        entry.write_text(_CAPTURE_ENTRY)

        git(self.garden.root, 'add', str(entry))
        _integrate_direct(str(entry), str(self.garden.root), skip_validate=True)

        show = git_out(self.garden.root, 'show', '--name-only', 'HEAD')
        self.assertIn('python/GE-20260517-cap001.md', show)
        self.assertIn('python/INDEX.md', show)
        self.assertIn('GARDEN.md', show)
        self.assertIn('GE-20260517-cap001', show)  # _summaries entry

    def test_drift_counter_incremented_by_one(self):
        """CAPTURE integration increments GARDEN.md drift counter by 1."""
        entry = self.garden.root / 'python' / 'GE-20260517-cap001.md'
        entry.write_text(_CAPTURE_ENTRY)
        git(self.garden.root, 'add', str(entry))
        _integrate_direct(str(entry), str(self.garden.root), skip_validate=True)

        content = (self.garden.root / 'GARDEN.md').read_text()
        m = re.search(r'\*\*Entries merged since last sweep:\*\*\s*(\d+)', content)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), 1)
```

- [ ] **Step 3: Run the new CAPTURE tests to confirm they pass**

```bash
python -m pytest tests/test_integration.py::TestCaptureDeliverFlow -v
```

Expected: Both PASS (implementation from Task 2 is already in place).

- [ ] **Step 4: Commit**

```bash
git -C /path/to/soredium add tests/test_integration.py
git -C /path/to/soredium commit -m "test: add CAPTURE deliver flow integration tests — Refs #54"
```

---

## Task 4: Write SWEEP integration tests

**Files:**
- Modify: `tests/test_integration.py`

Add `TestSweepDeliverFlow` verifying that calling `integrate(skip_validate=True, skip_commit=True)` per entry then doing one batch commit produces a single commit with all entries + index updates.

- [ ] **Step 1: Append `TestSweepDeliverFlow` at the end of `test_integration.py`**

```python
_SWEEP_ENTRY_A = textwrap.dedent("""\
    ---
    id: GE-20260517-sw0001
    title: "SWEEP batch test entry A"
    type: gotcha
    domain: python
    score: 10
    tags: [python, sweep, batch]
    submitted: 2026-05-17
    staleness_threshold: 730
    ---

    Body A.
""")

_SWEEP_ENTRY_B = textwrap.dedent("""\
    ---
    id: GE-20260517-sw0002
    title: "SWEEP batch test entry B"
    type: technique
    domain: python
    score: 11
    tags: [python, testing]
    submitted: 2026-05-17
    staleness_threshold: 730
    ---

    Body B.
""")

_SWEEP_ENTRY_C = textwrap.dedent("""\
    ---
    id: GE-20260517-sw0003
    title: "SWEEP batch test entry C"
    type: gotcha
    domain: tools
    score: 9
    tags: [tools, git]
    submitted: 2026-05-17
    staleness_threshold: 730
    ---

    Body C.
""")


class TestSweepDeliverFlow(unittest.TestCase):
    """
    Integration tests for the revised SWEEP Step 5 batch deliver flow.

    Verifies that calling integrate(skip_validate=True, skip_commit=True) per entry
    then issuing one batch commit preserves the single-commit sweep behaviour while
    keeping all indexes current.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = GitGarden(Path(self.tmp.name))
        self.garden.init_garden("GE-0100")
        for domain in ['python', 'tools']:
            d = self.garden.root / domain
            d.mkdir()
            (d / 'INDEX.md').write_text(
                '| GE-ID | Title | Type | Score |\n|-------|-------|------|-------|\n'
            )
        (self.garden.root / '_index').mkdir()
        (self.garden.root / '_index' / 'global.md').write_text(
            '| Domain | Index |\n|--------|-------|\n'
        )
        self.garden.commit_all("init: add python and tools domains")

    def tearDown(self):
        self.tmp.cleanup()

    def test_sweep_produces_single_batch_commit(self):
        """3 entries → integrate(skip_validate, skip_commit) × 3 → exactly 1 new commit."""
        path_a = self.garden.root / 'python' / 'GE-20260517-sw0001.md'
        path_b = self.garden.root / 'python' / 'GE-20260517-sw0002.md'
        path_c = self.garden.root / 'tools' / 'GE-20260517-sw0003.md'
        path_a.write_text(_SWEEP_ENTRY_A)
        path_b.write_text(_SWEEP_ENTRY_B)
        path_c.write_text(_SWEEP_ENTRY_C)

        sha_before = self.garden.head_sha()

        for path in [path_a, path_b, path_c]:
            _integrate_direct(str(path), str(self.garden.root),
                              skip_validate=True, skip_commit=True)

        # Single batch commit (as SWEEP Step 5 does)
        git(self.garden.root, 'add',
            str(path_a), str(path_b), str(path_c),
            '_summaries/', '_index/', 'labels/', 'GARDEN.md')
        git(self.garden.root, 'add', '--update')
        git(self.garden.root, 'commit', '-m',
            'sweep: 3 entries — sweep-batch-a, sweep-batch-b, sweep-batch-c')

        # Exactly 1 new commit (not 3)
        log = git_out(self.garden.root, 'log', '--oneline',
                      f'{sha_before}..HEAD')
        self.assertEqual(len(log.strip().splitlines()), 1)

        show = git_out(self.garden.root, 'show', '--name-only', 'HEAD')
        self.assertIn('python/GE-20260517-sw0001.md', show)
        self.assertIn('python/GE-20260517-sw0002.md', show)
        self.assertIn('tools/GE-20260517-sw0003.md', show)
        self.assertIn('python/INDEX.md', show)
        self.assertIn('tools/INDEX.md', show)
        self.assertIn('GARDEN.md', show)

    def test_drift_counter_incremented_by_three(self):
        """SWEEP of 3 entries increments GARDEN.md drift counter by 3."""
        for path, entry in [
            (self.garden.root / 'python' / 'GE-20260517-sw0001.md', _SWEEP_ENTRY_A),
            (self.garden.root / 'python' / 'GE-20260517-sw0002.md', _SWEEP_ENTRY_B),
            (self.garden.root / 'tools' / 'GE-20260517-sw0003.md', _SWEEP_ENTRY_C),
        ]:
            path.write_text(entry)
            _integrate_direct(str(path), str(self.garden.root),
                              skip_validate=True, skip_commit=True)

        content = (self.garden.root / 'GARDEN.md').read_text()
        m = re.search(r'\*\*Entries merged since last sweep:\*\*\s*(\d+)', content)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), 3)

    def test_mixed_domain_both_index_files_updated(self):
        """Entries in python/ and tools/ both get their INDEX.md updated before commit."""
        path_a = self.garden.root / 'python' / 'GE-20260517-sw0001.md'
        path_c = self.garden.root / 'tools' / 'GE-20260517-sw0003.md'
        path_a.write_text(_SWEEP_ENTRY_A)
        path_c.write_text(_SWEEP_ENTRY_C)

        _integrate_direct(str(path_a), str(self.garden.root),
                          skip_validate=True, skip_commit=True)
        _integrate_direct(str(path_c), str(self.garden.root),
                          skip_validate=True, skip_commit=True)

        self.assertIn('GE-20260517-sw0001',
                      (self.garden.root / 'python' / 'INDEX.md').read_text())
        self.assertIn('GE-20260517-sw0003',
                      (self.garden.root / 'tools' / 'INDEX.md').read_text())
```

- [ ] **Step 2: Run the SWEEP tests to confirm they pass**

```bash
python -m pytest tests/test_integration.py::TestSweepDeliverFlow -v
```

Expected: All 3 PASS.

- [ ] **Step 3: Run full integration test suite for regressions**

```bash
python -m pytest tests/test_integration.py -v
```

Expected: All existing tests still PASS.

- [ ] **Step 4: Commit**

```bash
git -C /path/to/soredium add tests/test_integration.py
git -C /path/to/soredium commit -m "test: add SWEEP batch deliver flow integration tests — Refs #54"
```

---

## Task 5: Update forage SKILL.md — CAPTURE Step 8

**Files:**
- Modify: `forage/SKILL.md`

Replace the manual `git add/commit` block in Step 8 with the `integrate_entry.py --skip-validate` call.

- [ ] **Step 1: Replace Step 8 in `forage/SKILL.md`**

Find the block starting with `**Step 8 — Deliver**` and ending before `**Step 9 — Check for other untracked entries**`. Replace with:

```markdown
**Step 8 — Deliver**

**Resolve the garden path first** — evaluate `HORTORA_GARDEN` env var once, fall back to
`~/.hortora/garden`. Use the **concrete resolved path** in every subsequent command.
Never assign `GARDEN=...` inside a Bash block — that triggers shell expansion prompts.

**Use the soredium path resolved in Step 7** (`SOREDIUM_PATH` env var, or the path used
for `validate_pr.py`).

Detect the garden's remote (replace `/concrete/garden` and `/concrete/soredium` with resolved paths):
```bash
git -C /concrete/garden remote get-url origin 2>/dev/null
```

Stage the entry file, then run integration (validation already done in Step 7 — skip it here):
```bash
git -C /concrete/garden add <domain>/$GE_ID.md
python3 /concrete/soredium/scripts/integrate_entry.py \
  /concrete/garden/<domain>/$GE_ID.md \
  /concrete/garden \
  --skip-validate
```

`integrate_entry.py` updates all indexes (`_summaries/`, domain `INDEX.md`, `labels/`,
`_index/global.md`, `GARDEN.md` drift counter, `garden.db`) and commits the entry file
plus all index changes in a single commit. Commit message: `index: integrate <GE_ID>`.

**If the URL contains `github.com`** → pull and push:
```bash
git -C /concrete/garden pull --rebase origin main
git -C /concrete/garden push origin main
```
```

- [ ] **Step 2: Verify REVISE Step 5 reference is still accurate**

REVISE Step 5 says: *"Then deliver the same way as CAPTURE Step 8: PR (GitHub remote) or direct commit to main (local)."*

For REVISE, the entry file is a modification of an existing tracked file (not a new file), so `git add --update` inside `integrate_entry.py` will pick it up automatically. The pre-stage step (`git add <domain>/$GE_ID.md`) from Step 8 is harmless for REVISE (staging an already-tracked file) — no change needed. Confirm the reference still reads correctly after the Step 8 edit.

- [ ] **Step 3: Run the skill structure test to confirm SKILL.md is still valid**

```bash
python -m pytest tests/test_skill_structure.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git -C /path/to/soredium add forage/SKILL.md
git -C /path/to/soredium commit -m "feat(forage): wire integrate_entry.py into CAPTURE Step 8 — Refs #54"
```

---

## Task 6: Update forage SKILL.md — SWEEP Step 5 Deliver

**Files:**
- Modify: `forage/SKILL.md`

Replace the batch `git add/commit` block in SWEEP Step 5 Deliver with the `integrate_entry.py --skip-validate --skip-commit` per-entry loop + single batch commit.

- [ ] **Step 1: Replace SWEEP Step 5 Deliver in `forage/SKILL.md`**

Find the **Deliver** subsection inside **Step 5 — Submit confirmed entries (batched delivery)**. It currently starts with `**Deliver**` and contains two blocks (GitHub remote and no remote). Replace the entire Deliver subsection with:

```markdown
**Deliver**

**Resolve the garden path** (same rule as CAPTURE Step 8 — concrete path, no shell variable
assignment in Bash blocks). **Use the soredium path resolved above** (same `SOREDIUM_PATH`
used for `validate_pr.py` in the Validate step).

Detect the garden's remote:
```bash
git -C /concrete/garden remote get-url origin 2>/dev/null
```

For each written entry, update all indexes on disk without committing yet:
```bash
python3 /concrete/soredium/scripts/integrate_entry.py \
  /concrete/garden/<domain>/$GE_ID.md \
  /concrete/garden \
  --skip-validate --skip-commit
```

Run this sequentially for each entry. After all entries are processed, issue a single
batch commit containing all entry files and all index updates:
```bash
git -C /concrete/garden add <all written entry files>
git -C /concrete/garden add _summaries/ _index/ labels/ GARDEN.md
git -C /concrete/garden add --update
git -C /concrete/garden commit -m "sweep: <N> entries — <slug1>, <slug2>, ..."
```

**If the URL contains `github.com`** → pull and push:
```bash
git -C /concrete/garden pull --rebase origin main
git -C /concrete/garden push origin main
```
```

- [ ] **Step 2: Run the skill structure test**

```bash
python -m pytest tests/test_skill_structure.py -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git -C /path/to/soredium add forage/SKILL.md
git -C /path/to/soredium commit -m "feat(forage): wire integrate_entry.py into SWEEP Step 5 Deliver — Refs #54"
```

---

## Task 7: Full test run, code review, doc sync

- [ ] **Step 1: Run the complete test suite**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All tests PASS. Note any failures — if any test fails, investigate before continuing.

- [ ] **Step 2: Invoke `superpowers:requesting-code-review`**

Review the staged changes across all four modified files. Any finding Minor or above that is not fixed in this session must be filed as a GitHub issue in Hortora/soredium before sign-off. Batch related nits into a single issue.

- [ ] **Step 3: Invoke `implementation-doc-sync`**

Check whether `docs/` or `forage/` contain any documentation that references the old CAPTURE/SWEEP delivery behaviour and needs updating.

- [ ] **Step 4: Sync the installed forage skill**

The cc-praxis source of truth is `~/claude/cc-praxis/forage/SKILL.md`. The soredium repo also contains `forage/SKILL.md`. Confirm which is authoritative for this project and sync accordingly:

```bash
# If soredium/forage/SKILL.md is authoritative, sync to cc-praxis:
cp /path/to/soredium/forage/SKILL.md ~/claude/cc-praxis/forage/SKILL.md
# Then run sync-local to install
```

If cc-praxis is the source of truth, the edit in Task 5/6 should have been made there instead. Resolve and commit.

- [ ] **Step 5: Final commit with issue reference**

```bash
git -C /path/to/soredium log --oneline epic-forage-index-fix ^main
```

Verify all commits reference `#54`. If any don't, amend or note for the PR.

---

## Self-Review

**Spec coverage check:**
- ✅ Section 1 (integrate_entry.py flags): Tasks 1–2
- ✅ Section 2 (CAPTURE Step 8): Task 5
- ✅ Section 3 (SWEEP Step 5 Deliver): Task 6
- ✅ Section 4 — Unit tests (7 tests, flags): Task 1
- ✅ Section 4 — CAPTURE integration tests (2 tests): Task 3
- ✅ Section 4 — SWEEP integration tests (3 tests): Task 4

**Placeholder scan:** No TBDs, no "similar to Task N", all code shown in full.

**Type consistency:** `integrate()` signature is `(entry_path, garden_root=None, skip_validate=False, skip_commit=False)` — used consistently as `_integrate_direct(str(path), str(garden), skip_validate=True, skip_commit=True)` in Tasks 3–4. `git` and `git_out` helpers from `tests/garden_fixture.py` used consistently in Tasks 3–4.

**Gap check:** Task 7 Step 4 (cc-praxis sync) is explicit — forage/SKILL.md in soredium and cc-praxis must not diverge.
