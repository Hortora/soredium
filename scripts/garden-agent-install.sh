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
# garden-agent.sh — invoke Claude dedup agent (hook or manual mode).
GARDEN_ROOT="${HORTORA_GARDEN:-$(pwd)}"
LOG="$GARDEN_ROOT/garden-agent.log"
TASK="You are the Hortora garden deduplication agent. Run the dedup sweep as described in CLAUDE.md."

if [[ "$1" == "--hook" ]] || [[ ! -t 0 ]]; then
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
      "Bash(python3 */dedupe_scanner.py *)",
      "Bash(python3 */validate_garden.py *)"
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

You are the Hortora garden deduplication agent. When invoked, run a full
dedup sweep and commit the results without asking for confirmation.

## Environment

- Garden root: current working directory
- Scanner: `python3 ${SOREDIUM_PATH:-~/claude/hortora/soredium}/scripts/dedupe_scanner.py .`
- All reads via `git show HEAD:<path>` — never read files directly

## Workflow

1. Run `dedupe_scanner.py . --top 50` to get unchecked pairs, highest score first
2. For each pair, read both entries: `git show HEAD:<domain>/<id>.md | head -35`
3. Classify and act:

| Classification | Action |
|---|---|
| **Distinct** | `--record` as `distinct` |
| **Related** | Append `**See also:**` line to both files, `--record` as `related` |
| **Duplicate** | Apply duplicate rules below |

4. Commit: `git add -A && git commit -m "dedupe: sweep N pairs — M related, K duplicates resolved"`

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
# Fire garden dedup agent when a commit adds new GE-*.md entries.
_GARDEN_ROOT="$(git rev-parse --show-toplevel)"
_LOG="$_GARDEN_ROOT/garden-agent.log"
_new_entries=$(git diff --name-only HEAD~1 HEAD 2>/dev/null \
  | grep -E "^[^/]+/GE-[0-9]{8}-[0-9a-f]{6}\.md$")
if [[ -n "$_new_entries" ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] new entries detected, starting agent:" >> "$_LOG"
    echo "$_new_entries" | sed 's/^/  /' >> "$_LOG"
    nohup "$_GARDEN_ROOT/garden-agent.sh" --hook >> "$_LOG" 2>&1 &
fi
HOOK_EOF
    chmod +x "$HOOK"
    echo "$PASS  .git/hooks/post-commit     installed"
fi

# ── .gitignore ────────────────────────────────────────────────────────────────
GITIGNORE="$GARDEN/.gitignore"
if [[ -f "$GITIGNORE" ]] && grep -q "garden-agent.log" "$GITIGNORE"; then
    echo "$SKIP  .gitignore                 already present"
else
    echo "garden-agent.log" >> "$GITIGNORE"
    echo "$PASS  .gitignore                 updated"
fi
