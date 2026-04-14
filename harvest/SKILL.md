---
name: harvest
description: >
  Use when deduplicating existing garden entries (DEDUPE) or reviewing all stale entries
  across the garden (REVIEW). DEDUPE: user says "dedupe the garden", "check for duplicates".
  REVIEW: user says "review stale entries", "staleness review", "harvest review", or when
  validate_garden.py --freshness shows many overdue entries. Run as a dedicated session
  with full context budget. Do NOT use during normal session work — use forage for
  session-time operations. Never invoked automatically; always a deliberate maintenance
  operation.
---

# Harvest — Garden Maintenance Operations

Harvest handles two maintenance operations for the knowledge garden:

- **DEDUPE** — find and resolve duplicate entries within the existing garden
- **REVIEW** — find and resolve entries past their `staleness_threshold` across all domains

Harvest is always a **dedicated session** — never run during normal session work. It has a full context budget for reading garden files.

**Forage handles session-time operations: CAPTURE, SWEEP, SEARCH, REVISE.**

Entries are written directly to the garden by forage (as individual `<domain>/GE-XXXX.md` files with YAML frontmatter). There is no submissions queue — harvest is only needed for periodic duplicate detection.

---

## Git-Only Access Model

**All reads come from git HEAD. Writes go straight to commit. The filesystem is a staging area only.**

```bash
GARDEN=${HORTORA_GARDEN:-~/.hortora/garden}

# Read committed file
git -C $GARDEN show HEAD:GARDEN.md
git -C $GARDEN show HEAD:tools/GE-0002.md

# Search committed content
git -C $GARDEN grep "keywords" HEAD -- '*.md' ':!GARDEN.md' ':!CHECKED.md' ':!DISCARDED.md'

# Surgical section read from committed file
git -C $GARDEN show HEAD:tools/GE-0002.md | head -20
```

**Why:** Direct filesystem reads can see partial writes from concurrent forage sessions. `git show HEAD:path` always returns complete, committed state.

**Conflict recovery:** If a commit fails because a forage session committed in between:
```bash
git -C $GARDEN rebase HEAD
# Re-read affected files from new HEAD if needed
# Re-commit
```

---

## Garden Structure

```
${HORTORA_GARDEN:-~/.hortora/garden}/
├── GARDEN.md                   ← index and metadata (drift counter)
├── CHECKED.md                  ← duplicate check pair log
├── DISCARDED.md                ← discarded duplicates
├── tools/
│   └── GE-YYYYMMDD-xxxxxx.md  ← one file per entry, YAML frontmatter
├── quarkus/
├── java/
└── <tech-category>/
    └── GE-YYYYMMDD-xxxxxx.md
```

**`GARDEN.md` metadata header:**

```markdown
**Last legacy ID:** GE-0180
**Last full DEDUPE sweep:** YYYY-MM-DD
**Entries merged since last sweep:** 3
**Drift threshold:** 10
```

**`CHECKED.md`** tracks which entry pairs have been semantically compared for duplicate detection. Only within-category pairs are checked.

**`DISCARDED.md`** records entries discarded as duplicates:
```
| GE-XXXX | GE-YYYY | date | [brief reason] |
```

---

## GE-ID Format

All entries use the new format: `GE-YYYYMMDD-xxxxxx` (date + 6 random hex chars), assigned by forage at write time with no counter. See ADR-0003.

Legacy sequential IDs (`GE-0001` … `GE-0180`) still exist in the garden but no new ones are assigned.

---

## Workflows

### DEDUPE (find and resolve duplicate entries)

Use when: drift threshold exceeded, or user explicitly says "dedupe the garden", "check for duplicates".

DEDUPE checks *existing entries against each other* — it does not process submissions (there are none).

**Step 1 — Run scanner to get pre-scored pair list**

