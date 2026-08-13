## D1: DB-authoritative numbering with inline drift detection

**Choice:** Approach A — DB as authority for slot numbering, inline drift detection on list, repeatable reconciliation script
**Alternatives:**
- Approach B (separate health command) — drift only detected when manually run
- Approach C (disk-authoritative with DB cache) — doesn't fix the numbering collision root cause
- File-based monotonic counter (`slots/.next-slot`) — simpler, no DB dependency, but adds a third source of truth that can also diverge, and doesn't provide drift detection or audit trail
**Rationale:** The DB already exists and is maintained. Making it authoritative for numbering prevents future collisions at the source. Inline drift detection on list is zero-cost since list already iterates all slots.
**Trade-offs:** DB becomes a critical-path dependency for slot creation (see D3, D4). This is an intentional architectural shift from the worklog's current informational role — justified because numbering collisions have already caused real data integrity issues.
**Exploration:** quick
**Status:** revised (R1-02: removed fallback language contradicting D3; R1-04: added counter-file alternative with rejection rationale; R1-10: changed one-time to repeatable)

## D2: Reconciliation is audit-first, strategy-second, execute-third

**Choice:** Three-phase repeatable reconciliation: audit (report all divergences with full detail and taxonomy), strategy (propose actions with risk assessment, user approves), execute (apply only approved actions, log everything, quarantine rather than delete)
**Alternatives:**
- Single-pass fix-it script — faster but risks silent data loss
- Manual cleanup — too tedious with 24+ collisions across two families
**Rationale:** Ghost directories look safe to delete based on spot checks, but we haven't exhaustively verified every one. Audit-first means every divergence is visible before any action. Quarantine over delete means mistakes are reversible.
**Trade-offs:** Three phases is more ceremony than a one-shot fix, but the downside of losing work far outweighs the cost of reviewing an audit report
**Depends on:** D1 (divergence taxonomy and remediation strategies depend on which source is authoritative)
**Exploration:** quick
**Status:** revised (R1-10: repeatable not one-time — @safe write failures can produce new divergences; R1-11: added divergence taxonomy requirement)

### Divergence taxonomy (from R1-11)

The audit phase classifies each divergence:

| Type | Description | Risk |
|------|-------------|------|
| `db-only` | DB record exists, no disk directory | Low — DB stale, no data to lose |
| `disk-only` | Disk directory exists, no DB record | Medium — slot works but invisible to DB queries |
| `state-mismatch` | Both exist but disagree on state (e.g., DB says active, disk in attic) | Medium — misleading reports |
| `ghost` | Directory exists at slot path with no `.slot` file | Low — remnant, not real slot data |
| `collision` | Same number in both `slots/N/` and `slots/attic/N/` | High if both have `.slot` — potential data confusion |

## D3: Hard fail when DB is unavailable for slot numbering

**Choice:** Hard fail — refuse to create a slot if the worklog DB cannot be queried for the next slot number
**Alternatives:**
- Graceful fallback to disk scan — same behavior as today, but risks numbering collisions in the exact scenario the fix is meant to prevent
**Rationale:** The entire point of D1 is to make the DB authoritative. A fallback to disk scan reintroduces the collision risk. If the DB is unavailable, the user should fix that before creating slots — it's a rare edge case and the cost of blocking is low compared to the cost of another numbering collision.
**Trade-offs:** Blocks slot creation if DB is temporarily unavailable (file lock, corruption). User must resolve DB issue before proceeding. Acceptable because DB unavailability is rare and the fix is usually trivial (kill stale lock, rebuild from disk audit).
**Exploration:** quick
**Status:** captured

## D4: Slot creation DB write must propagate errors

**Choice:** `record_slot_create()` must NOT use `@safe` for the slot numbering path — if the DB write fails, slot creation fails. The allocated number is only valid if persisted to the DB.
**Alternatives:**
- Keep `@safe` on all worklog writes — current behavior, but allows DB to silently miss slot creation, causing `MAX(slot_number)+1` to allocate a duplicate on the next call
**Rationale:** Authoritative reads (D3) without authoritative writes is architecturally incoherent. If `record_slot_create()` silently fails, the next `allocate_slot_number()` call reads stale state and allocates a collision. The write that establishes the number must succeed or the operation must fail.
**Trade-offs:** Changes the worklog contract for this specific function — `record_slot_create` becomes critical-path while other worklog functions (`record_work_start`, `record_slot_archive`, etc.) remain informational/best-effort with `@safe`. This is deliberate: numbering authority requires write durability, event logging does not.
**Depends on:** D1, D3
**Exploration:** quick (surfaced by decision review R1-03)
**Status:** captured
