---
name: forage
description: >
  Use when non-obvious technical knowledge surfaces during session work — bugs whose symptoms
  mislead about root cause, tools that contradict documentation, silent failures with no error,
  workarounds found only via multiple failed approaches, techniques a skilled developer wouldn't
  naturally reach for. Session-time operations: CAPTURE (specific entry), SWEEP (systematic session
  scan), SEARCH (retrieve entries), REVISE (enrich existing entry). For DEDUPE use harvest.
---

# Forage — Session-Time Garden Operations

A cross-project, machine-wide library of hard-won technical knowledge —
three kinds of entries:

- **Gotchas** — bugs that silently fail, behaviours that contradict documentation, and workarounds that took hours to find
- **Techniques** — the umbrella for all non-obvious positive knowledge: specific how-to methods, strategic design philosophy, cross-cutting patterns. A skilled developer wouldn't naturally reach for it, but would immediately value it once shown.
- **Undocumented** — behaviours, options, or features that exist and work but simply aren't written down anywhere; only discoverable via source code, trial and error, or word of mouth

Stored at `${HORTORA_GARDEN:-~/.hortora/garden}/` so any Claude instance on this machine can read and contribute to it.

**Forage handles session-time operations only: CAPTURE, SWEEP, SEARCH, REVISE.**
For DEDUPE (finding duplicates across existing entries), use the `harvest` skill.

**Proactive OFFER rule:** When conditions match the CSO description but the user didn't ask — offer in 2 sentences and wait for confirmation before engaging any workflow.

**The bar for gotchas:** Would a skilled developer, familiar with the technology, still have spent significant time on this problem? If yes — it belongs.

**The bar for techniques:** Would a skilled developer be surprised this approach exists, or would they have reached for something more complex? If yes — it belongs.

**The bar for undocumented:** Does it exist, does it work, and would you have no reasonable way to discover it from the official docs? If yes — it belongs.

---

## Git-Only Access Model

**All reads come from git HEAD. The filesystem is a staging area only.**

```bash
GARDEN=${HORTORA_GARDEN:-~/.hortora/garden}

# Read a committed file (always use this, never cat/read directly)
git -C $GARDEN show HEAD:GARDEN.md
git -C $GARDEN show HEAD:tools/GE-0002.md

# Search committed content
git -C $GARDEN grep "keywords" HEAD -- '*.md' ':!GARDEN.md' ':!CHECKED.md' ':!DISCARDED.md'
```

**Why:** Direct filesystem reads can see partial writes from other sessions. `git show HEAD:path` always returns complete, committed state.

**The commit is the write.** After writing any file to the filesystem, immediately `git add` and `git commit`. Never leave garden files in an uncommitted state.

**Conflict recovery:** If a commit fails because another session committed first:
```bash
git -C $GARDEN rebase HEAD
# Re-commit
```

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
${HORTORA_GARDEN:-~/.hortora/garden}/
├── GARDEN.md                   ← index (By Technology, By Symptom/Type, By Label)
├── CHECKED.md                  ← duplicate check pair log
├── DISCARDED.md                ← discarded duplicates
├── tools/                      ← cross-domain tools, techniques, and patterns
│   └── GE-YYYYMMDD-xxxxxx.md  ← one file per entry, YAML frontmatter
├── quarkus/
├── java/
└── <tech-category>/
    └── GE-YYYYMMDD-xxxxxx.md
