# Classification Procedure (Steps 3a–3i)

Standalone reference for the commit classification procedure used by git-squash Step 3.
Extracted from SKILL.md to allow subagents to read classification logic without loading
the full 1300-line skill.

---

#### 3a — Gather raw data

Run `commit_gather.py` to collect per-commit data as structured JSON:
```bash
python3 ~/.claude/skills/git-squash/commit_gather.py <project> range=<base..head>
```

Parse the JSON output. The result contains:
- `commits[]` — array of per-commit objects with `sha`, `subject`, `body`, `author`,
  `date`, `files[]`, `insertions`, `deletions`, `issue_refs[]`, and `patch_id`
- `is_conventional` — whether ≥ 80% of recent history uses conventional commits (feeds Step 3b)
- `pr` — PR info if `gh` is available (feeds Step 3c)
- `commit_count` — total commits in range

Use the `commits` array for classification in Steps 3b–3i. The script handles all
git log, git show, git patch-id, and gh pr view calls internally.

**Non-trivial body content:** a body is non-trivial if it contains more than
`Co-authored-by:`, `Signed-off-by:`, or blank lines.

**Body synthesis for groups (Step 3a-ii):** After gathering all commit bodies in a group,
extract and synthesise substantive content for the curated final commit body:

1. **ADR references:** any mention of "ADR", "ADR-NNN", "Architecture Decision" → always preserve
2. **Rationale phrases:** sentences containing "because", "to avoid", "so that", "decided to", "per decision", "constraint" → preserve the sentence
3. **Rejected alternatives:** "instead of", "not X because", "considered X but" → preserve
4. **Planning doc subjects:** when absorbing a design spec or implementation plan commit, prepend `[Plan: <planning commit subject>]` to the synthesised body
5. **Deduplication:** remove repeated content across multiple commit bodies

The synthesised body appears in the plan's curated result column alongside the subject.
If no substantive body content is found, the curated body is empty (no "message adequate" noise).

This preserves architectural rationale through the squash — the *why* survives, not just the *what*.

#### 3b — Detect conventional commits

Use the `is_conventional` field from the `commit_gather.py` output (Step 3a).
If `true`, record `CONVENTIONAL=true` — used in Step 6 to enforce format
on MERGE messages.

#### 3c — PR/issue body integration

Use the `pr` field from the `commit_gather.py` output (Step 3a). If non-null,
it contains `number`, `title`, `body`, and `base`.

If a PR exists:
- **Protected-branch merge target** (`main`, `master`, `release/*`): note this for
  merge commit classification (Step 3d)
- **Commits mentioned by SHA** in the PR description → KEEP regardless of size
- **PR task list** where each task maps 1:1 to a commit → treat all as KEEP
  (they document the work breakdown; squashing loses the traceability)
- **PR description says "fix typo in X"** → corresponding commit is SQUASH regardless
  of message pattern

#### 3d-pre — Same-issue clustering (runs before pattern classification)

Before pattern classification, group commits by shared issue reference. Use
the `issue_refs` array from each commit in the `commit_gather.py` output (Step 3a).

For each issue number that appears in 2+ commits in the range:

**Clustering rules:**
- **One feat + one or more fix/test/docs sharing the same #N**: MERGE all into the feat. The combined work for that issue belongs together.
- **Multiple feat commits sharing the same #N**: KEEP each but annotate as parts of the same issue — they document distinct steps of a larger capability.
- **Only fix/test/docs for #N, no feat**: MERGE into the most substantive (largest diff), flag "no primary feat identified for #N"
- **Contiguity not required**: commits for the same issue may be scattered across the range — same-issue clustering reaches across non-adjacent commits.

Store the resulting issue-based groups as `ISSUE_GROUPS` for use in Step 3d (PR context).

#### 3d — Apply PR grouping context (if Step 0b produced groups)

If `PR_GROUPS` is populated from Step 0b, use it to pre-organise commits before
pattern classification:

- Commits within a PR group are classified together. The group's PR title (or scope
  label for Strategy D) becomes the heading for that section of the plan.
- Pattern classification (KEEP / SQUASH / MERGE / DROP) still applies within each
  group — the pre-pass determines *which* commits belong together, not how to handle
  individual commits.
