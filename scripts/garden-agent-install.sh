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
