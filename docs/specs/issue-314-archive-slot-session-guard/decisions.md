## D1: Detection method

**Choice:** lsof CWD check — run `lsof +D <slot_dir>` to find processes with CWD inside the slot
**Alternatives:**
- JSONL mtime — fast but false-negatives on idle sessions, false-positives from background tasks
- psutil CWD scan — portable but adds a dependency
- PID file — no PID files exist in Claude project directories
**Rationale:** Definitive — if a process has its CWD in the slot, it IS active. No false positives or negatives. Works on macOS and Linux. ~1s overhead is acceptable for an archival operation.
**Trade-offs:** Requires lsof on PATH. Not available on all platforms (Windows).
**Sources:** slot_claude.py (existing session management), incident description
**Exploration:** quick
**Status:** captured

## D2: Override behavior

**Choice:** --force overrides the active session guard
**Alternatives:**
- Absolute block — active session = never archive, even with --force
- Separate --ignore-sessions flag
**Rationale:** --force already overrides landed/SHA checks. Adding session guard to the same flag is consistent. User takes responsibility.
**Trade-offs:** User might accidentally force-archive an active session. Mitigated by printing WARN with session details.
**Sources:** slot_lifecycle.py:601-605 (existing --force pattern)
**Exploration:** quick
**Status:** captured

## D3: Revised detection (PID unavailable)

**Choice:** lsof CWD check over PID check — no PID files exist in Claude project dirs
**Alternatives:** (revision of D1 after discovery)
**Rationale:** Claude Code stores only .jsonl conversation logs in project dirs. No .pid file. lsof is the only definitive method without adding new metadata.
**Trade-offs:** lsof scans are heavier than PID checks. Acceptable for archival (one-time operation).
**Sources:** ~/.claude/projects/ directory inspection
**Exploration:** quick
**Status:** captured