```

Every entry is a standalone file with YAML frontmatter. There is no `submissions/` queue — forage writes entries directly to their domain directory.

---

## Entry Format

All entries use YAML frontmatter. See [submission-formats.md](submission-formats.md) for complete templates.

**Required frontmatter fields:**
```yaml
---
id: GE-YYYYMMDD-xxxxxx
title: "Short descriptive title"
type: gotcha | technique | undocumented
domain: tools          # directory name (tools, quarkus, java, etc.)
stack: "Technology, Version"
tags: [tag1, tag2]
score: N               # must be ≥8 to pass validation
verified: true
staleness_threshold: 730
submitted: YYYY-MM-DD
---
```

**Score thresholds:**

| Score | Decision |
|-------|----------|
| 12–15 | **Strong include** — no question |
| 8–11 | **Include** — "case for" should outweigh "case against" |
| 5–7 | **Borderline** — needs a compelling "case for" |
| <5 | **Don't submit** |

---

## Workflows

### CAPTURE (write an entry — default operation)

**Step 0 — Assign GE-ID**

Generate locally — no external counter needed:
```bash
GE_ID="GE-$(date +%Y%m%d)-$(python3 -c "import secrets; print(secrets.token_hex(3))")"
# e.g. GE-20260410-a3f7c2
```

Format: `GE-YYYYMMDD-xxxxxx` (date + 6 lowercase hex chars). Collision probability is negligible at any realistic garden scale. See ADR-0003 for rationale.

**Step 1 — Classify, score, and filter**

Classify the type: **gotcha**, **technique**, or **undocumented**.

Is it cross-project? (Not tied to one specific codebase's logic.) If no → skip.

Compute the Garden Score (see [submission-formats.md](submission-formats.md)):
- **12–15** → offer confidently
- **8–11** → offer with brief framing
- **5–7** → only offer if case for is genuinely compelling
- **<5** → don't submit

**Step 1b — Light duplicate check (index scan only)**

Before drafting, scan the committed index for obvious conflicts:

```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} show HEAD:GARDEN.md
```

Find entries in the same technology category. Compare titles:
- If same thing → stop; offer REVISE instead
- If different → proceed

Do NOT read garden detail files — index only.

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
| verified_on | For library/tool-specific entries only (type gotcha or undocumented with a named stack version): version(s) this was verified on — e.g. "quarkus: 3.34.2". Extract from context if mentioned. Skip for technique/cross-cutting entries. |
| rationale | For entries scoring ≥12: why this fix over the obvious alternative. Extract from context if already explained; otherwise prompt in Step 5. |
| author | Read from `~/.claude/settings.json` `initials` field. Set automatically — do not ask the user unless `initials` is not set (see Step 6). |
| constraints | What conditions must hold for this fix to apply — environment, version, architecture. Extract from context if mentioned; otherwise prompt in Step 5. |
| alternatives_considered | What else was tried/evaluated and why rejected. Extract from session context — the "What was tried (didn't work)" section often contains this. |
| invalidation_triggers | What changes would make this entry wrong — library updates, deprecations, architectural shifts. Extract if mentioned; otherwise prompt in Step 5. |

**For patterns-garden entries**, also extract these optional fields from context:

| Field | Extract from |
|-------|-------------|
| `observed_in` | Projects where this pattern was observed in the session — name, URL, path if mentioned |
| `suitability` | Any discussion of when the pattern works and when it doesn't |
| `variants` | Named adaptations discussed (e.g. in-memory vs event-sourced) |
| `variant_frequency` | Any frequency or adoption counts mentioned |
| `authors` | Developer names or GitHub handles attributed to the pattern |
| `stability` | Any discussion of how widely or consistently the pattern is used across projects |

These fields are optional — include only what's known from context. Do not ask the user to supply them if they weren't discussed.

**Step 4 — Determine the garden and domain**

First, select the garden based on knowledge type:

| Knowledge type | Garden |
|---------------|--------|
| Non-obvious behaviour, silent failure, undocumented feature | `discovery` |
| Reusable architectural or structural solution | `patterns` |
| Minimal working code example, copy-paste ready | `examples` |
| Breaking change, deprecation, or new capability in a version | `evolution` |
| Production failure mode, anti-pattern, or incident pattern | `risk` |
| Architectural or technology choice with alternatives considered | `decisions` |

**Editorial bar per garden:**

| Garden | Bar |
|--------|-----|
| `discovery` | Would a skilled developer familiar with the technology still have spent significant time on this? |
| `patterns` | Would a practitioner reach for something more complex or less elegant without this pattern? |
| `examples` | Is this minimal, working, and demonstrating a real use case — not a toy? |
| `evolution` | Does this describe a breaking change, deprecation, or capability shift that would change code correctness for someone on that version? |
| `risk` | Has this failure mode caused production harm at meaningful scale, and is the mechanism universal enough to recur? |
| `decisions` | Does this capture the reasoning clearly enough that someone facing the same choice could apply it — including what was rejected and why? |

Then, select the coarse domain (Qdrant partition key):

| Technology | Domain |
|-----------|--------|
| AppKit, WKWebView, NSTextField | `macos-native-appkit` |
| Panama FFM, jextract, GraalVM native | `java-panama-ffm` |
| Quarkus, Java, Drools, JVM | `jvm` |
| Python | `python` |
| Git, tmux, Docker, CLI tools, cross-cutting patterns | `tools` |
| Web, frontend, Node.js | `web` |
| Databases, data pipelines | `data` |
| Cloud platforms, Kubernetes | `cloud` |
| Security tooling | `security` |
| Doesn't fit existing | `<new-descriptive-dir>` |

Include `garden: <garden>` as the first field after `id` in the entry frontmatter.

**Step 5 — Draft and confirm**

Draft the entry using the YAML frontmatter template in [submission-formats.md](submission-formats.md). Show it to the user:
> "Does this capture it accurately?"

**For library/tool-specific entries** (type gotcha or undocumented with a named stack version), if `verified_on` is not already known from context, ask:
> "What version was this verified on? (e.g. 'quarkus: 3.34.2' — or press Enter to skip)"

If provided, include as a YAML frontmatter field after `staleness_threshold`:
```yaml
staleness_threshold: 730
verified_on: "quarkus: 3.34.2"
submitted: YYYY-MM-DD
```

**For entries scoring 12 or above**, ask:
> "Optionally: why this fix over the obvious alternative? (Enter to skip)"

If provided, add a `### Why this fix` body section immediately after `### Why this is non-obvious`:
```markdown
### Why this fix
[Submitter's rationale — why this approach over the obvious alternative]
```

