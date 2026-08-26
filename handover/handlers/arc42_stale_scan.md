# Handler: arc42_stale_scan

Scan ARC42STORIES.MD for staleness from cross-session and cross-repo work.

## Three things to scan

### 1. Layer/chapter statuses not reflecting closed issues

Read the layer taxonomy table and chapter index. For each `🔲 pending (#NNN)`:
```bash
gh issue view <NNN> --repo <OWNER_REPO> --json state --jq '.state'
```
If CLOSED but row says pending → stale.

### 2. External blocker references that have resolved

Scan for `blocked on`, `pending casehubio/`, `waiting on`, `requires`
followed by cross-repo issue references:
```bash
gh issue view NNN --repo "casehubio/REPO" --json state --jq '.state'
```
If blocker is CLOSED → stale.

### 3. Forward-tense issue references where issue is closed

Scan for `#NNN will`, `will migrate`, `will add` etc. Check if issue
is CLOSED → update to past tense.

## Report and fix

Present each finding with exact line and proposed fix. Apply on confirmation:
```bash
python3 ~/.claude/skills/git-commit/commit_exec.py commit "$PROJECT" message="docs: sync ARC42STORIES.MD — stale scan at session wrap" files=ARC42STORIES.MD
```

If nothing stale → proceed silently.
