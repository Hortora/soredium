# Design: Garden Schema — `type: convention` + `variant:` field

**Issue:** Hortora/soredium#44
**Date:** 2026-05-14
**Status:** Approved

---

## Problem

During Audit 2, a third entry type emerged that doesn't fit `gotcha`, `technique`, or `undocumented`: **conventions** — deliberate style choices where alternatives are equally valid. Examples: Maven submodule naming (`api/runtime/deployment` vs `core/web/persistence`), Quartz job store (RAM vs JDBC), three-tier module structure. These are project-level decisions, not universal truths, but still worth sharing so other projects can adopt or consciously reject them.

The current schema has no place for them. The `discovery` garden only accepts `gotcha | technique | undocumented`.

---

## Schema Changes

### `type: convention`

Added to `discovery` garden valid types alongside `gotcha`, `technique`, `undocumented`.

**Editorial bar:** Is this a deliberate style choice that another project could meaningfully adopt? Is there at least one known valid alternative?

**Staleness threshold:** 3650 days (10 years). Style conventions change slowly — same default as `patterns` and `decisions` gardens. This intentionally overrides the discovery garden's 730-day default; submitters should always include `staleness_threshold: 3650` in convention entries.

### `variant:` field (optional)

When two or more entries share the same `title:` in the same domain, each must carry `variant:` to distinguish them.

```yaml
# Entry 1
title: "Maven submodule naming"
variant: "api/runtime/deployment — Quarkus extension style"
type: convention

# Entry 2
title: "Maven submodule naming"
variant: "core/web/persistence — Spring Boot layered style"
type: convention
```

**Lifecycle:** A solo convention entry (first of its title) omits `variant:`. When a second entry for the same title is submitted, both entries gain `variant:` — the new one at submission time, the existing one via a REVISE.

`variant:` is also accepted on `type: technique` entries (for same-problem alternative approaches), but enforcement only triggers for `type: convention`.

---

## Section 1 — `validate_pr.py`

### Changes

**1. Add `'convention'` to `GARDEN_TYPES['discovery']['valid_types']`.**
One-liner. No other type-validation logic changes.

**2. Add `find_same_title_siblings(title, domain, garden_root, exclude_stem) -> list[str]`.**
Scans `garden_root/domain/GE-*.md`, parses frontmatter via existing `parse_entry`, returns list of stems whose `title` field matches exactly. Exceptions per file are caught and skipped (matching the existing `scan_domain` pattern).

**3. Variant consistency check (when `garden_root` provided), gated on `type: convention`.**

After the Jaccard block:

```
if entry_type == 'convention' and garden_root:
    siblings = find_same_title_siblings(title, domain, garden_root, path.stem)
    if siblings and 'variant' not in fm:
        CRITICAL: "Convention shares title {title!r} with {stems}: add 'variant:' to distinguish"
    if 'variant' in fm and not siblings:
        WARNING: "'variant:' set but no sibling with title {title!r} found in domain — verify title matches or omit 'variant:'"
```

For `type != 'convention'`: if same-title siblings exist, emit WARNING only ("same title as {stems} — verify this is intentional"). No CRITICAL.

**4. Jaccard suppression for confirmed convention siblings.**

After the Jaccard loop, when `entry_type == 'convention'` and `'variant' in fm` and siblings were found: downgrade any Jaccard WARNINGs for those specific stems to INFO with a note: "(convention sibling — expected overlap)". This prevents spurious duplicate warnings on valid same-title pairs.

### Why the CRITICAL is type-gated

Same-title entries on `technique` or other types are not necessarily wrong — they could be independent entries that happen to share a title. Only `convention` semantically requires `variant:` when siblings exist; enforcing it as CRITICAL for all types would generate false positives for coincidental title matches.

---

## Section 2 — `validate_garden.py`

### Changes

**1. Add `import yaml` at module level** (alongside existing `import re`, `import sys`, `from pathlib import Path`). Guard at the top of `validate()` with a try/except ImportError that calls `log_error` and returns early if PyYAML is unavailable, matching the `validate_pr.py` error pattern. This is a new runtime dependency for `validate_garden.py`; document in README if one exists.

**2. Add check 8 — same-title variant consistency** (after the existing check 7):

```
# 8. Check variant: consistency for same-title entries
Scan all GE-*.md files (respecting EXCLUDE_DIRS and skip-names).
Parse frontmatter via yaml.safe_load.
Group by (domain, title).
For any group with >1 member where any member lacks 'variant:':
    log_error(f"Same-title entries in {domain!r} share title {title!r} but {', '.join(missing)} lack 'variant:'")
```

Files that fail to parse are skipped silently (non-entry .md files exist in `_index/` and `_summaries/`).

**Severity:** ERROR (exit code 1). A missing `variant:` in a confirmed same-title group is a genuine integrity violation.

**Scope:** Integrated garden entries only. `submissions/` is excluded (already in `EXCLUDE_DIRS`). The PR-time CRITICAL handles pre-integration enforcement; this check is the backup.

---

## Section 3 — `submission-formats.md`

### Changes

**1. Add `variant:` to the Optional Frontmatter Fields table** at the top:

| Field | Type | Purpose |
|-------|------|---------|
| `variant` | string | Distinguishes this entry from same-title alternatives in the same domain. Required when two or more entries share `title:`. Omit for a solo entry with no known alternatives yet — add it (via REVISE) when a second entry for this title is submitted. |

**2. Add Convention Template** after the Undocumented template. Key points:
- `variant:` shown with an inline comment: `# Omit if this is the only entry for this title`
- `staleness_threshold: 3650` with a comment: `# 10yr — conventions change slowly`
- Body heading uses the `variant` value (not the title), with a note explaining this diverges from other templates because two entries for the same title need distinct H1s
- Score footer line included: `*Score: N/15 · Included because: ... · Reservation: ...*`

**3. Note on `staleness_threshold: 3650`:** Add a sentence to the template or table explaining that convention entries use 3650 rather than the discovery default of 730 because style conventions are stable over years.

---

## Section 4 — `forage/SKILL.md`

### All enumeration sites (11 total)

Every place that lists entry types needs updating. Complete list:

| Location | Change |
|----------|--------|
| Intro "three kinds of entries" bullet list | → "four kinds"; add convention bullet |
| "The bar for undocumented" paragraph block | Add companion "The bar for conventions" paragraph |
| Entry format block: `type: gotcha \| technique \| undocumented` | Add `\| convention` |
| Step 1: "Classify the type: gotcha, technique, or undocumented" | Add convention; add definition and guidance |
| SWEEP Step N header/intro: "all three entry types" | → "all four entry types" |
| SWEEP Step N report string: "across gotchas, techniques, or undocumented items" | Add conventions |
| SWEEP success criterion: "All three categories checked" | → "All four categories checked" |
| Proactive Trigger offer line: "[gotcha / technique / undocumented]" | Add convention |
| Common Pitfalls: "Techniques and undocumented items are easy to miss" | Add conventions |
| Common Pitfalls: CAPTURE type list for non-discovery gardens | Add convention |
| Step 4 discovery editorial bar | Add convention bar (see below) |

### Convention definition (Step 1)

Add a fourth classification option:

> **Convention** — a deliberate style choice where alternatives exist and are equally valid. Not universally true — another project could legitimately choose a different style. Examples: naming schemes, module structures, config strategy choices. If same-title alternatives will exist, each entry carries `variant:`.

### SWEEP — new Step 4 (convention scan)

Insert between current Step 3 (Undocumented) and Step 4 (Confirm):

> **Step 4 — Scan for Conventions**
>
> Look for: naming or structuring decisions made deliberately with alternatives compared; patterns adopted as a project style that another project could consciously adopt or reject; moments where "we always do it this way" was stated about a non-universal choice.
>
> For each candidate: *"We chose [X] for [concern] — an alternative is [Y]. Worth submitting as a convention entry?"*

Renumber subsequent steps.

### Proactive Trigger for conventions

Add to the Proactive Trigger section:

> **For conventions:** a naming or structural choice was discussed with alternatives considered. User says "we always do it this way", "we chose X over Y", "that's our style for this".
>
> Offer: *"That looks like a deliberate style choice — want me to record it as a convention entry?"*

### Step 4 — garden table and editorial bar

Update `discovery` row description to: "Non-obvious behaviour, silent failure, undocumented feature, or deliberate style choice with known alternatives."

Update `discovery` editorial bar: "Gotcha/technique/undocumented: Would a skilled developer familiar with the technology still have spent significant time on this? Convention: Is this a deliberate style choice another project could meaningfully adopt, with at least one known valid alternative?"

### Scoring note for conventions

Add a note in the scoring section or Step 1: "Convention entries typically score lower on Pain/Impact and Non-obviousness than gotchas — a score of 6–9 is expected for a well-articulated convention with clear alternatives. Apply the editorial bar rather than the score gate mechanically."

---

## Files Changed

| File | Change |
|------|--------|
| `scripts/validate_pr.py` | Add `convention` type; add `find_same_title_siblings`; variant consistency check (type-gated); Jaccard suppression for convention siblings |
| `scripts/validate_garden.py` | Add `import yaml`; add check 8 (same-title variant consistency) |
| `forage/submission-formats.md` | Add `variant:` to Optional Frontmatter Fields table; add Convention Template |
| `forage/SKILL.md` | Update all 11 enumeration sites; add convention to Step 1; add SWEEP Step 4; add Proactive Trigger; update garden table and editorial bar; add scoring note |

## Tests

New test cases for `validate_pr.py`:
- `type: convention` accepted in discovery garden
- `variant:` absent, no siblings → passes (no CRITICAL, no WARNING)
- `variant:` absent, sibling with same title exists → CRITICAL
- `variant:` present, sibling exists → passes
- `variant:` present, no sibling → WARNING
- Non-convention type with same-title sibling → WARNING only (no CRITICAL)
- Two convention siblings both with `variant:` → Jaccard WARNINGs downgraded to INFO

New test cases for `validate_garden.py`:
- Two entries same domain+title, both have `variant:` → passes
- Two entries same domain+title, one missing `variant:` → ERROR
- Two entries same domain+title, both missing `variant:` → ERROR listing both GE-IDs
- Solo convention entry, no `variant:` → passes (no sibling group)