```bash
python3 ${SOREDIUM_PATH:-~/claude/hortora/soredium}/scripts/dedupe_scanner.py \
  ${HORTORA_GARDEN:-~/.hortora/garden} --top 50
```

The scanner reads domain directories directly for YAML-frontmatter entries, cross-references CHECKED.md to exclude already-checked pairs, computes Jaccard similarity for all unchecked within-domain pairs, and returns them sorted highest-score-first.

Review pairs from highest score down — highest-scoring pairs are most likely related or duplicate. Use `--domain <name>` to focus on one domain at a time. Use `--json` for machine-readable output.

**Step 2 — Generate unchecked pairs per category**

For each technology category:
- List all entries in that category
- Generate all within-category pairs
- Exclude pairs already in CHECKED.md
- These are the unchecked pairs to process

Cross-category pairs are never checked — they cannot be duplicates.

**Step 3 — Compare unchecked pairs**

For each unchecked pair, read both entries surgically from committed state:

```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} show HEAD:<domain>/GE-XXXX.md | head -30
```

Classify:
- **Distinct** — different enough; no action needed
- **Related** — similar but legitimately separate; add cross-references to both entries
- **Duplicate** — one is a subset or copy of the other; propose to user which to keep

**Step 4 — Resolve duplicates and related entries**

Write changes to working tree:
- Related pairs: add `**See also:** GE-XXXX [title]` to both entries
- Duplicates: present both to user, keep the more complete one, discard the other; record in DISCARDED.md

**Step 5 — Record comparison results via scanner**

For each pair reviewed, record the result using the scanner's `--record` flag:

```bash
python3 ${SOREDIUM_PATH:-~/claude/hortora/soredium}/scripts/dedupe_scanner.py \
  ${HORTORA_GARDEN:-~/.hortora/garden} \
  --record "GE-XXXX × GE-YYYY" distinct "brief note"
```

Results must be one of: `distinct`, `related`, `duplicate-discarded`.

The scanner enforces canonical ID ordering and is idempotent — recording the same pair twice produces one row only. Do NOT append to CHECKED.md manually.

**Step 6 — Reset drift counter**

Update GARDEN.md in working tree:
- `Last full DEDUPE sweep: YYYY-MM-DD`
- `Entries merged since last sweep: 0`

**Step 7 — Commit atomically**

```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} add .
git -C ${HORTORA_GARDEN:-~/.hortora/garden} commit -m "dedupe: sweep N pairs — M related, K duplicates resolved"
```

If the commit fails, rebase and re-commit.

**Step 8 — Report**

Tell the user:
- How many pairs were checked
- How many were distinct / related / duplicate
- Which garden files were updated

---

### REVIEW (find and resolve stale entries)

Use when: "review stale entries", "staleness review", "harvest review", or when
`validate_garden.py --freshness` shows many overdue entries across the garden.

Unlike the SWEEP staleness spot-check (domain-filtered, session-scoped), REVIEW covers
ALL domains systematically — it is the backstop that guarantees full garden coverage.

**Step 1 — Report overdue count**

```bash
python3 ${SOREDIUM_PATH:-~/claude/hortora/soredium}/scripts/validate_garden.py \
  --freshness ${HORTORA_GARDEN:-~/.hortora/garden}
```

Note the count and which entries are most overdue. If count is 0, report to user and stop — no REVIEW needed.

**Step 2 — Load all entries and build the overdue list**

Read the committed index:
```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} show HEAD:GARDEN.md
```

For each entry in the By Technology section, read its YAML frontmatter:
```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} show HEAD:<domain>/GE-XXXX.md | head -25
```

Build the overdue list: entries where `(today - max(submitted, last_reviewed)).days > staleness_threshold`.
Sort oldest-first.

**Step 3 — Process each overdue entry**

For each entry in the overdue list, present:

> ⚠️ **GE-XXXX** "[title]"
> Domain: {domain} | Submitted: {submitted} | Last reviewed: {last_reviewed or "never"} | Age: {N} days | Threshold: {T} days
> **CONFIRM** still valid / **REVISE** / **RETIRE** / **Skip**?

