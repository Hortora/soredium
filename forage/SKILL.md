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

**Step 4 — Determine the domain**

Based on the technology stack, determine the domain directory:

| Technology | Domain |
|-----------|--------|
| AppKit, WKWebView, NSTextField | `macos-native-appkit` |
| Panama FFM, jextract, GraalVM native | `java-panama-ffm` |
| Quarkus | `quarkus` |
| Java (language, JVM) | `java` |
| Git, tmux, Docker, CLI tools, cross-cutting patterns | `tools` |
| Doesn't fit existing | `<new-descriptive-dir>` |

**Step 5 — Draft and confirm**

Draft the entry using the YAML frontmatter template in [submission-formats.md](submission-formats.md). Show it to the user:
> "Does this capture it accurately?"

Wait for confirmation before writing.

**Step 6 — Write the entry file**

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

**If the URL contains `github.com`** → create a branch and open a PR:
```bash
GARDEN=${HORTORA_GARDEN:-~/.hortora/garden}
git -C $GARDEN checkout -b submit/$GE_ID
git -C $GARDEN add <domain>/$GE_ID.md
git -C $GARDEN commit -m "submit($GE_ID): <slug>"
git -C $GARDEN push origin submit/$GE_ID
gh pr create --repo Hortora/garden \
  --title "submit($GE_ID): <slug>" \
  --label "garden-submission" \
  --head submit/$GE_ID
git -C $GARDEN checkout main
```

**If no GitHub remote** → commit directly to main:
```bash
GARDEN=${HORTORA_GARDEN:-~/.hortora/garden}
git -C $GARDEN add <domain>/$GE_ID.md
git -C $GARDEN commit -m "submit($GE_ID): <slug>"
```

**Step 9 — Report back**

Tell the user the entry path and (for GitHub gardens) the PR URL.

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

### IMPORT (from project-level docs)

Use when importing from `BUGS-AND-ODDITIES.md` or similar project-level bug/quirk documents.

1. Read the source document
2. For each entry, classify **CROSS-PROJECT** or **PROJECT-LOCAL**
3. Show classifications, ask for confirmation
4. For cross-project entries: run the CAPTURE flow per entry
5. Report: N entries written, M skipped as project-specific

---

### REVISE (submit an enrichment to an existing entry)

Use when new knowledge enriches an existing garden entry rather than standing alone.

**Step 1 — Identify the target entry**

If already in context, use that knowledge directly. Otherwise search:

```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} grep "keywords" HEAD -- '*.md' \
  ':!GARDEN.md' ':!CHECKED.md' ':!DISCARDED.md'
```

Read only the specific entry:
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

**Step 3 — Draft and confirm**

Use the REVISE template in [submission-formats.md](submission-formats.md). Show it to the user. Wait for confirmation.

**Step 4 — Write the REVISE entry file**

REVISE entries get their own GE-ID. Include "revise" in the filename:
```bash
# $GARDEN/<domain>/$GE_ID-revise-<target-slug>.md
```

**Step 5 — Validate and deliver**

Same as CAPTURE Steps 7–8: validate, then PR (GitHub remote) or direct commit (local).

---

### SEARCH (retrieving entries)

**Session start** — pull latest index changes before searching:
```bash
git -C ${HORTORA_GARDEN:-~/.hortora/garden} pull --filter=blob:none
```

**Search workflow:**

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

5. If the user just fixed something related, offer to submit via CAPTURE.

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

---

## Success Criteria

CAPTURE is complete when:
- ✅ GE-ID generated locally (`GE-YYYYMMDD-xxxxxx` format)
- ✅ Entry file written to `<domain>/GE-YYYYMMDD-xxxxxx.md` with YAML frontmatter
- ✅ Light duplicate check performed against committed GARDEN.md index
- ✅ User confirmed the draft before writing
- ✅ `validate_pr.py` run — no CRITICAL errors
- ✅ Delivered: PR opened (GitHub remote) or committed directly to main (local)

SWEEP is complete when:
- ✅ All three categories checked from session memory
- ✅ Each finding proposed explicitly with type and description
- ✅ Confirmed entries submitted via CAPTURE
- ✅ Report given: N found, M submitted per category

REVISE is complete when:
- ✅ Target entry located via `git grep` or `git show HEAD:path`
- ✅ REVISE entry file written with "revise" in the filename
- ✅ Revision kind declared in YAML frontmatter
- ✅ User confirmed before writing
- ✅ Delivered: PR (GitHub remote) or direct commit (local)

SEARCH is complete when:
- ✅ Index read from `GARDEN.md` or `_index/global.md`
- ✅ Entry read from `git cat-file blob HEAD:<path>` (not filesystem)

---

## Skill Chaining

**Invoked by:** `handover` — garden SWEEP is Step 2b of the wrap checklist; user directly ("submit to the garden", "add this to the garden", "forage CAPTURE")

**Chains to:** `harvest` — for DEDUPE only

**Does NOT handle:** DEDUPE — that is a harvest operation.

**Garden location:** `${HORTORA_GARDEN:-~/.hortora/garden}/`