**For all entries**, prompt for WHY context fields — each is optional but earns a +1 bonus on the effective score:

> "What constraints must hold for this fix to apply? (e.g. 'requires Java 17+, not applicable to reactive pipelines' — or press Enter to skip)"

If provided, add `constraints: "<text>"` to YAML frontmatter.

> "What alternatives did you consider and reject? (Enter to skip — or describe briefly)"

If provided, add a `### Alternatives considered` body section with a bulleted list.

> "What changes would invalidate this entry? (e.g. 'revisit if Spring Boot 4.0 ships' — or press Enter to skip)"

If provided, add `invalidation_triggers: "<text>"` to YAML frontmatter.

Each WHY field present adds +1 to the effective score reported by the validator (base gate of ≥8 still applies to self-reported score only).

Wait for confirmation before writing.

**Step 6 — Write the entry file**

**Set author field:** Read `initials` from `~/.claude/settings.json`. If set, include `author: "<initials>"` in YAML frontmatter. If not set, prompt once:
> "What initials should identify your garden entries on the contributor scoreboard? (e.g. 'mdp')"
Save the answer to `~/.claude/settings.json` as `"initials": "<answer>"` and include `author: "<answer>"` in frontmatter.

```bash
GARDEN=${HORTORA_GARDEN:-~/.hortora/garden}
# write $GARDEN/<domain>/$GE_ID.md with YAML frontmatter + body
```

**Step 7 — Validate**

```bash
python3 ${SOREDIUM_PATH:-~/claude/hortora/soredium}/scripts/validate_pr.py \
  ${HORTORA_GARDEN:-~/.hortora/garden}/<domain>/$GE_ID.md \
  ${HORTORA_GARDEN:-~/.hortora/garden}
```

Fix any CRITICAL issues before continuing.

**Step 8 — Deliver**

Detect the garden's remote:
```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} remote get-url origin 2>/dev/null
```

**If the URL contains `github.com`** → commit directly to main and push:
```bash
GARDEN=${HORTORA_GARDEN:-~/.hortora/garden}
git -C $GARDEN add <domain>/$GE_ID.md
git -C $GARDEN commit -m "submit($GE_ID): <slug>"
git -C $GARDEN pull --rebase origin main
git -C $GARDEN push origin main
```

**If no GitHub remote** → commit directly to main:
```bash
GARDEN=${HORTORA_GARDEN:-~/.hortora/garden}
git -C $GARDEN add <domain>/$GE_ID.md
git -C $GARDEN commit -m "submit($GE_ID): <slug>"
```

**Step 9 — Check for other untracked entries**

