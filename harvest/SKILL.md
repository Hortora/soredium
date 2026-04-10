---
name: harvest
description: >
  Use when integrating garden submissions or deduplicating existing entries — user says "merge
  garden submissions", "harvest the garden", "process submissions", "dedupe the garden", "check
  for duplicates", or invokes /harvest. Run as a dedicated session with full context budget.
  Do NOT use during normal session work — use forage for session-time operations (CAPTURE, SWEEP,
  SEARCH, REVISE). Never invoked automatically; always a deliberate maintenance operation.
---

# Harvest — Garden Maintenance Operations

Harvest handles the two maintenance operations for the knowledge garden:

- **MERGE** — integrate pending submissions from `${HORTORA_GARDEN:-~/.hortora/garden}/submissions/` into the main garden files
- **DEDUPE** — find and resolve duplicate entries within the existing garden

Harvest is always a **dedicated session** — never run during normal session work. It has a full context budget for reading submissions and garden files.

**Forage handles session-time operations: CAPTURE, SWEEP, SEARCH, REVISE.**

**Submission format compatibility:** Harvest processes submissions from both `forage` and the legacy `garden` skill. The submission format is identical.

---

## Git-Only Access Model

**All reads come from git HEAD. Writes go straight to commit. The filesystem is a staging area only.**

```bash
GARDEN=${HORTORA_GARDEN:-~/.hortora/garden}

# Read committed file
git -C $GARDEN show HEAD:GARDEN.md
git -C $GARDEN show HEAD:submissions/2026-04-09-foo-GE-0123-bar.md
git -C $GARDEN show HEAD:tools/git.md

# List committed submissions
git -C $GARDEN ls-tree --name-only HEAD submissions/

# Search committed content
git -C $GARDEN grep "keywords" HEAD -- '*.md' ':!GARDEN.md' ':!CHECKED.md' ':!DISCARDED.md'

# Surgical section read from committed file
git -C $GARDEN show HEAD:tools/git.md | grep -A 40 "## Entry Title"
```

**Why:** Direct filesystem reads can see partial writes from concurrent forage sessions. `git show HEAD:path` always returns complete, committed state.

**Conflict recovery:** If a commit fails because a forage session committed in between:
```bash
git -C $GARDEN rebase HEAD   # incorporate forage's changes
# Re-read affected files from new HEAD if needed
# Re-commit
```

This works identically for local git and remote/federated gardens.

---

## Garden Structure

```
${HORTORA_GARDEN:-~/.hortora/garden}/
├── GARDEN.md                   ← metadata header (Last assigned ID, drift counter)
├── CHECKED.md                  ← duplicate check pair log
├── DISCARDED.md                ← discarded duplicates
├── submissions/                ← pending entries from forage and garden sessions
│   └── YYYY-MM-DD-<project>-GE-XXXX-<slug>.md
├── tools/
├── quarkus/
├── java/
├── intellij-platform/
└── <tech-category>/
    └── <topic>.md
```

**`GARDEN.md` metadata header:**

```markdown
**Last assigned ID:** GE-0042
**Last full DEDUPE sweep:** YYYY-MM-DD
**Entries merged since last sweep:** 3
**Drift threshold:** 10
```

**`CHECKED.md`** tracks which entry pairs have been semantically compared for duplicate detection. Only within-category pairs are checked.

**`DISCARDED.md`** records submissions discarded as duplicates:
```
| GE-XXXX | GE-YYYY | date | [brief reason] |
```

---

## GE-ID Format

Two formats coexist in the garden:

- **Legacy** (GE-0001 … GE-0172): sequential counter, assigned at submission time. The `Last assigned ID` field in GARDEN.md tracks the highest legacy ID.
- **New** (GE-YYYYMMDD-xxxxxx, e.g. GE-20260410-a3f7c2): date + 6 random hex chars, assigned by forage at submission time with no counter. See ADR-0003.

Harvest does NOT assign new IDs — those are always assigned by forage. Harvest verifies IDs from submission filenames and headers, checks for conflicts, and adds the `**ID:** GE-XXXX` line to each integrated entry.

If a submission has no GE-ID (legacy format with no ID in the file): generate a new-format ID using `GE-$(date +%Y%m%d)-$(python3 -c "import secrets; print(secrets.token_hex(3))")` and note the assignment in the commit message.

---

## Workflows

### MERGE (integrate submissions into the garden)

Run as a dedicated operation with full context budget for reading.

**When to run MERGE:**
- User says "merge the garden", "harvest the garden", "process garden submissions"
- There are pending submissions (check in Step 1)
- Before a session that will need to search the garden for existing knowledge

