#!/usr/bin/env bash
# garden-agent-install.sh — idempotent installer for the garden dedup agent.
# Run from inside a garden directory (or set HORTORA_GARDEN).
# No tokens consumed. Safe to run multiple times.

set -euo pipefail

GARDEN="${HORTORA_GARDEN:-$(pwd)}"
PASS="✓"
SKIP="–"

echo "Garden Agent Installer"
echo "Garden: $GARDEN"
echo ""

# ── garden-agent.sh ──────────────────────────────────────────────────────────
AGENT_SH="$GARDEN/garden-agent.sh"
if [[ -f "$AGENT_SH" ]]; then
    echo "$SKIP  garden-agent.sh            already present"
else
    cat > "$AGENT_SH" << 'AGENT_EOF'
#!/usr/bin/env bash
# garden-agent.sh — invoke Claude harvest+dedup agent (hook or manual mode).
GARDEN_ROOT="${HORTORA_GARDEN:-$HOME/.hortora/garden}"
LOG="$GARDEN_ROOT/garden-agent.log"
LOCK="$GARDEN_ROOT/garden-agent.lock"
TASK="You are the Hortora garden agent. Merge open forage PRs and run the dedup sweep as described in CLAUDE.md."

# Acquire lockfile — prevent concurrent runs (mkdir is atomic).
if ! mkdir "$LOCK" 2>/dev/null; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] garden-agent already running, skipping" >> "$LOG"
    exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

if [[ "$1" == "--hook" ]] || [[ ! -t 0 ]]; then
    # Rotate log at 1MB, keep last 5
    if [[ -f "$LOG" ]] && [[ $(wc -c < "$LOG") -gt 1048576 ]]; then
        for i in 4 3 2 1; do
            [[ -f "${LOG}.$i" ]] && mv "${LOG}.$i" "${LOG}.$((i+1))"
        done
        mv "$LOG" "${LOG}.1"
    fi
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] garden-agent starting" >> "$LOG"
    claude --print "$TASK" >> "$LOG" 2>&1
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] garden-agent done" >> "$LOG"
else
    claude "$TASK"
fi
AGENT_EOF
    chmod +x "$AGENT_SH"
    echo "$PASS  garden-agent.sh            installed"
fi

# ── run-scanner.sh ───────────────────────────────────────────────────────────
SCANNER_SH="$GARDEN/run-scanner.sh"
if [[ -f "$SCANNER_SH" ]]; then
    echo "$SKIP  run-scanner.sh             already present"
else
    cat > "$SCANNER_SH" << 'SCANNER_EOF'
#!/usr/bin/env bash
# Wrapper so the garden agent calls dedupe_scanner.py without shell expansions.
# The agent calls: bash run-scanner.sh [args...]
SOREDIUM="${SOREDIUM_PATH:-$HOME/claude/hortora/soredium}"
exec python3 "$SOREDIUM/scripts/dedupe_scanner.py" "$@"
SCANNER_EOF
    chmod +x "$SCANNER_SH"
    echo "$PASS  run-scanner.sh             installed"
fi

# ── .claude/settings.json ────────────────────────────────────────────────────
SETTINGS_DIR="$GARDEN/.claude"
SETTINGS="$SETTINGS_DIR/settings.json"
if [[ -f "$SETTINGS" ]]; then
    echo "$SKIP  .claude/settings.json      already present"
else
    mkdir -p "$SETTINGS_DIR"
    cat > "$SETTINGS" << 'SETTINGS_EOF'
{
  "defaultMode": "acceptEdits",
  "permissions": {
    "allow": [
      "Bash(git show *)",
      "Bash(git log *)",
      "Bash(git status *)",
      "Bash(git add *)",
      "Bash(git commit *)",
      "Bash(git diff *)",
      "Bash(git pull *)",
      "Bash(bash run-scanner.sh *)",
      "Bash(python3 */validate_garden.py *)",
      "Bash(gh pr list *)",
      "Bash(gh pr merge *)",
      "Bash(gh pr view *)"
    ],
    "deny": []
  }
}
SETTINGS_EOF
    echo "$PASS  .claude/settings.json      installed"
