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

- **MERGE** — integrate pending submissions from `~/claude/knowledge-garden/submissions/` into the main garden files
- **DEDUPE** — find and resolve duplicate entries within the existing garden

Harvest is always a **dedicated session** — never run during normal session work. It has a full context budget for reading submissions and garden files.

**Forage handles session-time operations: CAPTURE, SWEEP, SEARCH, REVISE.**

**Submission format compatibility:** Harvest processes submissions from both `forage` and the legacy `garden` skill. The submission format is identical.

---

## Garden Structure

```
~/claude/knowledge-garden/
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

## GE-ID Counter

The GE-ID counter lives at `~/claude/knowledge-garden/GARDEN.md` under `**Last assigned ID:**`. Harvest does NOT assign new IDs — those are assigned by forage at submission time. Harvest verifies IDs from submission filenames and headers, checks for conflicts, and adds the `**ID:** GE-XXXX` line to each integrated entry.

If a submission has no GE-ID (legacy format): assign the next available ID, update GARDEN.md, and note the change in the commit message.

---

## Workflows

### MERGE (integrate submissions into the garden)

Run as a dedicated operation with full context budget for reading.

**When to run MERGE:**
- User says "merge the garden", "harvest the garden", "process garden submissions"
- There are several pending submissions: `ls ~/claude/knowledge-garden/submissions/`
- Before a session that will need to search the garden for existing knowledge

**Step 0 — Drift check**

Read GARDEN.md metadata header:
- `Entries merged since last sweep` — how many entries since last full DEDUPE
- `Drift threshold` — trigger point (default: 10)

If `entries_merged_since_sweep >= drift_threshold`:
  > "The garden has drifted — [N] entries have been added since the last full duplicate sweep (threshold: [T]). Run a full DEDUPE sweep before merging this batch?"
  >
  > Options: **YES** (run DEDUPE now, then continue) / **defer** (merge now, sweep later) / **skip** (merge and reset counter)

**Step 1 — List pending submissions**

```bash
ls ~/claude/knowledge-garden/submissions/
```

**Step 2 — Read each submission** (small, targeted)

Read all submission files. They're compact by design.

**Step 3 — Load GARDEN.md index**

```bash
cat ~/claude/knowledge-garden/GARDEN.md
```

Scan all index sections for entries similar to each submission.

**Step 4 — For likely duplicates: surgical read of relevant section**

```bash
grep -A 30 "## <existing title>" ~/claude/knowledge-garden/<file>.md
```

Don't load entire garden files — read only sections that might overlap.

**Step 4b — Identify REVISE submissions**

Check filenames for "revise" — these need different handling from new entries.

For each REVISE submission:
1. Read the target entry (the section, not the whole file)
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
2. Find same-category existing entries in GARDEN.md index
3. For each candidate: read the first 30 lines of the entry:
   ```bash
   grep -A 30 "## Entry Title" ~/claude/knowledge-garden/<file>.md
   ```
4. Compare: symptom description, root cause keywords, fix approach
5. If similar: present to user — "GE-XXXX [new] looks similar to GE-YYYY [existing] — duplicate, related, or distinct?"
   - **Duplicate** → discard; add to DISCARDED.md; log to CHECKED.md as `duplicate-discarded`
   - **Related** → note cross-references; log to CHECKED.md as `related`
   - **Distinct** → proceed; log to CHECKED.md as `distinct`
6. Log ALL comparisons made to CHECKED.md (even distinct ones)

**Step 6 — Integrate new and related entries**

For new entries: append to the appropriate garden file. Add `**ID:** GE-XXXX` to the entry header immediately after the `## Entry Title` heading. Then update GARDEN.md:

| Entry type | By Technology | By Symptom / Type | By Label |
|---|---|---|---|
| Gotcha | ✅ add | ✅ add under matching symptom category | — |
| Technique | ✅ add | — | ✅ add under each matching label |
| Undocumented | ✅ add | ✅ add (or new "Undocumented" category) | — |

**Verify GE-ID:** Confirm the submission's GE-ID is not already present in the garden index. If it is (race condition), assign the next available ID and note the change.

**Creating a new garden file:** Add the correct header on line 1:
- `# <Technology> Gotchas` / `# <Technology> Techniques` / `# <Technology> Gotchas and Techniques`
- Use tool/library name, not problem-domain name

**Adding a technique:** Ensure the entry has a `**Labels:**` field with at least one label from the Tag Index. Reuse existing tags before inventing new ones.

**Preserve the score:** At the end of each newly integrated entry, append the compact score line from the submission:

```
*Score: 11/15 · Included because: [brief reason] · Reservation: [none / brief reason]*
```

**Step 7 — Remove processed submissions**

```bash
git rm ~/claude/knowledge-garden/submissions/<processed-file>.md
```

**Step 8 — Update GARDEN.md metadata**

- Increment `Entries merged since last sweep` by the number of new entries integrated
- `Last assigned ID` stays as set during submission; verify it matches the highest ID integrated