Before reporting back, scan for any other untracked entry files in the garden:

```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} ls-files --others --exclude-standard \
  | grep -E "^[^/]+/GE-[0-9]{8}-[0-9a-f]{6}\.md$"
```

If any appear, offer to commit them immediately before they can be lost by a future branch operation:
> "There are N other untracked entry files in the garden — want me to commit them now?"

If confirmed, stage and commit them in a single commit alongside any GARDEN.md index updates needed.

**Step 10 — Report back**

Tell the user the entry path and confirm it was pushed to main.

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

**Step 4 — Submit confirmed entries (batched delivery)**

For each confirmed entry, run CAPTURE steps 0–6 (GE-ID generation through writing the file). Work from session context — do NOT ask the user to re-describe things you already know. Track the list of written entry paths as you go.

After all entry files are written, validate and deliver as a single batch:

**Validate**

If 3 or more entries were written, run validation in parallel (faster for typical 6–8 entry sweeps):
```bash
GARDEN=${HORTORA_GARDEN:-~/.hortora/garden}
for ENTRY_PATH in <list of written entry paths>; do
  python3 ${SOREDIUM_PATH:-~/claude/hortora/soredium}/scripts/validate_pr.py \
    "$ENTRY_PATH" "$GARDEN" &
done
wait
```

If fewer than 3, validate sequentially (same command without `&`).

Fix any CRITICAL issues before continuing.

**Deliver**

Detect the garden's remote:
```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} remote get-url origin 2>/dev/null
```

**GitHub remote** — single commit to main and push:
```bash
GARDEN=${HORTORA_GARDEN:-~/.hortora/garden}
git -C $GARDEN add <all written entry files>
git -C $GARDEN commit -m "sweep: <N> entries — <slug1>, <slug2>, ..."
git -C $GARDEN pull --rebase origin main
git -C $GARDEN push origin main
```

**No GitHub remote** — single commit to main:
```bash
GARDEN=${HORTORA_GARDEN:-~/.hortora/garden}
git -C $GARDEN add <all written entry files>
git -C $GARDEN commit -m "sweep: <N> entries — <slug1>, <slug2>, ..."
```

**Step 5 — Staleness spot-check (domain-filtered)**

Derive session domains from:
- The `domain` field of entries submitted in Steps 1–4 of this SWEEP
- Technology stacks mentioned in the session conversation (Quarkus → `quarkus`, tmux → `tools`, etc.)

If no domains can be identified from either source, skip this step entirely.

Otherwise:

1. Read the committed index:
   ```bash
   git -C ${HORTORA_GARDEN:-~/.hortora/garden} show HEAD:GARDEN.md
   ```

2. For each entry in the By Technology section whose domain is in the session domain set:
   - Read the entry's YAML frontmatter (head only):
     ```bash
     git -C ${HORTORA_GARDEN:-~/.hortora/garden} show HEAD:<domain>/GE-XXXX.md | head -20
     ```
   - Compute `reference_date = max(submitted, last_reviewed)` if `last_reviewed` present, else `submitted`
   - If `(today - reference_date).days > staleness_threshold`: add to overdue list

3. For each overdue entry, present to the user:
   > ⚠️ **GE-XXXX** "[title]" — {N} days old (threshold {T} days).
   > **Confirm** still valid / **Revise** / **Retire** / **Skip**?

   - **Confirm**: add `last_reviewed: YYYY-MM-DD` to YAML frontmatter in working tree. Commit after all responses collected.
   - **Revise**: run the REVISE workflow for this entry.
   - **Retire**: run REVISE with `deprecated` kind — add `**Deprecated:** [reason] — {date}` near the top of the entry body.
   - **Skip**: no action.

4. If any entries were Confirmed: commit all `last_reviewed` additions atomically:
   ```bash
   git -C ${HORTORA_GARDEN:-~/.hortora/garden} add .
   git -C ${HORTORA_GARDEN:-~/.hortora/garden} commit -m "review: staleness spot-check — N confirmed, M revised, K retired"
   ```

If no overdue entries are found in session domains, omit this step from the report entirely (no noise for fresh gardens).

**Step 6 — Report**

