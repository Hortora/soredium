# Diary Form Guide

A diary entry must be worth reading independently by a developer who has
never seen this codebase. It informs, engages, and demonstrates relevance.
If a reader could reconstruct the same information from `git log`, the
entry has no reason to exist. 

Written in the moment, not in hindsight. Raw honesty is the value —
readers see how decisions actually get made, including what failed first,
what was rejected, and what changed direction mid-build. Verify claims
against evidence — check `git log` before writing durations or timelines.
"I was working on this for weeks" when the codebase is three days old
destroys credibility.

---

## Writing Quality

**Voice:** "I" for what I thought, believed, wanted, or decided. "we" for
what we built, tried, found, or fixed together with Claude. Name Claude
directly when its specific behaviour is the story — catching a mistake,
reporting a result, going off-script. Never third-person for the developer.
Full register rules are in `write-content/voice/mandatory-rules.md`.

**Make the reader care.** For anything non-obvious — an architectural
choice, a subtle fix, a design constraint — explain why it matters to
someone using this project. Use examples or allegories a practitioner
will recognise. The test: would a reader who doesn't know this codebase
understand why this change is interesting, not just what it does? If not,
add the "so what."

> "We extracted `workspace_artifacts.py` as a central path resolver —
> until now, every skill that promoted specs or blogs was computing paths
> independently, and three of them were getting it wrong."

When something requires specialist knowledge beyond what an average
Java or TypeScript engineer would have, provide enough context that they
can follow the reasoning. Scale context to novelty and importance — the
more novel or important, the more explanation earns its place.

**Credibility comes from specifics.** Exact error messages verbatim.
File paths. What was tried before the fix and why each attempt failed.
Numbers. Code blocks for the interesting parts. The moment something
surprised you. Screenshots for any UI work (mandatory). Avoid smooth
narratives with no failed attempts. Avoid "we decided to use X" without
saying what else was considered.

**Every entry looks forward.** What does this work open up? What questions
surfaced? What directions are being considered? This isn't a "Next Steps"
footer — it's genuine reflection woven into the closing prose. A diary
that only records what happened feels like a closed loop. Even a small
observation gives the reader trajectory.

Closing insight is optional — only when genuine. Forms that earn their place:
- What it might lead to — a direction not obvious from the commits
- A non-obvious implication or cross-project connection
- A decision made implicitly that's worth naming explicitly

If it reads as obligation rather than thought, end on the last real point.

**Every sentence pays for itself.** Routine work needs no justification.
Novel work needs enough context that a reader understands why it matters.
Don't cap it; don't pad it. End when the point is made.

---

## Entry Types

| Type | When to use |
|------|------------|
| **Entry** | Inform or reflect — a milestone, a pivot, a discovery, a correction. Written in the moment. |
| **Retrospective** | Covering all work to date in one pass — scans git history, proposes phases, writes in sequence. See [diary-retrospective.md](diary-retrospective.md). |

---

## Workflow

### Step 1 — Setup

**Resolve blog directory:**

```bash
python3 ~/.claude/skills/write-content/resolve_artifact_dir.py blog <WORKSPACE> <CLAUDE_MD_PATH> [slot_root=<SLOT_ROOT>]
```

Read `ARTIFACT_DIR` from output. Resolve to an absolute path.

**Load voice:** check `~/claude-workspace/writing-styles/` for personal
style files. Load personal style or fall back to `voice/common-voice.md`.

**Resolve author initials** from `~/.claude/settings.json` `initials` field.

**Determine type:** article or note/diary. Auto-route from invocation
context when unambiguous. Set frontmatter: `entry_type`, `subtype: diary`
(for notes), `projects` from CLAUDE.md `**Repository:**` field using
`<github-org>/<repo-name>` format (e.g. `casehubio/engine`). If no
`**Repository:**` field exists, fall back to CLAUDE.md `**Name:**` field.

**Check prior entries in this series:** if `.meta` exists, scan `<BLOG_DIR>/`
for entries with matching `series:` frontmatter using the branch name.

### Step 1b — Revise-or-new decision

**Skip** if no prior entries found in Step 1's series check.

If prior entries exist with matching `series:` (branch name):