**Step 9 — Commit**

```bash
cd ~/claude/knowledge-garden
git add .
git commit -m "merge: integrate N submissions — <brief summary>"
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

Read GARDEN.md: enumerate all entries with their GE-IDs, grouped by technology category.
Read CHECKED.md: build the set of already-verified pairs.

**Step 2 — Generate unchecked pairs per category**

For each technology category:
- List all entries in that category
- Generate all within-category pairs
- Exclude pairs already in CHECKED.md
- These are the unchecked pairs to process

Cross-category pairs are never checked — they cannot be duplicates.

**Step 3 — Compare unchecked pairs**

For each unchecked pair, read both entries surgically:

```bash
grep -A 40 "## Entry Title" ~/claude/knowledge-garden/<file>.md
```

Classify:
- **Distinct** — different enough; no action needed
- **Related** — similar but legitimately separate; add cross-references to both entries
- **Duplicate** — one is a subset or copy of the other; propose to user which to keep

**Step 4 — Resolve duplicates and related entries**

For related pairs: add `**See also:** GE-XXXX [title]` to both entries.
For duplicates: present both to user, keep the more complete one, discard the other; record in DISCARDED.md.

**Step 5 — Update CHECKED.md**

Log every comparison:

```markdown
| GE-0003 × GE-0007 | distinct | YYYY-MM-DD | |
| GE-0004 × GE-0008 | related | YYYY-MM-DD | cross-referenced |
| GE-0005 × GE-0009 | duplicate-discarded | YYYY-MM-DD | GE-0005 kept |
```

**Step 6 — Reset drift counter**

Update GARDEN.md metadata:
- `Last full DEDUPE sweep: YYYY-MM-DD`
- `Entries merged since last sweep: 0`

**Step 7 — Commit**

```bash
cd ~/claude/knowledge-garden
git add .
git commit -m "dedupe: sweep N pairs — M related, K duplicates resolved"
```

**Step 8 — Report**

Tell the user:
- How many pairs were checked
- How many were distinct / related / duplicate
- Which garden files were updated

---

## Common Pitfalls

| Mistake | Why It's Wrong | Fix |
|---------|----------------|-----|
| Running MERGE during normal session work | Needs full context budget; deprives active session | Always run harvest as a dedicated session |
| Loading entire garden files during MERGE | Wastes context; only need specific sections | Surgical reads: `grep -A 30 "## Title" file.md` |
| Not checking REVISE filenames before processing | Treats enrichments as new entries | Always check for "revise" in filenames first |
| Adding a second solution without pros/cons | Reader can't choose between approaches | Always use Solution 1 / Solution 2 format when 2+ exist |
| Retroactively reformatting single-solution entries | Unnecessary churn | Only add pros/cons when a second solution arrives |
| REVISE "resolved" entry: deleting the original content | Users on older versions still need the entry | Add "Resolved in: vX.Y" note — never delete |
| Not including "revise" check on submission filenames | Misses REVISE submissions | Always scan filenames for "revise" before processing |
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
- ✅ All submissions classified (new / duplicate / related)
- ✅ New entries appended to appropriate garden files (with correct file header if new file)
- ✅ Technique entries have `**Labels:**` field in the content file
- ✅ GARDEN.md updated: By Technology always; By Symptom/Type for gotchas; By Label for techniques
- ✅ New labels added to Tag Index if used
- ✅ GE-IDs verified from submission filenames/headers; added as `**ID:**` in entry headers and index
- ✅ GARDEN.md metadata updated: `Entries merged since last sweep` incremented
- ✅ Medium duplicate check (section read) performed; results logged in CHECKED.md
- ✅ Discarded submissions recorded in DISCARDED.md
- ✅ DEDUPE offered if drift threshold exceeded
- ✅ Processed submissions removed
- ✅ Committed with `merge:` format

DEDUPE is complete when:
- ✅ All within-category unchecked pairs processed
- ✅ CHECKED.md updated with all results
- ✅ Related entries have cross-references
- ✅ Duplicate entries resolved (user confirmed which to keep)
- ✅ GARDEN.md drift counter reset
- ✅ Committed with `dedupe:` format

---

## Skill Chaining

**Invoked by:** User directly for maintenance sessions ("merge garden submissions", "harvest the garden", "dedupe the garden")

**Invoked after:** `forage` sessions accumulate submissions — forage tells users to "run harvest when convenient"

**Does NOT handle:** CAPTURE, SWEEP, SEARCH, REVISE — those are forage operations.

**Reads from:**
- `~/claude/knowledge-garden/GARDEN.md` — index and metadata
- `~/claude/knowledge-garden/CHECKED.md` — for MERGE (light duplicate check) and DEDUPE
- `~/claude/knowledge-garden/submissions/` — all pending submissions
- Garden detail files — surgical section reads during MERGE and DEDUPE

**Garden location:** `~/claude/knowledge-garden/`
**Submission format:** Processes both forage submissions and legacy garden submissions (identical format).