Tell the user:
- How many candidates were found in each category
- How many were confirmed and submitted
- If staleness spot-check ran: N overdue entries found in session domains, M resolved
- If nothing was found: "Nothing garden-worthy surfaced in this session across gotchas, techniques, or undocumented items."

---

### IMPORT (from project-level docs)

Use when importing from `BUGS-AND-ODDITIES.md` or similar project-level bug/quirk documents.

1. Read the source document
2. For each entry, classify **CROSS-PROJECT** or **PROJECT-LOCAL**
3. Show classifications, ask for confirmation
4. For cross-project entries: run the CAPTURE flow per entry
5. Report: N entries written, M skipped as project-specific

---

### REVISE (enrich an existing entry in-place)

Use when new knowledge enriches an existing garden entry rather than standing alone: a solution surfaces for a previously-unsolved gotcha, an alternative approach is found, additional context emerges, or an entry's status changes.

Unlike CAPTURE, REVISE modifies the target entry directly — no separate file is created.

**Step 1 — Identify the target entry**

If already in context, use that knowledge directly. Otherwise search:

```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} grep "keywords" HEAD -- '*.md' \
  ':!GARDEN.md' ':!CHECKED.md' ':!DISCARDED.md'
```

Read the full entry from committed state:
```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} show HEAD:<domain>/GE-XXXX.md
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

**Step 3 — Draft the modification and confirm**

Draft the specific change to the target entry body. Show it to the user. Wait for confirmation before writing.

See [submission-formats.md](submission-formats.md) for how to apply each revision kind and the Multiple Solutions format.

**Step 4 — Apply the revision directly to the target entry**

Edit the target entry file in the working tree. Apply based on revision kind:

| Kind | How to apply |
|------|-------------|
| `solution` | If Fix says "None known": replace with the fix. If Fix already has a solution: restructure into **Solution 1 / Solution 2** with pros/cons for each (see below). |
| `alternative` | Add `### Alternative — [brief name]` after the existing Fix/Solution section with pros/cons. |
| `variant` | Add `## Variant — [context]` section within the file. |
| `update` | Append to the relevant section (Root cause, Context, Caveats, etc.). |
| `resolved` | Add `**Resolved in: vX.Y** — [brief note]` after the **Stack** line; keep entry intact. |
| `deprecated` | Add `**Deprecated:** [reason and date]` near the top; keep the entry for historical reference. |

**Multiple Solutions structure** (only when 2 or more solutions exist):

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

Single solutions never get pros/cons. Only restructure when a second solution is being added.

**REVISE "resolved" entry:** Never delete the original content — users on older versions still need it. Add the resolved note and keep everything else.

**Step 5 — Validate and deliver**

Validate:
```bash
python3 ${SOREDIUM_PATH:-~/claude/hortora/soredium}/scripts/validate_pr.py \
  ${HORTORA_GARDEN:-~/.hortora/garden}/<domain>/GE-XXXX.md \
  ${HORTORA_GARDEN:-~/.hortora/garden}
```

Then deliver the same way as CAPTURE Step 8: PR (GitHub remote) or direct commit to main (local).

Commit message: `revise(GE-XXXX): <revision-kind> — <brief description>`

---

### SEARCH (retrieving entries)

**Session start** — pull latest index changes before searching:
```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} pull --filter=blob:none
```

**Single-garden search workflow** (no `garden-config.toml`, or single garden configured):

1. Read the committed index:
   ```
   Read: ${HORTORA_GARDEN:-~/.hortora/garden}/GARDEN.md
   ```
   Check By Technology, By Symptom/Type, and By Label sections.

2. Read the specific entry:
   ```bash
   git -C ${HORTORA_GARDEN:-~/.hortora/garden} cat-file blob HEAD:<domain>/GE-XXXX.md
   ```

3. If not in the index, search committed content:
   ```bash
   git -C ${HORTORA_GARDEN:-~/.hortora/garden} grep "keywords" HEAD -- '*.md' \
     ':!GARDEN.md' ':!CHECKED.md' ':!DISCARDED.md'
   ```

4. Return the full entry.

