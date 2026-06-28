### Missing aggregate boundary for billing

The Invoice aggregate has no upper bound on line items. Unbounded aggregates
cause consistency problems under load — a single invoice with 10K line items
would exceed the event store's payload limit.

Impact: Data loss or silent truncation when invoices exceed payload limits.

Recommendation: Define a maximum line item count with batch splitting for
larger invoices.

### No failure mode for payment timeout

The spec defines PAYMENT_PENDING but no terminal failure state. If the
payment gateway times out after retries, the invoice is stuck in PENDING
indefinitely.

Impact: Orphaned invoices accumulate, requiring manual intervention.

Recommendation: Add a terminal PAYMENT_FAILED state after N retries with
exponential backoff.

### Event schema missing correlation ID

The InvoiceCreated event schema doesn't include a correlationId. This
breaks the existing tracing contract documented in billing/events.md.

Impact: Distributed tracing across the billing pipeline is broken for
new invoices.

Recommendation: Add correlationId to InvoiceCreated following the
existing event contract pattern.

ASSUMPTION: Event store supports exactly-once delivery

---
SIGNAL: CONTINUE
