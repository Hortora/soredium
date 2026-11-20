---
id: PP-20261120-ae7fd4
title: "A test that pins a rule must fail with the rule removed, and must hand the code what a real caller would"
type: rule
scope: repo
applies_to: "New or changed tests for routing, location and guard rules in project/, work-end/, work-slot/"
severity: important
refs:
  - tests/test_work_wrap_end.py
violation_hint: "End-to-end tests that pass the right path or id explicitly; a test that sets the isolation it claims to verify; no record of the tests failing against the old behaviour"
garden_ref: "GE-20261120-e8581e"
created: 2026-11-20
---

Before a test is trusted as evidence for a rule, break the rule on purpose (make the deciding function return the old answer), run the tests that claim to pin it, see them fail, and restore the code with a checkout. The harness must supply the input the real caller supplies in the state being guarded against: for "never be led to the inherited queue", hand the pipeline the inherited queue's path and assert its bytes and git status are unchanged afterwards. Tests for the root-queue rule first passed with the rule deleted; rewritten this way they found a step still writing to the wrong file.
