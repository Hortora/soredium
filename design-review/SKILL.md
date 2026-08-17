---
name: design-review
description: >
  Use when a design spec needs adversarial review — user says "review this design",
  "design review", "tear this spec apart", "pre-review this", or invokes /design-review.
  Supports multiple review phases: pre-review (approach validation), spec review
  (detailed adversarial review). NOT for code review (use code-review).
  NOT for brainstorming (use superpowers:brainstorming).
---

# Adversarial Design Review

Orchestrates adversarial design review between independent Claude sessions with
issue-level tracking, evidence-based verification, and human-in-the-loop escalation.

Supports multiple review phases — each phase uses different reviewer briefs and
round counts appropriate to the review stage.

## Step 0 — Verify permissions (first run only)

Before the first run, check that the review script can execute without
permission prompts. The script path resolves to `~/.claude/skills/design-review/review.py`.

Check if the permission exists:
```bash
cat ~/.claude/settings.json | python3 -c "import sys,json; perms=json.load(sys.stdin).get('permissions',{}).get('allow',[]); print('OK' if any('design-review/review.py' in p for p in perms) else 'MISSING')"
```

If MISSING, add it using the `update-config` skill or tell the user:
> The design-review skill needs a Bash permission to run.
> Add this to your `~/.claude/settings.json` permissions.allow:
> `"Bash(python3 */.claude/skills/design-review/review.py *)"`

This is a one-time setup. Once added, the skill runs without prompts.

## Step 0.5 — Select review degree

Reviews are lifecycle-driven. The **lifecycle point** determines which dimensions
run. The **degree** is the user's only choice. See [review-tiers.md](review-tiers.md).

### Lifecycle detection

Determine the lifecycle point from context:
- **Post-spec** (default): invoked on a spec file, or brainstorming handed off
- Post-brainstorming, post-implementation, pre-ship: future lifecycle points

For post-spec, all three dimensions run automatically:
- **Coherence** — completeness, consistency, gaps
- **Structure** — decomposition, boundaries, dependencies
- **Robustness** — failure modes, edge cases, error paths
- **Cross-cutting** — automatic after all dimensions complete

### Recommendation engine

Analyze the spec for complexity signals and present a recommendation:

| Signal | Recommendation |
|--------|---------------|
| Config-only, rename, mechanical wiring | Skip |
| Clear requirements, known domain, small scope | Light |
| New module, API surface changes | Standard |
| Cross-module boundaries, dependency ordering | Standard |
| Auth, security, PII, concurrency, distributed state | Adversarial |
| Novel architecture, first-of-kind, high-stakes | Deep |

### Degree-only prompt

```python
AskUserQuestion(questions=[{
    "question": "Review depth? (coherence + structure + robustness + cross-cutting)",
    "header": "Review",
    "options": [
        {"label": "<Recommended> (Recommended)", "description": "<reasoning>"},
        {"label": "Skip", "description": "No review needed"},
        {"label": "Light", "description": "~2 min — single pass per dimension"},
        {"label": "Standard", "description": "~5 min — 2-3 rounds per dimension"},
        {"label": "Adversarial", "description": "~12 min — 4-6 rounds per dimension"},
        {"label": "Deep", "description": "~25 min — 8-10 rounds + ultrathink"},
    ],
    "multiSelect": false,
}])
```

**If invoked with explicit `--type` flag** (`/design-review --type robustness`):
run only that single dimension (backward compat, old behavior). No cross-cutting.

**If invoked with `--degree` only:** run all dimensions at that degree.

**Backward compat:** `--mode`, `--depth` still accepted and mapped.

**After light/standard reviews:** check for escalation assessment. If `ESCALATE: yes`,
present the recommendation and ask whether to proceed with the escalated review.

## Step 1 — Identify the spec

Determine the spec file from the user's message. Look for:
- An explicit path: "review ~/tmp/invoice-aggregate-spec.md"
- A filename: "review the invoice spec"
- Context: if in a project with a recent brainstorming output, the spec is likely the most
  recently created or modified `.md` file in `~/tmp/` or the current directory

If ambiguous, ask:
> Which spec should I review? (provide the file path)

## Step 2 — Determine context directories

