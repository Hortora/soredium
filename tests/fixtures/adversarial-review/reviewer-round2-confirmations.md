### R1-02 — Concurrent modification during payment retries

The retry policy is good but the invoice state during retries is
PAYMENT_PENDING, which doesn't prevent concurrent modification. Two
payment attempts could run simultaneously.

Impact: Double-charge or inconsistent invoice state.

Recommendation: Add optimistic locking with a version field.

### Missing batch orchestration

Batch splitting for large invoices is defined but no orchestration
mechanism coordinates the batch. Who ensures all sub-invoices complete?

Impact: Partial batch processing with no recovery path.

Recommendation: Define a saga or orchestrator for batch coordination.

## Addressed Items
- R1-01: resolved
- R1-02: still open — concurrent modification during retries not addressed
- R1-03: resolved

ASSUMPTION: Payment gateway idempotency window is 24h

---
SIGNAL: CONTINUE