**Step 0 — Drift check**

Read GARDEN.md from committed state:
```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} show HEAD:GARDEN.md | head -10
```

Check `Entries merged since last sweep` against `Drift threshold` (default: 10).

If `entries_merged_since_sweep >= drift_threshold`:
  > "The garden has drifted — [N] entries have been added since the last full duplicate sweep (threshold: [T]). Run a full DEDUPE sweep before merging this batch?"
  >
  > Options: **YES** (run DEDUPE now, then continue) / **defer** (merge now, sweep later) / **skip** (merge and reset counter)

**Step 1 — List pending submissions**

Read from committed state:
```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} ls-tree --name-only HEAD submissions/
```

**Step 2 — Read each submission**

Read each submission from committed state:
```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} show HEAD:submissions/<filename>.md
```

They're compact by design — read all of them.

**Step 3 — Load GARDEN.md index**

```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} show HEAD:GARDEN.md
```

Scan all three index sections (By Technology, By Symptom/Type, By Label) for entries similar to each submission.

**Step 4 — For likely duplicates: surgical read of relevant section**

Read only the sections that might overlap:
```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} show HEAD:<file>.md | grep -A 30 "## <existing title>"
```

**Step 4b — Identify REVISE submissions**

Check filenames for "revise" — these need different handling from new entries.

For each REVISE submission:
1. Read the target entry from committed state:
   ```bash
   git -C ${HORTORA_GARDEN:-~/.hortora/garden} show HEAD:<path>/<file>.md | grep -A 60 "## Exact Entry Title"
   ```
2. Integrate based on revision kind:

| Kind | How to integrate |
|------|-----------------|
| `solution` | If Fix says "None known": replace with solution. If Fix already has a solution: restructure into Solution 1 / Solution 2 with pros/cons for each |
| `alternative` | Add `### Alternative — [brief name]` after the existing Fix/Solution section with pros/cons |
| `variant` | Add `## Variant — [context]` section within the file |
| `update` | Append to the relevant section (Root cause, Context, Caveats, etc.) |
| `resolved` | Add `**Resolved in: vX.Y** — [brief note]` after the Stack line; keep the entry intact |
| `deprecated` | Add `**Deprecated:** [reason and date]` near the top; keep the entry for historical reference |

**Multiple solutions structure** (only when 2 or more exist):

```markdown
### Solution 1 — [brief descriptive name]
**Approach:** [one sentence]
**Pros:** [what makes it good]
**Cons/trade-offs:** [limitations, constraints]
[code block]

### Solution 2 — [brief descriptive name]
**Approach:** [one sentence]
**Pros:** [what makes it good]
**Cons/trade-offs:** [limitations, constraints]
[code block]
```

Single solutions don't get pros/cons. Only apply when a second solution is being added.

**Step 5 — Classify each submission**

For each submission, check the Garden Score first:
- **Score 12–15** → include unless it's a duplicate
- **Score 8–11** → include if "case for" outweighs "case against"
- **Score 5–7** → only include if "case for" is compelling
- **Score <5** → discard; note in the report

Then classify against existing garden content:
- **New** — no matching entry exists; place in garden (subject to score threshold)
- **Duplicate** — identical to an existing entry; discard submission regardless of score
- **Related** — overlaps with an existing entry; enrich or note the variant

**Step 5b — Medium duplicate check (section read)**

For each submission classified as "New" in Step 5:
1. Extract technology/stack keywords from the submission
2. Find same-category existing entries in the committed GARDEN.md index
3. For each candidate, read the first 30 lines from committed state:
   ```bash
   git -C ${HORTORA_GARDEN:-~/.hortora/garden} show HEAD:<file>.md | grep -A 30 "## Entry Title"
   ```
4. Compare: symptom description, root cause keywords, fix approach
5. If similar: present to user — "GE-XXXX [new] looks similar to GE-YYYY [existing] — duplicate, related, or distinct?"
   - **Duplicate** → discard; add to DISCARDED.md; log to CHECKED.md as `duplicate-discarded`
   - **Related** → note cross-references; log to CHECKED.md as `related`
   - **Distinct** → proceed; log to CHECKED.md as `distinct`
6. Log ALL comparisons made to CHECKED.md (even distinct ones)

**Step 6 — Integrate new and related entries**

Write changes to the filesystem (staging area), then commit atomically in Step 9.

For new entries: append to the appropriate garden file in the working tree. Add `**ID:** GE-XXXX` to the entry header immediately after the `## Entry Title` heading. Then update GARDEN.md in the working tree:

| Entry type | By Technology | By Symptom / Type | By Label |
|---|---|---|---|
| Gotcha | ✅ add | ✅ add under matching symptom category | — |
| Technique | ✅ add | — | ✅ add under each matching label |
| Undocumented | ✅ add | ✅ add (or new "Undocumented" category) | — |

**Verify GE-ID:** Confirm the submission's GE-ID is not already present in the committed index. If it is (race condition), assign the next available ID from `git show HEAD:GARDEN.md` and note the change.

**Creating a new garden file:** Add the correct header on line 1:
- `# <Technology> Gotchas` / `# <Technology> Techniques` / `# <Technology> Gotchas and Techniques`
- Use tool/library name, not problem-domain name

**Adding a technique:** Ensure the entry has a `**Labels:**` field with at least one label from the Tag Index. Reuse existing tags before inventing new ones.

**Preserve the score:** At the end of each newly integrated entry, append the compact score line from the submission:

```
*Score: 11/15 · Included because: [brief reason] · Reservation: [none / brief reason]*
```

**Step 6b — Integrate using integrate_entry.py (preferred method)**

After writing the final integrated entry to `<domain>/GE-XXXX.md`, run:

```bash
python ${SOREDIUM_PATH:-~/claude/hortora/soredium}/scripts/integrate_entry.py \
  ${HORTORA_GARDEN:-~/.hortora/garden}/<domain>/GE-XXXX.md \
  ${HORTORA_GARDEN:-~/.hortora/garden}
```

This updates `_summaries/`, domain `INDEX.md`, `labels/`, and `_index/global.md` in one step, runs the structural check, and commits automatically. **Do not commit manually** — `integrate_entry.py` commits automatically.

Alternatively, if using manual index updates (Step 6 above), proceed to Step 7 and commit as described. The script approach (6b) automates those steps.

**Step 7 — Remove processed submissions**

Stage the deletions:
```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} rm submissions/<processed-file>.md
```

**Step 8 — Update GARDEN.md metadata**

In the working tree:
- Increment `Entries merged since last sweep` by the number of new entries integrated
- `Last assigned ID`: only update if any legacy-format (GE-NNNN) entries were assigned new IDs from the counter; new-format IDs (GE-YYYYMMDD-xxxxxx) do not affect the counter

**Step 9 — Validate and commit atomically**

Run the validator against the working tree (it legitimately reads uncommitted state here — it's validating what's about to be committed):
```bash
python3 ~/claude/hortora/soredium/scripts/validate_garden.py ${HORTORA_GARDEN:-~/.hortora/garden}
```

Must exit 0. If it reports errors, fix them before committing.

Then commit all changes in one atomic operation:
```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} add .
git -C ${HORTORA_GARDEN:-~/.hortora/garden} commit -m "merge: integrate N submissions — <brief summary>"
```

If the commit fails (a forage session committed in between):
```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} rebase HEAD
# Re-read any affected files from new HEAD
# Re-commit
```

**Step 10 — Report**

Tell the user:
- How many submissions were merged
- How many were duplicates / discarded
- How many were related entries (cross-referenced)
- Which garden files were updated
- Current drift status (entries merged since last DEDUPE sweep)

---

### DEDUPE (find and resolve duplicate entries)

Use when: drift threshold exceeded (prompted by MERGE Step 0), or user explicitly says "dedupe the garden", "check for duplicates".

Unlike MERGE which checks new submissions against existing entries, DEDUPE checks *existing entries against each other*.

**Step 1 — Load the index and pair log**

Read both from committed state:
```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} show HEAD:GARDEN.md
git -C ${HORTORA_GARDEN:-~/.hortora/garden} show HEAD:CHECKED.md
```