- **CONFIRM**: add `last_reviewed: YYYY-MM-DD` to YAML frontmatter in working tree (or update if already present).
- **REVISE**: run the REVISE workflow for this entry in-place.
- **RETIRE**: add `**Deprecated:** [reason] — {date}` near the top of the entry body. Keep content intact — users on older versions still need it.
- **Skip**: no action. Entry will appear on the next REVIEW.

**Step 4 — Update GARDEN.md staleness tracking**

In the GARDEN.md working tree, update the `Last staleness review` line:
```
**Last staleness review:** YYYY-MM-DD
```

**Step 5 — Commit atomically**

```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} add .
git -C ${HORTORA_GARDEN:-~/.hortora/garden} commit -m "review: staleness sweep — N confirmed, M revised, K retired, P skipped"
```

If the commit fails (concurrent forage session committed first):
```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} rebase HEAD
# Re-commit
```

**Step 6 — Report**

Tell the user:
- How many entries were overdue in total
- How many confirmed / revised / retired / skipped
- That `Last staleness review` in GARDEN.md is now updated to today

---

## Common Pitfalls

| Mistake | Why It's Wrong | Fix |
|---------|----------------|-----|
| Reading garden files with `cat` or `grep` from filesystem | May see partial writes from a concurrent forage session | Always use `git show HEAD:path` |
| Running DEDUPE during normal session work | Needs full context budget; deprives active session | Always run harvest as a dedicated session |
| Running REVIEW during normal session work | Needs full context budget for full garden sweep | Always run harvest as a dedicated session |
| Adding a second solution without pros/cons | Reader can't choose between approaches | Always use Solution 1 / Solution 2 format when 2+ exist |
| Skipping the commit | Makes git history useless as an archive | Commit is mandatory |
| Not updating CHECKED.md | Loses track of which pairs have been compared | Every comparison made must be logged |
| Running DEDUPE across categories | Cross-category entries can't be duplicates | Only compare within-category pairs |

---

## Success Criteria

DEDUPE is complete when:
- ✅ Index and CHECKED.md read via `git show HEAD:` (not filesystem)
- ✅ All within-category unchecked pairs processed
- ✅ Garden entries read via `git show HEAD:<path>` (not filesystem)
- ✅ CHECKED.md updated with all results
- ✅ Related entries have cross-references
- ✅ Duplicate entries resolved (user confirmed which to keep)
- ✅ GARDEN.md drift counter reset
- ✅ All changes committed atomically with `dedupe:` format

REVIEW is complete when:
- ✅ `validate_garden.py --freshness` run and count noted
- ✅ All overdue entries read via `git show HEAD:<path>` (not filesystem)
- ✅ All overdue entries processed (CONFIRM / REVISE / RETIRE / Skip)
- ✅ `last_reviewed` field added/updated for all CONFIRMed entries
- ✅ RETIRE entries have deprecation note added, original content preserved
- ✅ `Last staleness review` in GARDEN.md updated to today
- ✅ All changes committed atomically with `review:` message format

---

## Skill Chaining

**Invoked by:** User directly for maintenance sessions
- DEDUPE: "dedupe the garden", "check for duplicates", drift counter at threshold
- REVIEW: "review stale entries", "staleness review", "harvest review", or when `--freshness` shows many overdue entries

**Does NOT handle:** CAPTURE, SWEEP, SEARCH, REVISE — those are forage operations.

**Reads from (git HEAD only):**
- `git show HEAD:GARDEN.md` — index and metadata
- `git show HEAD:CHECKED.md` — pair log for DEDUPE
- `git show HEAD:<domain>/<entry>.md` — garden entry files (surgical reads)

**Garden location:** `${HORTORA_GARDEN:-~/.hortora/garden}/`
