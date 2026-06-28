### R1-01: FIXED
Updated §2.3 with a maximum of 500 line items per invoice. Invoices
exceeding this limit are automatically split into batches using the
InvoiceBatchSaga.

### R1-02: FIXED
Updated §4.1 with a terminal PAYMENT_FAILED state. After 3 retries
with exponential backoff (1s, 4s, 16s), the invoice transitions to
PAYMENT_FAILED and a notification is emitted.

### R1-03: REJECTED
The correlationId is already present in the event envelope, not the
event payload. Adding it to the payload would duplicate infrastructure
concerns into the domain model. The tracing contract in billing/events.md
specifies envelope-level correlation, not payload-level.

SETTLED: Maximum 500 line items per aggregate with batch splitting (from R1-01)

---
SIGNAL: CONTINUE
