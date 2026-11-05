# ADR-0017: Separate Queue from Ceremony State

- **Status:** Accepted
- **Date:** 2026-11-05
- **Supersedes:** ADR-0013 (unified .plan)

## Context

ADR-0013 unified the issue queue and lifecycle state into a single `.plan`
file with a `state:` field tracking 12 lifecycle states
(`active → closing:review → ... → closing:stamped → idle`).

This coupling caused 12 plan-destruction bugs (tracked via #498) because:

1. **Seven deletion paths** cleared `.plan` during ceremony cleanup, destroying
   the issue queue along with ephemeral ceremony state
2. **State corruption** during failed ceremonies left the queue in an
   unrecoverable state
3. **Complexity** — 620 lines of corruption detection code existed solely to
   detect and recover from coupling-induced state inconsistencies
4. The lifecycle state machine (lifecycle.py, 400+ LOC) enforced transitions
   between states that only existed because queue and ceremony were coupled

## Decision

Separate the issue queue from close-ceremony state:

- **`.queue`** — persistent issue queue (items, branch, issue-repo, status).
  Status has 4 values: `active | paused | drained | idle`. Never deleted
  during normal operation.
- **`.close-state`** — ephemeral ceremony state (step, session_id, repos).
  Created at ceremony start, deleted on success. Presence means "ceremony
  in progress."

The close ceremony (`work-end/close.py`) is a single Python invocation that
either succeeds or fails cleanly. It reads `.queue` and git state; lands
branches, stamps, advances the queue. Each step is idempotent.

## Consequences

### Positive

- Queue is never destroyed by ceremony cleanup — the 7 deletion paths are
  eliminated
- 620 lines of corruption detection replaced by ~30 lines of queue validation
- Lifecycle state machine (400+ LOC) replaced by a 4-value status field
- Pre-push hook checks for `.close-state` existence instead of parsing
  lifecycle states
- Close ceremony is ~300 LOC instead of ~10,800 LOC

### Negative

- Two files where there was one (`.queue` + `.close-state`)
- Migration path needed: `.plan` → `.queue` (handled by `queue_io.migrate_plan_to_queue`)
- Transition period where both `META_STATE` and `QUEUE_STATUS` are output
  by ctx.py

### Neutral

- `plan_manager.py` retains its name — it manages lifecycle state beyond
  just the queue, and renaming is a follow-up