fi

# ── CLAUDE.md ─────────────────────────────────────────────────────────────────
CLAUDE_MD="$GARDEN/CLAUDE.md"
if [[ -f "$CLAUDE_MD" ]]; then
    echo "$SKIP  CLAUDE.md                  already present"
else
    cat > "$CLAUDE_MD" << 'CLAUDE_EOF'
# Garden Deduplication Agent

You are the Hortora garden deduplication agent. When invoked, merge open forage
PRs then run a full dedup sweep, committing results without asking for confirmation.

## Environment

- Garden root: current working directory
- Scanner: call `bash run-scanner.sh` — this wrapper resolves SOREDIUM_PATH
  and delegates to dedupe_scanner.py without shell expansions in the command.
  Example: `bash run-scanner.sh . --top 50`
  Example: `bash run-scanner.sh . --record "GE-X × GE-Y" distinct "note"`
- All reads via `git show HEAD:<path>` — never read files directly

## Workflow

### Phase 1 — Merge open PRs

1. List open PRs: `gh pr list --state open --json number,title`
2. For each open PR, issue one separate Bash call per PR (not a loop):
   `gh pr merge <number> --squash --delete-branch`
3. Pull merged commits: `git pull`

Skip to Phase 2 if no open PRs.

### Phase 2 — Dedup sweep

1. Run `bash run-scanner.sh . --top 50` to get unchecked pairs, highest score first
2. For each pair, read both entries: `git show HEAD:<domain>/<id>.md | head -35`
3. Classify and act:

| Classification | Action |
|---|---|
| **Distinct** | `bash run-scanner.sh . --record "GE-X × GE-Y" distinct "note"` |
| **Related** | Append `**See also:**` line to both files, then record as `related` |
| **Duplicate** | Apply duplicate rules below |

4. Commit: `git add -A && git commit -m "dedupe: sweep N pairs — M related, K duplicates resolved"`

Skip the commit if no pairs were processed.

## Duplicate Rules

Keep the entry with the higher `score:` in frontmatter. If tied, keep the
newer `submitted:` date. If still tied, keep the longer entry (line count).

Delete the discarded file. Append to `DISCARDED.md`. Remove from `GARDEN.md`
index if present. Record as `duplicate-discarded`.

## Tiebreaker order

Score → submitted date → line count (keep longer).
CLAUDE_EOF
    echo "$PASS  CLAUDE.md                  installed"
fi

# ── .git/hooks/post-commit ───────────────────────────────────────────────────
HOOK="$GARDEN/.git/hooks/post-commit"
SENTINEL="# garden-agent: auto-installed"
if [[ -f "$HOOK" ]] && grep -q "$SENTINEL" "$HOOK"; then
    echo "$SKIP  .git/hooks/post-commit     already present"
else
    cat >> "$HOOK" << 'HOOK_EOF'
# garden-agent: auto-installed
# Fire garden agent after any non-dedupe commit — merges open PRs then dedupes.
_GARDEN_ROOT="$(git rev-parse --show-toplevel)"
_LOG="$_GARDEN_ROOT/garden-agent.log"
_commit_msg=$(git log -1 --format="%s")
if echo "$_commit_msg" | grep -qE "^dedupe:"; then
    exit 0
fi
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] commit detected, starting agent" >> "$_LOG"
nohup "$_GARDEN_ROOT/garden-agent.sh" --hook >> "$_LOG" 2>&1 &
HOOK_EOF
    chmod +x "$HOOK"
    echo "$PASS  .git/hooks/post-commit     installed"
fi

# ── .gitignore ────────────────────────────────────────────────────────────────
GITIGNORE="$GARDEN/.gitignore"
if [[ -f "$GITIGNORE" ]] && grep -q "garden-agent.log" "$GITIGNORE"; then
    echo "$SKIP  .gitignore                 already present"
else
    printf "garden-agent.log\ngarden-agent.log.*\ngarden-agent.lock\n" >> "$GITIGNORE"
    echo "$PASS  .gitignore                 updated"
fi