Enumerate all entries with their GE-IDs, grouped by technology category. Build the set of already-verified pairs from CHECKED.md.

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
git -C ${HORTORA_GARDEN:-~/.hortora/garden} show HEAD:<file>.md | grep -A 40 "## Entry Title"
```

Classify:
- **Distinct** — different enough; no action needed
- **Related** — similar but legitimately separate; add cross-references to both entries
- **Duplicate** — one is a subset or copy of the other; propose to user which to keep

**Step 4 — Resolve duplicates and related entries**

Write changes to working tree:
- Related pairs: add `**See also:** GE-XXXX [title]` to both entries
- Duplicates: present both to user, keep the more complete one, discard the other; record in DISCARDED.md

**Step 5 — Update CHECKED.md**

Append to CHECKED.md in working tree:

```markdown
| GE-0003 × GE-0007 | distinct | YYYY-MM-DD | |
| GE-0004 × GE-0008 | related | YYYY-MM-DD | cross-referenced |
| GE-0005 × GE-0009 | duplicate-discarded | YYYY-MM-DD | GE-0005 kept |
```

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

## Common Pitfalls

| Mistake | Why It's Wrong | Fix |
|---------|----------------|-----|
| Reading garden files with `cat` or `grep` from filesystem | May see partial writes from a concurrent forage session | Always use `git show HEAD:path` |
| Reading submission list with `ls submissions/` | Filesystem may show a file mid-write | Use `git ls-tree --name-only HEAD submissions/` |
| Running MERGE during normal session work | Needs full context budget; deprives active session | Always run harvest as a dedicated session |
| Not checking REVISE filenames before processing | Treats enrichments as new entries | Always check for "revise" in filenames first |
| Adding a second solution without pros/cons | Reader can't choose between approaches | Always use Solution 1 / Solution 2 format when 2+ exist |
| Retroactively reformatting single-solution entries | Unnecessary churn | Only add pros/cons when a second solution arrives |
| REVISE "resolved" entry: deleting the original content | Users on older versions still need the entry | Add "Resolved in: vX.Y" note — never delete |
| Skipping the commit | Makes git history useless as an archive | Commit is mandatory |
| Not updating CHECKED.md during MERGE | Loses track of which pairs have been compared | Every comparison made must be logged |
| Running DEDUPE across categories | Cross-category entries can't be duplicates | Only compare within-category pairs |
| MERGE: By Label section not updated for new technique | Technique unfindable by cross-cutting concern | For every technique, add to By Label under each label |
| MERGE: By Symptom / Type updated for a technique | Wrong section for techniques | By Symptom / Type is for gotchas only |
| Missing version for a 3rd party library | Future readers can't tell if the gotcha applies | Include version or range |
| Forgetting to increment drift counter | DEDUPE is never triggered | Increment `Entries merged since last sweep` after each new entry |
| Assigning new GE-IDs during MERGE | IDs are assigned at submission time by forage | Only verify IDs; assign new ones only for legacy submissions without IDs |

---

## Success Criteria

MERGE is complete when:
- ✅ Submissions listed via `git ls-tree` (not `ls`)
- ✅ All submissions read via `git show HEAD:submissions/<file>` (not filesystem)
- ✅ All garden files read via `git show HEAD:<path>` (not filesystem)
- ✅ All submissions classified (new / duplicate / related)
- ✅ New entries appended to appropriate garden files (with correct file header if new file)
- ✅ Technique entries have `**Labels:**` field in the content file
- ✅ GARDEN.md updated: By Technology always; By Symptom/Type for gotchas; By Label for techniques
- ✅ New labels added to Tag Index if used
- ✅ GE-IDs verified from submission filenames/headers; added as `**ID:**` in entry headers and index
- ✅ GARDEN.md metadata updated: `Entries merged since last sweep` incremented
- ✅ Medium duplicate check (section read) performed; results logged in CHECKED.md
- ✅ Discarded submissions removed and recorded in DISCARDED.md
- ✅ DEDUPE offered if drift threshold exceeded
- ✅ Validator run: `python3 ~/claude/hortora/soredium/scripts/validate_garden.py` — exits 0
- ✅ All changes committed atomically with `merge:` format
- ✅ Conflict recovery via `git rebase` if commit fails

DEDUPE is complete when:
- ✅ Index and CHECKED.md read via `git show HEAD:` (not filesystem)
- ✅ All within-category unchecked pairs processed
- ✅ Garden entries read via `git show HEAD:<path>` (not filesystem)
- ✅ CHECKED.md updated with all results
- ✅ Related entries have cross-references
- ✅ Duplicate entries resolved (user confirmed which to keep)
- ✅ GARDEN.md drift counter reset
- ✅ All changes committed atomically with `dedupe:` format

---

## Skill Chaining

**Invoked by:** User directly for maintenance sessions ("merge garden submissions", "harvest the garden", "dedupe the garden")

**Invoked after:** `forage` sessions accumulate submissions — forage tells users to "run harvest when convenient"

**Does NOT handle:** CAPTURE, SWEEP, SEARCH, REVISE — those are forage operations.

**Reads from (git HEAD only):**
- `git show HEAD:GARDEN.md` — index and metadata
- `git show HEAD:CHECKED.md` — pair log for DEDUPE
- `git ls-tree HEAD submissions/` — list pending submissions
- `git show HEAD:submissions/<file>` — individual submissions
- `git show HEAD:<path>` — garden detail files (surgical reads)

**Garden location:** `${HORTORA_GARDEN:-~/.hortora/garden}/`
**Submission format:** Processes both forage submissions and legacy garden submissions (identical format).
