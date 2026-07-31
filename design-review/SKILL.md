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

## Step 0.5 — Select review type and degree

Reviews have two dimensions: **type** (what to examine) and **degree** (how deeply).
See [review-tiers.md](review-tiers.md) for the full model and recommendation signals.

**Three-part flow:**

1. **Present full recommendation as text** — analyze the spec for complexity signals,
   then present the recommended type, degree, and reasoning. Be specific to this spec.

2. **Type selection via AskUserQuestion** — recommended option first with "(Recommended)".
   Skip is always an option.

```python
AskUserQuestion(questions=[{
    "question": "Review this spec?",
    "header": "Review type",
    "options": [
        {"label": "<Recommended> (Recommended)", "description": "<reasoning>"},
        {"label": "Skip", "description": "No review needed"},
        {"label": "Coherence", "description": "Completeness, consistency, gaps"},
        {"label": "Structure", "description": "Decomposition, boundaries, dependencies"},
        {"label": "Robustness", "description": "Failure modes, edge cases, error paths"},
    ],
    "multiSelect": false,
}])
```

3. **Degree selection via AskUserQuestion** (if not Skip):

```python
AskUserQuestion(questions=[{
    "question": "Review degree?",
    "header": "Depth",
    "options": [
        {"label": "<Recommended> (Recommended)", "description": "<reasoning>"},
        {"label": "Light", "description": "~1 min — quick pass, flags if deeper needed"},
        {"label": "Standard", "description": "~5 min — thorough examination"},
        {"label": "Adversarial", "description": "~12 min — actively tries to break the design"},
        {"label": "Deep", "description": "~25 min — exhaustive, ultrathink enabled"},
    ],
    "multiSelect": false,
}])
```

**If invoked with explicit flags** (`/design-review --type robustness --degree deep`):
skip the prompt and use the flags directly.

**If the user just says "design review"** without specifying type or asking to choose:
still show the recommendation and prompt — the recommendation helps the user pick the
right depth rather than defaulting to the heaviest option.

**Mapping to `--type` and `--degree`:**

| Type | `--type` flag | Default degree |
|------|--------------|----------------|
| Coherence | `coherence` | Light |
| Structure | `structure` | Standard |
| Robustness | `robustness` | Adversarial |
| Conformance | `conformance` | Standard |
| Readiness | `readiness` | Standard |

**Backward compat:** `--mode pre-review|spec-review|code-review|final-review` still
accepted and mapped to the new types. `--depth` accepted as alias for `--degree`.

**After the review completes (light/standard):** check the review output for an
escalation assessment. If `ESCALATE: yes`, present the recommendation to the user
and ask whether to proceed with the escalated review.

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
ls -d ~/adr/*/{title}-* 2>/dev/null
```

If a workspace exists:
- Check its `progress.log` to see how far it got
- Ask the user: **"Found existing workspace at {path} with {n} round(s) completed. Resume it or start fresh?"**
- If resume: use `--workspace {path}` instead of `--spec`
- If fresh: delete the old workspace first

**Never silently create a duplicate workspace.** The user has already spent tokens on the prior run.

## Step 4 — Run the review

**IMPORTANT: This is a long-running process (10-30 minutes). Do NOT run it
inline with the Bash tool — the output will be captured and invisible to the
user until the process finishes or times out.**

Tell the user BEFORE running:
> Starting adversarial design review of **{title}**.
>
> This runs as a background process. I'll check progress periodically.
> You can also monitor directly:
> - `tail -f ~/adr/*/{title}-*/progress.log`
> - Open `~/adr/*/{title}-*/tracker.md` in Typora

Then run in the background:

```bash
python3 /Users/mdproctor/.claude/skills/design-review/review.py \
  --spec {spec_path} \
  --title {title} \
  --mode {mode} \
  --stage {maturity_stage} \
  --source-dirs {dirs}
