---
name: forage
description: >
  Use when non-obvious technical knowledge surfaces during session work — bugs whose symptoms
  mislead about root cause, tools that contradict documentation, silent failures with no error,
  workarounds found only via multiple failed approaches, techniques a skilled developer wouldn't
  naturally reach for. Session-time operations: CAPTURE (specific entry), SWEEP (systematic session
  scan), SEARCH (retrieve entries), REVISE (enrich existing entry). For MERGE and DEDUPE use harvest.
---

# Forage — Session-Time Garden Operations

A cross-project, machine-wide library of hard-won technical knowledge —
three kinds of entries:

- **Gotchas** — bugs that silently fail, behaviours that contradict documentation, and workarounds that took hours to find
- **Techniques** — the umbrella for all non-obvious positive knowledge: specific how-to methods, strategic design philosophy, cross-cutting patterns. A skilled developer wouldn't naturally reach for it, but would immediately value it once shown.
- **Undocumented** — behaviours, options, or features that exist and work but simply aren't written down anywhere; only discoverable via source code, trial and error, or word of mouth

Stored at `~/claude/knowledge-garden/` so any Claude instance on this machine can read and contribute to it.

**Forage handles session-time operations only: CAPTURE, SWEEP, SEARCH, REVISE.**
For MERGE and DEDUPE (integrating submissions into the garden), use the `harvest` skill.

**Proactive OFFER rule:** When conditions match the CSO description but the user didn't ask — offer in 2 sentences and wait for confirmation before engaging any workflow.

**The bar for gotchas:** Would a skilled developer, familiar with the technology, still have spent significant time on this problem? If yes — it belongs.

**The bar for techniques:** Would a skilled developer be surprised this approach exists, or would they have reached for something more complex? If yes — it belongs.

**The bar for undocumented:** Does it exist, does it work, and would you have no reasonable way to discover it from the official docs? If yes — it belongs.

---

## What This Is Not

- **Not an idea log** — ideas go in `idea-log`
- **Not an ADR** — architecture decisions go in `adr`
- **Not how-to content** — step-by-step tutorials for standard documented APIs don't belong; the distinction is *non-obvious* knowledge vs *documented* knowledge
- **Not project-specific** — if it says "in ProjectX, the foo() method..." skip it; if it says "JavaParser's getByName() only searches top-level types..." it does
- **Not expected errors** — if it's in the docs with the fix, skip it
- **Not transient issues** — network flakes, temporary rate limits
- **Not general best practices** — "always validate input" isn't a technique; "you can use X to avoid Y in context Z in a way most people don't know about" is
- **Not documented behaviour presented as undocumented** — if it's in the official docs (even buried), it's not undocumented; the bar is genuinely absent from any documentation

---

## Garden Structure

```
~/claude/knowledge-garden/
├── GARDEN.md                   ← metadata header (Last assigned ID, drift counter)
├── CHECKED.md                  ← duplicate check pair log
├── DISCARDED.md                ← discarded duplicates
├── submissions/                ← incoming entries from any Claude session
│   └── YYYY-MM-DD-<project>-GE-XXXX-<slug>.md
├── tools/                      ← cross-domain tools, techniques, and patterns
├── quarkus/
├── java/
├── intellij-platform/
└── <tech-category>/
    └── <topic>.md
```

**`submissions/`** is how all Claude sessions contribute. Write first, deduplicate with harvest later.

---

## The Submission Model

**Why submissions instead of direct writes:**

Reading garden files to check for duplicates costs the submitting Claude's context window. The solution: **write first, deduplicate with harvest.**

- **Forage** writes a self-contained submission file. Cheap. No garden files read unless already in context.
- **Harvest** is a dedicated session whose whole job is reading submissions and integrating them. It has full budget for the merge.

**The only exception:** If forage already has a garden file in context (because it searched the garden earlier in the same session), it should use that existing awareness to avoid an obvious duplicate.

**Submission format:** See [submission-formats.md](submission-formats.md) for complete templates (gotcha, technique, undocumented, revise), scoring dimensions, and post-merge entry format.

**Score thresholds:**

| Score | Decision |
|-------|----------|
| 12–15 | **Strong include** — no question |
| 8–11 | **Include** — "case for" should outweigh "case against" |
| 5–7 | **Borderline** — needs a compelling "case for" |
| <5 | **Don't submit** |

---

## Workflows

