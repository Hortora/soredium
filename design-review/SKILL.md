---
name: design-review
description: >
  Use when a design spec needs adversarial review — user says "review this design",
  "design review", "tear this spec apart", or invokes /design-review.
  Orchestrates two independent Claude sessions (reviewer + implementor) with a Python PM
  tracking every issue to evidence-based resolution. NOT for code review (use code-review).
  NOT for brainstorming (use superpowers:brainstorming).
---

# Adversarial Design Review

Orchestrates adversarial design review between independent Claude sessions with
issue-level tracking, evidence-based verification, and human-in-the-loop escalation.

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
  --source-dirs {dirs}
```

Use `run_in_background: true` on the Bash tool call.

## Step 6 — Monitor and report

After launching, periodically check the progress log:

```bash
cat ~/adr/*/{title}-*/progress.log 2>/dev/null | tail -20
```

Report progress to the user when you see updates.

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

**Never silently spin.** If 2 minutes pass with no progress log updates, check what's happening
and report to the user.

## Step 8 — Present results

When the review completes, summarize:
- Total rounds and issues raised
- How many verified, accepted, deferred
- Cost
- Where to find the final spec and tracker

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
| "use sonnet" / "cheap mode" | `--model sonnet` |
| "fresh sessions" / "no continuity" | `--fresh-sessions` |
| "more rounds" / "up to 15" | `--max-rounds 15` |
| "shorter windows" | `--session-window 3` |

## What this skill does NOT do

- **Code review** — use `code-review` for that
- **Brainstorming** — use `superpowers:brainstorming` to create the spec first
- **Implementation** — this reviews design specs, not code