1. Read the most recent entry in the series
2. Assess: would a new entry largely repeat what the existing one covers?

**Default to Revise** when:
- The existing entry covers work on this branch that this session continued
- The entry is unpublished (still in workspace, not promoted to project)
- A new entry would substantially overlap with the existing one

**Default to New** when:
- The existing entry covers a complete, distinct phase (different problem,
  different discovery, different direction)
- Enough genuinely new content exists to stand alone as its own narrative
- The work direction changed significantly since the last entry

Present the decision with a recommendation and reasoning:
```
Prior entry found: <filename>
  "<title>" — <date>, <word-count> words

  [R] Revise (Recommended) — <1-2 sentence reason, e.g. "this session
      continued the same work; a new entry would largely repeat the
      existing one">
  [N] New — <when this would be better, e.g. "choose this if the work
      direction changed enough to warrant a separate narrative">
```

Always recommend one option. The default-to-Revise and default-to-New
rules above determine which to recommend — surface that reasoning in
the prompt so the user can verify the judgment.

If **Revise**: carry the existing file path forward as `REVISE_PATH`. Step 2
gathers new content. Step 3 drafts an updated version that integrates the
existing prose with new material — not an append, but a coherent rewrite.
Step 4 writes to the same file.

If **New**: `REVISE_PATH` is empty. Proceed as normal — Step 4 creates a new
file with the next sequence number and a continuity note.

### Step 2 — Gather

**Entry worthiness check — before gathering anything:**

Does this session contain at least one of:
- A decision and its reasoning
- An observation or discovery about how something works
- A conceptual or theoretical exploration
- An industry reflection or opinion
- Anything worth reading independently of the action sequence

If the session was a pure action sequence with none of the above:
**do not write this entry.**

If worthy, extract from conversation context. Only ask for what's
genuinely unclear: What was the goal? What was believed going in?
What was built/tried/found? What failed? What changed direction?

### Step 3 — Draft and confirm

**Pre-draft gate (mandatory — do not draft until complete):**

1. Voice classified — I/we/Claude register decided per section
2. Content focus checked — no process narration (build runs, test counts,
   agent counts, methodology names, issue numbers as scaffolding)
3. Factual accuracy checked — durations/counts verified against git log
4. Banned words scanned — anti-slop.md applied

Read `write-content/voice/mandatory-rules.md` and
`write-content/mandatory-gates.md` before drafting.

Draft. Go through the style guide's "What to Avoid" line by line. Fix
before showing. Scan for third-party references (named persons,
identifiable groups) — flag each for author approval per
`mandatory-gates.md`. Present the full draft. **Do NOT write to disk
until the user confirms.**

### Step 4 — Write

**If `REVISE_PATH` is set (revise mode):**

Write the updated draft to `REVISE_PATH`, replacing the existing content.
Preserve the original frontmatter `date:` field. Update `title:` and `tags:`
only if the revised content warrants it. Do not change the filename.

Update `<BLOG_DIR>/INDEX.md` only if the summary changed:
```bash
python3 ~/.claude/skills/write-content/update_blog_index.py <REVISE_PATH> --summary "<updated one-line summary>"
```

Commit via `git-commit`.

**If `REVISE_PATH` is empty (new entry):**

```bash
ls <BLOG_DIR>/YYYY-MM-DD-<initials>*.md 2>/dev/null | wc -l
# NN = count + 1, zero-padded
```

File name: `YYYY-MM-DD-<initials>NN-<kebab-case-title>.md`

`<initials>` from `~/.claude/settings.json`. `NN` is two-digit per-author
sequence number starting at `01`. Kebab-case title, ≤30 chars.

Frontmatter:
```yaml
---
layout: post
title: "<title>"
date: YYYY-MM-DD
entry_type: <article|note>
subtype: diary
projects: [<project>, ...]
tags: [<tag>, ...]
series: <branch-name>      # omit if no prior entries in this series
---
```

If `series:` is set and prior entries exist, open with a one-line
continuity note linking to the previous entry.

After writing, update `<BLOG_DIR>/INDEX.md`:
```bash
python3 ~/.claude/skills/write-content/update_blog_index.py <blog-file-path> --summary "<one-line summary>"
```

Commit via `git-commit`.