### CAPTURE (write a submission — default operation)

**Step 0 — Assign GE-ID (before anything else)**

1. Read the current counter:
   ```bash
   grep "Last assigned ID" ~/claude/knowledge-garden/GARDEN.md
   ```
2. Increment by 1. Pad to 4 digits: GE-0001, GE-0042, GE-0100.
3. Update GARDEN.md immediately:
   ```bash
   # Update "Last assigned ID: GE-XXXX" → "Last assigned ID: GE-YYYY"
   ```
4. Stage the GARDEN.md change — it will be committed with the submission in Step 7.

**Race condition note:** If two Claudes submit simultaneously, one git commit will conflict on GARDEN.md. The loser must rebase: re-read the counter, take the next ID, update their submission file and filename, and re-commit.

**Step 1 — Classify, score, and filter**

First, classify the type:
- **gotcha** — something that went wrong in a non-obvious way
- **technique** — a non-obvious approach that worked
- **undocumented** — something that exists and works but isn't in the docs

Is it cross-project? (Not tied to one specific codebase's logic.) If no → skip.

Compute the Garden Score (see [submission-formats.md](submission-formats.md)):
- **12–15** → offer confidently
- **8–11** → offer with brief framing
- **5–7** → only offer if case for is genuinely compelling
- **<5** → don't submit

**Step 1b — Light duplicate check (index scan only)**

Before drafting, do a quick scan for obvious conflicts:

1. Extract the technology/stack from the entry being prepared
2. Read GARDEN.md index — find entries in the same technology category
3. Compare titles: if any existing entry title is very similar, flag it
   - If same thing → stop; offer REVISE instead
   - If different → proceed; note which IDs were checked (for CHECKED.md update in Step 7)
4. Do NOT read garden detail files — index only.

**Step 2 — Duplicate awareness check (context only, no reads)**

Ask: is any garden content already in context from this session?
- Searched the garden earlier → if the new knowledge **enriches** an existing entry → pivot to **REVISE**
- Already submitted this entry this session → skip it
- Neither → proceed without reading anything

**Step 3 — Extract the 8 fields from conversation context**

Work from what's already known. Ask only for what's genuinely unclear.

| Field | Extract from |
|-------|-------------|
| Title | The surprising thing itself |
| Stack | Tools, libraries, versions mentioned |
| Symptom | What was observed / error messages |
| Context | When it occurs, what setup triggers it |
| What was tried | Failed approaches in the session |
| Root cause | The diagnosis reached |
| Fix | The working solution with code |
| Why non-obvious | Why the obvious approach failed |

**Step 4 — Determine the suggested target (don't read, just reason)**

Based on the technology stack, suggest the likely destination:

| Technology | Suggested target |
|-----------|-----------------|
| AppKit, WKWebView, NSTextField | `macos-native-appkit/appkit-panama-ffm.md` |
| Panama FFM, jextract, upcalls | `java-panama-ffm/native-image-patterns.md` |
| GraalVM native image | `graalvm-native-image/<topic>.md` |
| Quarkus | `quarkus/<topic>.md` |
| Git, tmux, Docker, CLI tools | `tools/<tool>.md` |
| Techniques spanning multiple technologies | `tools/<problem-domain>.md` |
| Doesn't fit existing | `<new-descriptive-dir>/<topic>.md` |

This is a hint only — harvest decides final placement.

**Step 5 — Draft and confirm**

Draft the submission using the template in [submission-formats.md](submission-formats.md). Show it to the user:
> "Does this capture it accurately?"

Wait for confirmation before writing.

**Step 6 — Write the submission file**

```bash
mkdir -p ~/claude/knowledge-garden/submissions
# write YYYY-MM-DD-<project>-GE-XXXX-<slug>.md
```

**Step 7 — Commit**

```bash
cd ~/claude/knowledge-garden
git add submissions/ GARDEN.md  # GARDEN.md because counter was updated
git commit -m "submit(<project>): GE-XXXX '<short title>'"
```

**Step 8 — Report back**

Tell the user the submission file path and that it will be merged in the next harvest session.

---

### SWEEP (scan the current session for all three entry types)

Use when: "sweep", "garden sweep", "scan for garden entries", or at the end of a session.

Unlike CAPTURE (where you provide the specific knowledge), SWEEP reviews the session from conversation memory and proposes findings. It covers all three categories explicitly.

**Step 1 — Scan for Gotchas** (non-obvious things that went wrong)

Review the session for:
- Bugs whose symptom misled about the root cause
- Silent failures with no error or warning
- Things that required multiple failed approaches before the fix
- Workarounds for things that "should" work but don't

For each candidate, compute the Garden Score then present:
*"During this session we hit [X] — the symptom was [Y] but the actual cause was [Z]. Scored [N]/15 — worth submitting as a gotcha?"*

**Step 2 — Scan for Techniques** (non-obvious approaches that worked)

Review the session for:
- Solutions a skilled developer wouldn't naturally reach for
- Tool or API combinations used in undocumented or unexpected ways
- Patterns that solved a problem more elegantly than expected

For each candidate, compute the Garden Score then present:
*"We used [approach] to [achieve outcome] — most developers would have [done it the hard way]. Scored [N]/15 — worth submitting as a technique?"*

**Step 3 — Scan for Undocumented** (exists but isn't in any docs)

Review the session for:
- Flags, options, or behaviours only discoverable via source code
- Features that work but have no official documentation
- Things discovered through trial and error or commit history

For each candidate, compute the Garden Score then present:
*"We discovered [X] — it exists and works but there's no documentation for it. Scored [N]/15 — worth submitting as undocumented?"*

**Score threshold during SWEEP:** Only propose candidates scoring ≥8.

**Step 4 — Submit confirmed entries**

For each finding confirmed by the user: run the CAPTURE workflow with the specific content already known from context. Do NOT ask the user to re-describe things you already know.

**Step 5 — Report**

Tell the user:
- How many candidates were found in each category
- How many were confirmed and submitted
- If nothing was found: "Nothing garden-worthy surfaced in this session across gotchas, techniques, or undocumented items."

---

### REVISE (submit an enrichment to an existing entry)

Use when new knowledge enriches an existing garden entry rather than standing alone: a solution surfaces for a previously-unsolved gotcha, an alternative approach is found, additional context emerges, or an entry's status changes.

**Step 1 — Identify the target entry**

If the entry is already in context from this session, use that knowledge directly. If you need to find it:
```bash
grep -r "keywords" ~/claude/knowledge-garden/ --include="*.md" \
  --exclude-dir=submissions -l
```
Then read only the specific entry:
```bash
grep -A 60 "## Entry Title" ~/claude/knowledge-garden/<path>.md
```

**Step 2 — Determine the revision kind**

| Situation | Kind |
|-----------|------|
| Gotcha had no fix — now there's a real fix | `solution` |
| Entry has one solution — found a different approach | `alternative` |
| Same pattern in a different context | `variant` |
| Additional context, edge cases, or discovery | `update` |
| Bug fixed in a newer version | `resolved` |
| Feature removed or approach obsolete | `deprecated` |

**Step 3 — Draft and confirm**

Use the REVISE template in [submission-formats.md](submission-formats.md). Show it to the user. Wait for confirmation.

**Step 4 — Write the submission file**

Include "revise" in the filename so harvest identifies it immediately:
```
YYYY-MM-DD-<project>-GE-XXXX-revise-<entry-slug>.md
```
(GE-XXXX is this revision's own assigned ID, not the target's ID.)

**Step 5 — Commit**

```bash
cd ~/claude/knowledge-garden
git add submissions/ GARDEN.md
git commit -m "submit(<project>): GE-XXXX revise '<entry title>' — <what's new>"
```

---

### SEARCH (retrieving entries)

1. Read `~/claude/knowledge-garden/GARDEN.md` — check all index sections
2. Follow the file link for full detail
3. If not in the index:
   ```bash
   grep -r "keywords" ~/claude/knowledge-garden/ --include="*.md" \
     --exclude-dir=submissions
   ```
4. Return the full entry (Symptom + Root Cause + Fix + Why Non-obvious)
5. If the user just fixed something related, offer to submit the new knowledge via CAPTURE

---

## Proactive Trigger

Fire **without being asked** when:

**For gotchas:**
- Multiple approaches were tried before the fix was found
- The documented approach didn't work
- Something works in one context but silently fails in another
- The user says: "that took way too long", "I'd never have guessed that", "weird behaviour"

**For techniques:**
- A non-obvious approach was used that solved a problem more elegantly than expected
- A combination of tools or APIs was used in an undocumented way
- The user says: "that's a neat trick", "I didn't know you could do that", "this should be documented"

**For undocumented:**
- A flag, option, or behaviour was found by reading source code, not docs
- Something works but there's no official explanation
- The user says: "this isn't in the docs", "I only found this in the source"

Offer, don't assume — and name the type:
> "This was non-obvious — want me to submit it to the garden as a [gotcha / technique / undocumented]?"

**Also fire for REVISE** when a solution surfaces for a previously-unsolved gotcha, or an alternative approach is found:
> "This looks like a solution to an existing garden entry — want me to submit a REVISE to enrich '[entry title]' with the fix?"

---

## Common Pitfalls

| Mistake | Why It's Wrong | Fix |
|---------|----------------|-----|
| Reading garden files to check for duplicates during CAPTURE | Burns context budget; garden grows, cost grows | Write the submission; let harvest handle deduplication |
| Skipping the submission and writing directly to garden files | Reintroduces the read-for-dedup problem | Always use submissions/ for new entries |
| Not including "Suggested target" in submission | Harvest has to infer from scratch | Include the likely destination as a hint |
| Omitting **Type: gotcha / technique / undocumented** in submission | Harvest can't categorise correctly | Always declare the type |
| Gotcha: title describes the fix not the weird thing | Can't find it by symptom | Title = the surprising behaviour, not the solution |
| Gotcha: fix has no code | Useless in 6 months | Complete, runnable code or config required |
| Technique: no "why non-obvious" section | Just becomes documentation | Must explain what developers would normally do instead |
| Not including "revise" in the REVISE submission filename | Harvest has to infer from content | Always include "revise" in the filename slug |
| SWEEP: asking the user what was discovered | Claude has the context; user shouldn't re-explain | Scan session memory and propose specific candidates |
| SWEEP: only checking gotchas | Techniques and undocumented items are easy to miss | Always check all three categories explicitly |
| Forgetting to run harvest periodically | Submissions accumulate, garden stays stale | Harvest after 3–5 submissions, or before a search-heavy session |
| Omitting GE-ID from submission filename or header | Harvest can't reconcile with CHECKED.md | Always assign GE-ID in CAPTURE Step 0; embed in filename |
| Forgetting to commit GARDEN.md with the submission | Counter drifts; next submitter picks a duplicate ID | Stage both submissions/ and GARDEN.md in Step 7 |

---

## Success Criteria

CAPTURE is complete when:
- ✅ GE-ID assigned and recorded in GARDEN.md counter before submission written
- ✅ Filename includes GE-ID: `YYYY-MM-DD-<project>-GE-XXXX-<slug>.md`
- ✅ Submission header includes `**Submission ID:** GE-XXXX`
- ✅ Light duplicate check (index scan) performed; scanned IDs noted
- ✅ No garden detail files were read specifically for duplicate detection
- ✅ User confirmed the draft before writing
- ✅ GARDEN.md committed alongside submission (counter update)
- ✅ Committed with `submit(<project>): GE-XXXX '<title>'` format

SWEEP is complete when:
- ✅ All three categories checked from session memory (gotchas, techniques, undocumented)
- ✅ Each finding proposed explicitly with type and description
- ✅ Confirmed entries submitted via CAPTURE
- ✅ Report given: N found, M submitted per category

REVISE is complete when:
- ✅ Submission file written with "revise" in the filename
- ✅ Target entry path and exact title specified
- ✅ Revision kind declared
- ✅ User confirmed the draft before writing
- ✅ Committed with `submit(<project>): revise '<title>' — <what's new>` format

SEARCH is complete when:
- ✅ Full entry returned for any matching bugs
- ✅ grep run (excluding submissions/) if topic not in index

---

## Skill Chaining

**Invoked by:** `session-handover` — garden SWEEP is Step 2b of the wrap checklist; user directly ("submit to the garden", "add this to the garden", "forage CAPTURE")

**Chains to:** `harvest` — for MERGE and DEDUPE (integrating submissions into the garden)

**Reads from:**
- `~/claude/knowledge-garden/GARDEN.md` — for SEARCH and counter reads
- Garden detail files — SEARCH only, surgical section reads; never for duplicate checking during CAPTURE

**Does NOT handle:** MERGE, DEDUPE — those are harvest operations.

**Garden location:** `~/claude/knowledge-garden/`
**Submission format:** Identical to the `garden` skill — harvest processes both.