5. Append a staleness annotation immediately after the entry content:

   - From the returned entry's YAML frontmatter, read:
     - `submitted` (required)
     - `staleness_threshold` (required)
     - `last_reviewed` (optional — use if present)
     - `verified_on` (optional — include in annotation if present)
   - Compute `reference_date = last_reviewed if present, else submitted`
   - Compute `age_days = (today - reference_date).days`

   **If `age_days > staleness_threshold`:**
   > ⚠️ **Stale entry** — last verified {reference_date} ({age_days} days ago, threshold {staleness_threshold} days). The fix may not apply to your current stack version. Verify before acting.
   > Verified on: {verified_on}  ← only if `verified_on` is present

   **If `age_days > staleness_threshold * 0.75` (approaching threshold):**
   > ℹ️ Entry is {age_days} days old (threshold {staleness_threshold} days) — worth re-verifying if you encounter issues.

   **If `age_days <= staleness_threshold * 0.75`:** no annotation. Do not annotate fresh entries.

6. If the user just fixed something related, offer to submit via CAPTURE.

---

**Multi-garden search workflow** (`~/.claude/garden-config.toml` present with multiple gardens):

Check `~/.claude/garden-config.toml` at session start. If present, determine the garden topology before searching.

**For child gardens** (local garden has `role: child` in SCHEMA.md):

Search in priority order — stop at first match:

1. **Local garden first** — search the local child garden using Steps 1–4 above. If found, return immediately with staleness annotation and label:
   > `[local]` — from `<garden-name>`

2. **Walk upstream chain** — if not found locally, search each upstream garden in order (as declared in SCHEMA.md `upstream:` list, resolved to local paths via `garden-config.toml`):
   ```bash
   git -C <upstream-garden-path> pull --filter=blob:none
   git -C <upstream-garden-path> cat-file blob HEAD:<domain>/GE-XXXX.md
   ```
   Label the result so the user knows which garden it came from:
   > `[upstream: <garden-name>]` — from `<upstream-garden-name>`

3. **Full upstream grep** — if still not found after checking all indexed entries, run `git grep` across the upstream garden:
   ```bash
   git -C <upstream-garden-path> grep "keywords" HEAD -- '*.md' \
     ':!GARDEN.md' ':!CHECKED.md' ':!DISCARDED.md'
   ```

Apply the same staleness annotation (Step 5) regardless of which garden the entry came from.

**For peer gardens** (local garden has `role: peer` in SCHEMA.md, or `peers:` list in config):

Search all peers in parallel (or sequentially) and synthesise results:

1. Search each configured peer garden using the single-garden Steps 1–3.
2. Collect all matches across peers — do not deduplicate (peer overlaps are expected and valid).
3. Present results grouped by garden, each labelled:
   > `[peer: <garden-name>]`
4. If two peers have entries on the same topic, present both — the user decides which applies to their context.

**Submitting to the correct garden** — use `route_submission.py` to find the right garden for a new capture:
```bash
python3 ${SOREDIUM_PATH:-~/claude/hortora/soredium}/scripts/route_submission.py <domain>
```
This reads SCHEMA.md from each configured garden and returns the path of the one that owns the domain.

---

## Proactive Trigger

Fire **without being asked** when:

**For gotchas:** multiple approaches tried before fix; documented approach didn't work; silent failure in one context only. User says: "that took way too long", "weird behaviour".

**For techniques:** non-obvious approach used; tool/API combination used in unexpected way. User says: "that's a neat trick", "this should be documented".

**For undocumented:** found by reading source code, not docs; works but unexplained. User says: "this isn't in the docs".

Offer, don't assume:
> "This was non-obvious — want me to submit it to the garden as a [gotcha / technique / undocumented]?"

**Also fire for REVISE** when a solution surfaces for a previously-unsolved gotcha:
> "This looks like a solution to an existing garden entry — want me to submit a REVISE to enrich '[entry title]' with the fix?"

---

## Common Pitfalls