- Commits not covered by any PR group fall back to the nearest-KEEP grouping (Strategy E).
- For **Strategy A (reconstruction)**: the single squash commit on main is the KEEP;
  the recovered original branch commits are classified against it. Seed the curated
  message from the PR title (subject to conventional commit enforcement).

#### 3e — Pattern classification

For each commit, apply the KEEP / SQUASH / MERGE / DROP rules from `squash-policy.md`
in priority order. Pay particular attention to the refined merge commit rules (rows
2a–2e): inspect branch names in the merge message before classifying.

Only classify a commit as DROP if `git show --stat` confirms **zero files changed**.

**Scoped patterns — scope does not exempt from SQUASH:**
`chore(docs):`, `chore(build):`, `chore(examples):`, `style(enricher):`, `style(trust):`
etc. all match their base type (`chore:`, `style:`) for classification purposes.
A scope in parentheses does not make a chore or style commit a KEEP.

**Stale-ref classification takes priority over broad type patterns:**
Check `is_stale_ref` BEFORE the broad `docs:` KEEP and `fix:` KEEP patterns.
`docs: fix stale repo name references post-rename` is SQUASH, not KEEP.
`fix: update all stale repo name references` is SQUASH, not KEEP.
The stale-ref pattern overrides the type prefix.

**CI development arc detection:**
When 3 or more consecutive `ci:` / `fix(ci):` commits appear in the range, they
represent a development arc (scratch → working state). Do not absorb them all into
whatever KEEP precedes them. Instead:
1. Identify the arc: all contiguous `ci:` / `fix(ci):` commits (none of which has
   a non-CI commit between them)
2. Promote the **last** commit in the arc to KEEP — it represents the working outcome
3. Classify all preceding commits in the arc as SQUASH, absorbed into that final KEEP
4. The arc is self-contained — it does not absorb unrelated preceding commits

**Double issue-close detection (run after grouping, before showing plan):**

After all groups are formed, scan all surviving KEEP commits for duplicate `Closes #N`
references. Use the `issue_refs` array from each commit's `commit_gather.py` output
(Step 3a) — filter for entries where `type` is `"Closes"`.

For each issue number that appears more than once with `Closes`:
```
⚠️  Duplicate Closes #N: both <sha1> and <sha2> claim to close this issue.
    Only one should be authoritative. Suggest changing one to `Refs #N`.
    Typically: the PR merge commit closes; the individual branch commit refs.
```

Surface this flag in the plan before the approval prompt. Present both options:
amend one to `Refs #N`, or accept both as-is. Wait for the user's decision before
building the rebase todo.

**Consistent proximity-grouped flagging:**

The ⚠️ proximity-grouped annotation must apply to ALL cases where a commit is
absorbed into a semantically unrelated KEEP — not only chore commits. Apply it when:
- A `ci:` or `fix(ci):` commit is absorbed into a non-CI KEEP
- A `style:` or formatting commit is absorbed into an unrelated KEEP
- Any commit with zero meaningful word overlap (after PROXIMITY_STOP filter) with its KEEP

CI commits absorbed into blackboard feats, test commits, or unrelated fixes are
proximity-grouped by the same definition as chore commits near unrelated feats. Flag
them identically.

**Absorption target SHA verification (pre-execution, before building rebase todo):**

Before building the rebase todo, verify every non-group KEEP target SHA exists on
the working branch:

```bash
# Verify each referenced SHA exists — one command per SHA, no loop
git cat-file -e <sha1> 2>/dev/null || echo "MISSING: <sha1>"
git cat-file -e <sha2> 2>/dev/null || echo "MISSING: <sha2>"
# substitute actual SHA values
```

If any SHA is missing: halt and report. A missing SHA means the plan was generated
against a different branch state than the current working branch (the branch was
amended, rebased, or additional commits were added since plan generation). Do not
proceed until the plan is regenerated.

**Chronological ordering check for cross-group absorptions:**

When a SQUASH commit targets a KEEP from a *different* group (i.e., the target is
not the immediately preceding KEEP), verify the chronological relationship:

```bash
# Does SQUASH commit appear before or after its target in the range?
git log --format="%H" <range> | grep -n "<squash_sha>\|<target_sha>"
```

If the SQUASH commit appears *before* its target in the range (i.e., older), the
standard rebase todo cannot use a simple `squash` line — it would need to be listed
after the target's `pick` line, which requires manual reordering of the todo. Flag
this explicitly in the plan:

```
⚠️  Ordering: <squash_sha> is chronologically before <target_sha>.
    The rebase todo must list this commit as `squash` after the target's `pick` line.
    Verify the todo ordering before executing.
```

**Proximity-grouped resolution — scan forward before accepting a wrong attachment:**
When a SQUASH commit has zero meaningful word overlap with its nearest preceding KEEP
(PROXIMITY_STOP-filtered), do not immediately absorb it there. Instead:
1. Scan forward up to 5 commits for a KEEP with overlap > 0 (bounded to prevent spurious distant matches)
2. If a better semantic home is found: re-group there; note in plan "relocated to semantic home"
3. If no better home exists: promote the commit to KEEP micro-commit — a small standalone
   chore is better history than a wrong attachment

Only fall back to proximity grouping (with annotation) when no semantic home can be found.

**Rename sweep grouping — stale-ref fixups anchor to the rename, not nearest KEEP:**
When the range contains a rename commit (`refactor: rename to X — groupId, package...`),
scan forward from it for all stale-reference fixup commits:
- `docs: fix stale ... references`
- `docs: replace stale ... artifact names`
- `docs: update stale ...`
- `chore(docs): replace stale ...`
- `chore: update repo references to ...`

These all belong grouped under the rename commit regardless of what other KEEPs
appear between the rename and the fixups. A stale-ref fixup that is "already clean"
in isolation is wrong if a rename commit exists in the range — it is part of that
rename sweep.

#### 3f — Temporal scrutiny

Use the `author` and `date` fields from each commit in the `commit_gather.py`
output (Step 3a) to identify commits from the same author within 30-minute windows.

Temporal proximity is not a merge signal — two commits 10 minutes apart may address
completely different concerns. It is a scrutiny signal: surface them together in the
plan and ask the author to confirm they are genuinely distinct before leaving them as
separate KEEP commits.

Do not reclassify or merge automatically. Show the cluster as a question:
```
⏱ Close together — 3 commits from alice@example.com within 18 minutes:
   abc1234  feat(api): add UserRepository SPI
   def5678  docs: update CLAUDE.md for new conventions
   ghi9012  fix(test): correct assertion timing
   Are these genuinely distinct? (YES to keep separate / n to review for merge)
```

#### 3g — File-overlap MERGE detection

For each pair of KEEP commits in the range, compute Jaccard similarity of their
file sets:
```
similarity = |files(A) ∩ files(B)| / |files(A) ∪ files(B)|
```

If similarity ≥ 0.7, flag as a MERGE candidate — both commits are likely addressing
the same capability regardless of message wording. Surface as:
```
📁 File-overlap MERGE candidate — these commits share 4/5 files:
   abc1234  feat(api): add UserRepository SPI
   def5678  feat(api): wire UserRepository into ServiceLocator
   Overlap: UserRepository.java, UserRepositoryImpl.java, UserRepositoryTest.java, ...
```

Do not merge commits from different features/scopes just because files overlap.
Confirm that the overlap makes semantic sense (same module, same capability).

#### 3h — Cross-author check

For any KEEP or MERGE candidate that would be absorbed into a commit from a different
author — reclassify as KEEP and flag it. Cross-author squash is only permitted when
the absorbed commit is already classified SQUASH (formatting, CI, spelling).

#### 3i — Cherry-pick detection

For commits classified SQUASH or MERGE, use the `patch_id` field from the
`commit_gather.py` output (Step 3a) to check for cherry-picks. Compare each
commit's `patch_id` against patch-ids on other branches to detect duplicates.

If a commit being squashed has a matching patch-id on another branch, warn:
```
⚠️  Cherry-pick detected: abc1234 appears on branch release/2.1
    Squashing this commit rewrites its identity — the cherry-pick will conflict on
    future merges. Confirm? (YES to proceed, n to keep standalone)
```
