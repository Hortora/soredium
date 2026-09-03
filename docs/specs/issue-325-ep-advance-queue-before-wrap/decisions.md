## D1: Queue advancement timing relative to session choice

**Choice:** Advance unconditionally before offering session choice. Step 4 becomes a three-phase sequence: (1) advance queue mechanically if ALL_DONE + remaining issues, (2) offer continue/wrap, (3) queue-complete path unchanged.
**Alternatives:**
- Prevent wrap until work next is run — equivalent outcome but harder for LLM to follow (negative constraint vs positive sequence)
**Rationale:** Queue advancement is a mechanical consequence of task completion, not a session-level user choice. A completed issue should always be advanced regardless of whether the user continues or wraps.
**Trade-offs:** None — the current behavior is a bug, not a design trade-off.
**Sources:** GitHub issue #325 reproducer and root cause analysis; executing-plans/SKILL.md Step 2 (batch logic already correct) and Step 4 (the broken path)
**Exploration:** quick
**Status:** captured
