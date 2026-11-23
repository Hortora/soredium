# Decisions — #590

## D1: When to offer wrap_or_continue

**Choice:** Only after `work done` — never on `continue` or `start`
**Alternatives:**
- Session-awareness flag (suppress on first call per session) — same result, more complex
- Skill-layer heuristic (LLM judges "substantive work") — fragile, unreliable
**Rationale:** Work end needs the session's context (review material, decisions, diary). A fresh session has none of this. Done items waiting is information, not a gate.
**Trade-offs:** If a user finishes work and then types `work continue` instead of `work done`, they won't see the offer. That's fine — `work wrap` and `work end` are always available as explicit commands.
**Sources:** project/work_route.py:78 (offer = bool(done)), work skill OFFER=wrap_or_continue handler
**Exploration:** quick
**Status:** captured

## D2: Clone guard decision flow

**Choice:** Follow the move-on-gate pattern — `ACTION=decision` with handler file
**Alternatives:**
- Inline the decision in work.py (no handler file) — loses the handler pattern's separation of concerns
- Auto-create the clone without asking — violates propose-before-execute, creates a clone the user may not want
**Rationale:** The platform already has `ACTION=decision` with `DECISION=` / `OPTIONS=` / handler dispatch. Clone guard should use the same mechanism as move-on-gate.
**Trade-offs:** None significant — this is the natural pattern.
**Sources:** project/work.py:162-195 (current guard), work/handlers/move-on-gate.md (model handler), project/clone_manager.py:51 (create_clone)
**Exploration:** quick
**Status:** captured