The review needs `--source-dirs` pointing at the project and any related repos. Detect from:
- The current working directory (if it's a project repo)
- CLAUDE.md references to companion workspaces or parent repos
- The user's message ("review this against drafthouse")

Common patterns:
- Single project: `--source-dirs /path/to/project`
- Casehub project: `--source-dirs /path/to/casehub/{project} /path/to/casehub/parent ~/claude/public/casehub/{project}`

If you can't determine the source dirs, ask:
> Which project directories should the reviewer have access to?

## Step 3 — Derive title

Extract a short kebab-case title from the spec filename or content:
- `invoice-aggregate-spec.md` → `invoice-aggregate`
- `DESIGN-sparge-channels.md` → `sparge-channels`
- First heading of the spec → kebab-case of the first few words

## Step 3b — Check for existing workspace

Before creating a new workspace, check if one already exists for this title:

```bash
ls -d ~/reviews/*/{title}-* ~/adr/*/{title}-* 2>/dev/null
```

If a workspace exists:
- Check its `progress.log` to see how far it got
- Ask the user: **"Found existing workspace at {path} with {n} round(s) completed. Resume it or start fresh?"**
- If resume: use `--workspace {path}` instead of `--spec`
- If fresh: delete the old workspace first

**Never silently create a duplicate workspace.** The user has already spent tokens on the prior run.

## Step 4 — Launch dimension reviews

**IMPORTANT: These are long-running processes. Do NOT run inline — use
`run_in_background: true` on all Bash tool calls.**

### Single-type mode (backward compat)

If the user provided `--type X`, launch a single review.py with that type.
Skip cross-cutting. Use the old behavior exactly.

### Multi-dimension mode (default for post-spec)

Launch three review.py instances as parallel background processes. Each
gets the same spec, source-dirs, and degree. Title includes the dimension:

Tell the user BEFORE running:
> Starting post-spec review of **{title}** at **{degree}** depth.
>
> Launching 3 dimension reviews in parallel:
> - Coherence (completeness, consistency, gaps)
> - Structure (decomposition, boundaries, dependencies)
> - Robustness (failure modes, edge cases, error paths)
>
> You'll see round 1 findings as soon as they're ready (~2-5 min)
> and can kill dimensions that aren't finding useful issues.
> Monitor: `tail -f ~/reviews/*/{title}-*/progress.log`

Launch all three with `run_in_background: true`:

```bash
python3 ~/.claude/skills/design-review/review.py \
  --spec {spec_path} --title {title}-coherence \
  --type coherence --degree {degree} \
  --stage {maturity_stage} --source-dirs {dirs}
```

```bash
python3 ~/.claude/skills/design-review/review.py \
  --spec {spec_path} --title {title}-structure \
  --type structure --degree {degree} \
  --stage {maturity_stage} --source-dirs {dirs}
```

```bash
python3 ~/.claude/skills/design-review/review.py \
  --spec {spec_path} --title {title}-robustness \
  --type robustness --degree {degree} \
  --stage {maturity_stage} --source-dirs {dirs}
```

### Ordered mode (opt-in)

When the user selects an ordered review variant (e.g., "Standard, ordered"),
run dimensions sequentially with cascading findings. Each dimension's
tracker is passed as `--arch-files` to the next, so later dimensions see
and build on earlier findings.

**Ordering:** structure → coherence → robustness → cross-cutting

Tell the user BEFORE running:
> Starting ordered post-spec review of **{title}** at **{degree}** depth.
>
> Dimensions will run sequentially:
> 1. Structure (boundaries, decomposition)
> 2. Coherence (completeness, with structure findings)
> 3. Robustness (failure modes, with structure + coherence findings)
> 4. Cross-cutting (inter-dimension contradictions)
>
> Each dimension completes fully before the next starts.
> You can stop the pipeline between dimensions.

1. Launch structure with `run_in_background: true`:
   ```bash
   python3 ~/.claude/skills/design-review/review.py \
     --spec {spec_path} --title {title}-structure \
     --type structure --degree {degree} \
     --stage {maturity_stage} --source-dirs {dirs}
   ```

2. When structure completes (background task notification):
   - Read structure's tracker.md for findings summary
   - Present results to user
   - Ask: "Continue to coherence? (y/n)"
   - If no: stop the pipeline, present structure results as final
   - If yes: launch coherence with structure's tracker:
   ```bash
   python3 ~/.claude/skills/design-review/review.py \
     --spec {spec_path} --title {title}-coherence \
     --type coherence --degree {degree} \
     --stage {maturity_stage} --source-dirs {dirs} \
     --arch-files {structure_workspace}/tracker.md
   ```

3. When coherence completes:
   - Present results, ask "Continue to robustness? (y/n)"
   - If yes: launch robustness with both trackers:
   ```bash
   python3 ~/.claude/skills/design-review/review.py \
     --spec {spec_path} --title {title}-robustness \
     --type robustness --degree {degree} \
     --stage {maturity_stage} --source-dirs {dirs} \
     --arch-files {structure_workspace}/tracker.md \
                  {coherence_workspace}/tracker.md
   ```

4. When robustness completes:
   - Launch cross-cutting with all three trackers
   - Present unified results when complete

**Workspace path tracking:** Each review.py invocation creates a timestamped
workspace directory. Track these paths as you receive them (from the
progress.log first line or background task output) so you can pass the
correct `--arch-files` paths to subsequent dimensions. Do NOT use glob
patterns — use the explicit paths.

**Watchdog in ordered mode:** The watchdog monitors a single active
dimension. Checkpoint 1 (round 1 early-HIL) does not apply — results
are presented between dimensions. The watchdog's role is health
monitoring only: stalls, failures, timeouts.

## Step 5 — Set up HIL watchdog

**Immediately after launching**, create a SINGLE watchdog cron (not three)
to monitor all dimension reviews. Use a 2-minute interval.

The watchdog has two checkpoints: a **round 1 checkpoint** (early HIL)
and a **completion checkpoint** (pre-cross-cutting gate). Dimensions
keep running between checkpoints — they are never stopped and restarted.

Use `CronCreate` with `recurring: true` and this prompt:

> Check progress of the post-spec review for {title}. Read the last 20
> lines of each progress log:
> - `~/reviews/*/{title}-coherence-*/progress.log`
> - `~/reviews/*/{title}-structure-*/progress.log`
> - `~/reviews/*/{title}-robustness-*/progress.log`
>
> Track two things per dimension:
> 1. Whether round 1 is complete (look for `EVENT:` lines containing
>    `"type": "round_end"` with `"round_number": 1`)
> 2. Whether the review is done (`REVIEW DONE` in progress.log)
>
> **CHECKPOINT 1 — Round 1 findings (fires once):**
>
> When ALL dimensions have completed round 1 (or exited), and this
> checkpoint has not fired yet:
>
> Read each dimension's tracker.md. Present the round 1 summary:
> ```
> Round 1 findings:
>   Coherence:  {N} issues ({priority breakdown})
>   Structure:  {N} issues ({priority breakdown})
>   Robustness: {N} issues ({priority breakdown})
> ```
>
> If the degree is NOT light (i.e. dimensions will continue to round 2+),
> present four options:
> - **Accept all** — all dimensions continue running
> - **Refuse all** — kill all dimension processes, skip to checkpoint 2
> - **Refuse subset** — kill selected dimension processes (the others
>   keep running — they never stopped)
> - **Discuss** — read tracker entries for specific findings, discuss,
>   then re-present the options
>
> To kill a dimension: use `TaskStop` on its background task ID, or
> find the PID from progress.log and kill it.
>
> If the degree IS light: dimensions are already done (1 round). Skip
> the four-option prompt and proceed to checkpoint 2.
>
> **CHECKPOINT 2 — Pre-cross-cutting gate:**
>
> When ALL surviving dimensions show `REVIEW DONE` (or were killed):
>
> Read each surviving dimension's tracker.md. Present full results:
> ```
> Dimension results:
>   Coherence:  {N} rounds, {M} issues ({V} verified, {A} accepted, {D} deferred) — ${C}
>   Robustness: {N} rounds, {M} issues ({V} verified, {A} accepted, {D} deferred) — ${C}
>   Structure:  killed after round 1
> ```
>
> Two options:
> - **Run cross-cutting** — launch:
>   ```bash
>   python3 ~/.claude/skills/design-review/review.py \
>     --spec {spec_path} --title {title}-crosscutting \
>     --type crosscutting --degree {degree} \
>     --stage {maturity_stage} --source-dirs {dirs} \
>     --arch-files <surviving-tracker-paths>
>   ```
>   Only pass tracker.md paths for surviving dimensions.
>   Run in background. When cross-cutting completes, present unified
>   results using the template in Step 8.
> - **Skip** — present final results from dimensions only (Step 8).
>
> **When done (all results presented):** delete this cron.
>
> **Failure handling:**
> - `REVIEW PAUSED` — needs human input. Tell the user.
> - `REVIEW FAILED` / `REVIEW CRASHED` — report error, suggest resuming.
> - `REVIEW INTERRUPTED` — suggest resuming.
> - `.hil-timeout` marker — agent hit soft timeout, ask continue or kill.
> - No update for 10+ min — warn about stall.
>
> If one dimension fails before round 1, proceed with survivors for
> checkpoint 1. If only 1 dimension survives to checkpoint 2, skip
> cross-cutting and present results for that dimension alone.

Store the cron job ID for cleanup.

## Step 6 — Handle notifications

You will receive notifications from two sources:

1. **Background task completion** — fires when each review.py process exits
2. **Watchdog cron** — fires every 2 minutes with progress and checkpoint logic

On notification:
- If a dimension completed: the watchdog handles checkpoint logic
- If a dimension failed: report which one, suggest resuming
- If stalled: warn the user

## Step 7 — Handle failures

If a review.py process exits with an error:

1. Read its progress log to understand the failure
2. Check for permission issues (`claude -p` needs permission approval)
3. Check for timeouts (SESSION_TIMEOUT = 600s per claude -p call)
4. Report clearly which dimension failed
5. Suggest resuming:
   ```bash
   python3 ~/.claude/skills/design-review/review.py \
     --workspace ~/reviews/{project}/{title}-{dimension}-{timestamp}/ \
     --degree {degree} --source-dirs {dirs}
   ```

## Step 8 — Validate and present results

When all reviews complete (including optional cross-cutting):

1. **Read the final spec** — symlinked at `spec.md` in any workspace
2. **Read all trackers** — tracker.md from each dimension workspace
3. **Validate** — confirm verified/accepted items are reflected in the spec
4. **Report** — use this template:

```
Post-spec review complete: **{title}**

| Dimension | Rounds | Issues | Verified | Accepted | Deferred | Unresolved | Cost |
|-----------|--------|--------|----------|----------|----------|------------|------|
| Coherence | {N} | {M} | {V} | {A} | {D} | {U} | ${C} |
| Structure | {N} | {M} | {V} | {A} | {D} | {U} | ${C} |
| Robustness | {N} | {M} | {V} | {A} | {D} | {U} | ${C} |
| Cross-cutting | {N} | {M} | {V} | {A} | {D} | {U} | ${C} |
| **Total** | | **{M}** | **{V}** | **{A}** | **{D}** | **{U}** | **${C}** |

Health: {no issues | N timeout(s), M error(s)}
Spec: file://{spec_path}

{If unresolved items exist in any dimension, list each}
```

Omit rows for killed dimensions and for cross-cutting if it was skipped.

Do NOT substitute a narrative summary for this template.

## Step 8b — Triage and incorporate findings

After presenting the results table, triage unresolved findings into the spec.
This step runs for ALL degrees — light reviews surface raw findings that need
user triage; standard+ reviews may have surviving unresolved items.

**1. Collect unresolved findings**

Read each dimension's tracker.md. Extract findings that are NOT already
marked `accepted` or `rejected` by the adversarial rounds. For light reviews,
this is typically ALL findings (single round = no verification pass).

**2. Present all findings, then triage**

First, show every finding with full context — dimension, priority, and summary.
The user needs to see everything before deciding how to handle them:

```
## Review Findings — {N} unresolved

1. [coherence/P1] Missing error handling for X
   {2-3 sentence explanation from the tracker — what's wrong and why it matters}

2. [structure/P2] Component Y has circular dependency
   {explanation}

3. [robustness/P1] No fallback when Z fails
   {explanation}

...
```

Then present the triage choice via `AskUserQuestion`:

```python
AskUserQuestion(questions=[{
    "question": "How should these findings be handled?",
    "header": "Triage",
    "options": [
        {"label": "Incorporate all", "description": "Accept every finding and update the spec"},
        {"label": "Triage each", "description": "Walk through each finding — accept, reject, or defer"},
        {"label": "Skip", "description": "Leave findings in tracker only, no spec changes"},
    ],
    "multiSelect": false,
}])
```

**If "Incorporate all":** accept every finding, proceed to step 3.

**If "Triage each":** walk through findings one at a time using `AskUserQuestion`.
For each finding, show the full context and ask:

```python
AskUserQuestion(questions=[{
    "question": "[{dimension}/{priority}] {title} — {summary}. Accept this finding?",
    "header": "Finding {i}/{N}",
    "options": [
        {"label": "Accept", "description": "Incorporate into the spec"},
        {"label": "Reject", "description": "False positive or not applicable"},
        {"label": "Defer", "description": "Valid but out of scope for this iteration"},
    ],
    "multiSelect": false,
}])
```

Batch up to 4 findings per `AskUserQuestion` call (the tool supports 1-4
questions). Each question is one finding. This reduces round trips while
keeping the per-finding granularity.

**If "Skip":** no spec changes. Record all findings as "unresolved" in
decisions.md and end.

If zero unresolved findings (all resolved during adversarial rounds): skip
this step and proceed to "Resuming a failed/interrupted review" or end.

**3. Apply accepted findings**

For each accepted finding:
- Update the spec directly — add missing sections, fix inconsistencies,
  strengthen error handling, add constraints. The finding describes the gap;
  the fix goes into the spec prose, not as a comment or annotation.
- If a finding requires a design DECISION (multiple valid approaches), do NOT
  auto-resolve — flag it for brainstorming or add it to a `## Open Questions`
  section in the spec.

**4. Record decisions**

Write a `decisions.md` file in the review workspace (alongside tracker.md):

```markdown
# Review Decisions — {title}

## Accepted
- [coherence/P1] Missing error handling for X — added §Error Handling
- [robustness/P1] No fallback when Z fails — added retry + circuit breaker

## Rejected
- [structure/P2] Circular dependency — false positive, dependency is unidirectional

## Deferred
- [coherence/P2] Pagination not specified — out of scope for this iteration
```

**5. Commit the updated spec**

If any findings were accepted and the spec was modified:
- Stage the spec file
- Commit with message: `docs: incorporate {degree} design review findings Refs #N`

If no findings were accepted (all rejected/deferred/skipped): no commit needed.

## Resuming a failed/interrupted review

If the user says "resume the review" or a prior run was interrupted:

```bash
python3 ~/.claude/skills/design-review/review.py \
  --workspace {workspace_path} \
  --degree {degree} --source-dirs {dirs}
```

The script rebuilds tracker state from existing response files and resumes
from the next round. The degree is persisted in the workspace (`.depth` file)
and auto-loaded on resume, but passing `--degree` explicitly is recommended
as a safety net.

## Optional flags the user can request

| User says | Flag | Effect |
|-----------|------|--------|
| "light review" / "quick check" | `--degree light` | All dimensions, 1 round each |
| "standard review" | `--degree standard` | All dimensions, 2-3 rounds |
| "adversarial" / "stress test this" | `--degree adversarial` | All dimensions, 4-6 rounds |
| "deep review" / "thorough" / "ultrathink" | `--degree deep` | All dimensions, 8-10 rounds + ultrathink |
| "just coherence" / "completeness only" | `--type coherence` | Single dimension (no cross-cutting) |
| "just structure" | `--type structure` | Single dimension |
| "just robustness" / "try to break this" | `--type robustness` | Single dimension |
| "conformance review" / "code vs spec" | `--type conformance` | Single dimension |
| "readiness review" / "production check" | `--type readiness` | Single dimension |
| "use sonnet" / "cheap mode" | `--model sonnet` | Override model |
| "fresh sessions" / "no continuity" | `--fresh-sessions` | No session reuse |
| "more rounds" / "up to 15" | `--max-rounds 15` | Override round count |
| "use these arch files" | `--arch-files /path/...` | Extra context files |
| "diff against main" | `--diff-base main` | Show branch changes |
| Legacy: "pre-review this" | `--mode pre-review` | Maps to coherence/light |
| Legacy: "code review mode" | `--mode code-review` | Maps to conformance |

## What this skill does NOT do

- **Routine code review** — use `code-review` for pre-commit checklist review
- **Brainstorming** — use `brainstorming` to create the spec first,
  then use pre-review to validate the approach
- **Implementation** — this reviews design specs, not code

## Success Criteria

Design review is complete when:

- ✅ All issues tracked to resolution (accepted, rejected, or deferred)
- ✅ Spec updated to reflect accepted changes
- ✅ Decision log captures rationale for each resolution
- ✅ No open CRITICAL issues remain

**Not complete until** the review tracker shows zero unresolved items.

## Skill Chaining

**Invoked by:**
- User directly (`/design-review`, "review this design",
  "pre-review this", "tear this spec apart")
- `writing-plans` — conditionally, when review depth prompt selects a review (not Skip)
- `subagent-driven-development` — after implementation, SDD may invoke
  design-review `--mode final-review` for adversarial review
- `work-end` — before branch closure, work-end may invoke design-review
  for final validation

**Invokes:** None — runs an external Python orchestration script; does not
delegate to other skills

**Complements:**
- `brainstorming` — brainstorming creates the spec; design-review validates it
  (pre-review mode for approach, spec-review mode for detail)
- `verification-before-completion` — run VBC after design-review resolves
  all issues and before committing the updated spec
- `code-review` — different scope. design-review is multi-round adversarial
  review of design specs. code-review is routine pre-commit checklist review
  of staged changes

**Boundary with code-review:** design-review --mode code-review checks whether implementation matches the spec. code-review checks code quality, safety, and style on staged changes.

**Reads from:** User-provided spec path, CLAUDE.md for source directories,
`.spec-path` and `progress.log` in the workspace for resume