```

Where `{mode}` is `pre-review` or `spec-review` based on the phase selected
in Step 0.5. If mode is `spec-review` (the default), you may omit `--mode`.

`{maturity_stage}` comes from `MATURITY_STAGE` in the ctx.py output. If `pre-release`
(the default), you may omit `--stage`.

Use `run_in_background: true` on the Bash tool call.

## Step 5 — Set up watchdog

**Immediately after launching the background process**, create a cron watchdog
to monitor progress. This is mandatory — without it, stalls go undetected.

Use `CronCreate` with a 5-minute interval and this prompt:

> Check the design review progress for {title}. Read the last 10 lines of
> ~/adr/*/{title}-*/progress.log.
>
> Terminal status lines:
> - `REVIEW DONE` — read tracker.md AND the spec (symlinked at spec.md in
>   the workspace). Validate that the review's changes are present in the
>   spec, then report results. Delete this cron job.
> - `REVIEW PAUSED` — the review needs human input (timeout or SIGTERM).
>   Tell the user what happened and offer to resume.
> - `REVIEW ABORTED` — user chose to abort. Report and delete cron.
> - `REVIEW FAILED` / `REVIEW CRASHED` — report the error, suggest resuming.
> - `REVIEW INTERRUPTED` — KeyboardInterrupt. Suggest resuming.
>
> Also check for `.hil-timeout` marker file in the workspace. If it exists,
> the agent hit the soft timeout (600s) and is still running (up to 1800s
> hard timeout). Read the marker, tell the user the agent is still exploring,
> and ask: continue or kill? If kill, write "kill" to the marker file.
> If continue, write "extend" to reset the timer.
>
> If progress.log exists but hasn't been updated in 10+ minutes and no
> terminal line is present, warn the user that the review appears stalled.

Set `recurring: true`. Store the cron job ID so you can delete it when the
review completes.

## Step 6 — Handle notifications

You will receive notifications from two sources:

1. **Background task completion** — the Bash `run_in_background` notification
   fires when the Python process exits. Read progress.log to determine outcome.
2. **Watchdog cron** — fires every 5 minutes with a progress check.

On either notification:
- If the review completed: present results, delete the watchdog cron
- If it failed/crashed: report the error, suggest resuming, delete the cron
- If stalled: warn the user, suggest resuming or checking IntelliJ

## Step 7 — Handle failures

If the process exits with an error:

1. Read the progress log to understand where it failed
2. Check if it's a permission issue (common: `claude -p` needs permission approval)
   - Fix: suggest the user run `! python3 /Users/mdproctor/.claude/skills/design-review/review.py ...`
     from the prompt (the `!` prefix runs it in the foreground with visible prompts)
3. Check if it's a timeout (SESSION_TIMEOUT = 600s per claude -p call)
4. Report the error clearly to the user with the specific failure
5. If the workspace was partially created, suggest resuming:
   ```bash
   python3 /Users/mdproctor/.claude/skills/design-review/review.py \
     --workspace ~/adr/{project}/{title}-{timestamp}/ \
     --source-dirs {dirs}
   ```

## Step 8 — Validate and present results

When the review completes:

1. **Read the final spec** — the spec is symlinked at `spec.md` in the workspace
   (or read the path from `.spec-path`). Read it end to end.
2. **Read the tracker** — `tracker.md` in the workspace. Check which items are
   verified, accepted, deferred, and any still unresolved.
3. **Validate** — confirm the tracker's verified/accepted items are actually
   reflected in the spec. Don't trust the tracker alone — the spec is the evidence.
4. **Report** — use this exact template (fill in values, omit lines that are 0):

```
Design review complete.

- {N} rounds, {M} issues raised
- {V} verified (reviewer confirmed fixes in the spec)
- {A} accepted (reviewer accepted implementor's rejection)
- {D} deferred
- {U} unresolved
- Cost: ${C}
- Health: {no issues | N timeout(s), M error(s)}
- Spec: file://{spec_path}

{If unresolved items exist, list each with ID, title, and status}
```

Do NOT substitute a narrative summary for this template. The structured
format is what the user needs to make a go/no-go decision. You can add
a brief narrative AFTER the template if the review surfaced notable
findings worth highlighting.

## Resuming a failed/interrupted review

If the user says "resume the review" or a prior run was interrupted:

```bash
python3 /Users/mdproctor/.claude/skills/design-review/review.py \
  --workspace {workspace_path} \
  --source-dirs {dirs}
```

The script rebuilds tracker state from existing response files and resumes
from the next round.

## Optional flags the user can request

| User says | Flag |
|-----------|------|
| "coherence check" / "completeness review" | `--type coherence` |
| "structure review" / "architecture review" | `--type structure` |
| "robustness review" / "try to break this" | `--type robustness` |
| "conformance review" / "code vs spec" | `--type conformance` |
| "readiness review" / "production check" | `--type readiness` |
| "light review" / "quick check" | `--degree light` |
| "standard review" | `--degree standard` |
| "adversarial" / "stress test this" | `--degree adversarial` |
| "deep review" / "thorough" / "ultrathink" | `--degree deep` |
| "use sonnet" / "cheap mode" | `--model sonnet` |
| "fresh sessions" / "no continuity" | `--fresh-sessions` |
| "more rounds" / "up to 15" | `--max-rounds 15` |
| "shorter windows" | `--session-window 3` |
| "use these arch files" / specific arch context | `--arch-files /path/to/PLATFORM.md /path/to/ARC42.md` |
| "diff against main" / "changes since release" | `--diff-base main` or `--diff-base v1.0` |
| Legacy: "pre-review this" | `--mode pre-review` (maps to `--type coherence --degree light`) |
| Legacy: "code review mode" | `--mode code-review` (maps to `--type conformance`) |

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