| Mistake | Why It's Wrong | Fix |
|---------|----------------|-----|
| Reading garden files with `cat` or `grep` from filesystem | May see partial writes | Always use `git show HEAD:path` |
| Leaving uncommitted changes in the garden repo | Other sessions see partial state | Commit immediately after every write |
| Using `**Bold:** value` markdown headers | Wrong format — validator rejects the file | Always use YAML frontmatter; see submission-formats.md |
| Writing to a `submissions/` directory | No submissions queue — write directly to `<domain>/GE-XXXX.md` | Write the entry file to the domain dir |
| Opening a PR against the wrong repo | Entries end up in someone else's garden | Check `git remote get-url origin` before creating the PR |
| score below 8 | `validate_pr.py` will reject the entry | Only submit if score ≥ 8 |
| Gotcha: title describes the fix not the weird thing | Can't find it by symptom | Title = the surprising behaviour, not the solution |
| Technique: no "why non-obvious" section | Just becomes documentation | Must explain what developers would normally do instead |
| SWEEP: asking the user what was discovered | Claude has the context | Scan session memory and propose specific candidates |
| SWEEP: only checking gotchas | Techniques and undocumented items are easy to miss | Always check all three categories explicitly |
| CAPTURE: omitting garden field | New entries need explicit garden declaration | Always include `garden: <type>` in frontmatter |
| CAPTURE: using gotcha/technique/undocumented in non-discovery garden | Type vocabulary is per-garden | patterns uses architectural/migration/integration/testing; examples uses code |

---

## Success Criteria

CAPTURE is complete when:
- ✅ GE-ID generated locally (`GE-YYYYMMDD-xxxxxx` format)
- ✅ Entry file written to `<domain>/GE-YYYYMMDD-xxxxxx.md` with YAML frontmatter
- ✅ Light duplicate check performed against committed GARDEN.md index
- ✅ User confirmed the draft before writing
- ✅ `validate_pr.py` run — no CRITICAL errors
- ✅ Delivered: PR opened (GitHub remote) or committed directly to main (local)
- ✅ `verified_on` field included in YAML frontmatter for library/tool-specific entries (if version known)
- ✅ `### Why this fix` section added for entries scoring ≥12 (if rationale provided)
- ✅ `author` field included in YAML frontmatter (from `~/.claude/settings.json` `initials`)
- ✅ WHY fields (constraints, alternatives_considered, invalidation_triggers) prompted — user responses included if provided
- ✅ `garden` field declared in YAML frontmatter
- ✅ `type` value is valid for the declared garden
- ✅ Garden-specific required fields present (evolution: `changed_in`; risk: `severity`)
- ✅ For patterns-garden entries: optional extended fields (`observed_in`, `suitability`, `variants`, `variant_frequency`, `authors`, `stability`) included where known from context; no extended-field warnings from `validate_pr.py`

SWEEP is complete when:
- ✅ All three categories checked from session memory
- ✅ Each finding proposed explicitly with type and description
- ✅ Confirmed entries written via CAPTURE steps 0–6; validated (parallel if ≥3 entries) and delivered as a single batch commit + PR
- ✅ Staleness spot-check run for session domains (if identifiable)
- ✅ Overdue entries in session domains presented and resolved/skipped
- ✅ Report given: N found, M submitted per category; overdue entries resolved

REVISE is complete when:
- ✅ Target entry read from `git show HEAD:<domain>/GE-XXXX.md` (not filesystem)
- ✅ Revision kind determined and correct integration method applied to target entry body
- ✅ Multiple Solutions structure used when adding a second solution (not just appending)
- ✅ "resolved" entries: resolved note added, original content preserved
- ✅ User confirmed the modification before writing
- ✅ `validate_pr.py` run on the modified target entry — no CRITICAL errors
- ✅ Delivered: PR (GitHub remote) or direct commit to main (local)
- ✅ Commit message: `revise(GE-XXXX): <revision-kind> — <brief description>`

SEARCH is complete when:
- ✅ Index read from `GARDEN.md` or `_index/global.md`
- ✅ Entry read from `git cat-file blob HEAD:<path>` (not filesystem)
- ✅ Staleness annotation appended if entry is past or approaching threshold

---

## Skill Chaining

**Invoked by:** `handover` — garden SWEEP is Step 2b of the wrap checklist; user directly ("submit to the garden", "add this to the garden", "forage CAPTURE")

**Chains to:** `harvest` — for DEDUPE only

**Does NOT handle:** DEDUPE — that is a harvest operation.

**Garden location:** `${HORTORA_GARDEN:-~/.hortora/garden}/`
