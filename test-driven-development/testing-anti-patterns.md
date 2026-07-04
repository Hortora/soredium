# Testing Anti-Patterns

**Load this reference when:** writing or changing tests, adding mocks, or tempted to add test-only methods to production code.

## Overview

Tests must verify real behaviour, not mock behaviour. Mocks are a means to isolate, not the thing being tested.

**Core principle:** Test what the code does, not what the mocks do.

**Following strict TDD prevents these anti-patterns.**

## The Iron Laws

```
1. NEVER test mock behaviour
2. NEVER add test-only methods to production classes
3. NEVER mock without understanding dependencies
```

## Anti-Pattern 1: Testing Mock Behaviour

**The violation:** Asserting that a mock element exists rather than testing
the real component's behaviour.

**Why this is wrong:**
- You're verifying the mock works, not that the component works
- Test passes when mock is present, fails when it's not
- Tells you nothing about real behaviour

**The fix:** Test real component behaviour or don't mock it. If the
component must be mocked for isolation, don't assert on the mock —
test the consumer's behaviour with the dependency present.

### Gate Function

```
BEFORE asserting on any mock element:
  Ask: "Am I testing real behaviour or just mock existence?"

  IF testing mock existence:
    STOP — Delete the assertion or unmock the component

  Test real behaviour instead
```

## Anti-Pattern 2: Test-Only Methods in Production

**The violation:** Adding methods like `destroy()`, `reset()`, or
`getInternalState()` to production classes that are only called by tests.

**Why this is wrong:**
- Production class polluted with test-only code
- Dangerous if accidentally called in production
- Violates YAGNI and separation of concerns
- Confuses object lifecycle with entity lifecycle

**The fix:** Move cleanup and inspection logic to test utilities.
Production classes should only expose methods needed by production code.

### Gate Function

```
BEFORE adding any method to production class:
  Ask: "Is this only used by tests?"

  IF yes:
    STOP — Don't add it
    Put it in test utilities instead

  Ask: "Does this class own this resource's lifecycle?"

  IF no:
    STOP — Wrong class for this method
```

## Anti-Pattern 3: Mocking Without Understanding

**The violation:** Mocking a method "to be safe" without understanding
its side effects that the test depends on.

**Why this is wrong:**
- Mocked method may have side effects the test needs (writing config,
  updating state, publishing events)
- Over-mocking to "be safe" breaks actual behaviour
- Test passes for wrong reason or fails mysteriously

**The fix:** Mock at the right level. Understand what the real method
does before deciding what to mock. Mock the slow/external operation,
not the high-level method the test depends on.

### Gate Function

```
BEFORE mocking any method:
  STOP — Don't mock yet

  1. Ask: "What side effects does the real method have?"
  2. Ask: "Does this test depend on any of those side effects?"
  3. Ask: "Do I fully understand what this test needs?"

  IF depends on side effects:
    Mock at lower level (the actual slow/external operation)
    OR use test doubles that preserve necessary behaviour
    NOT the high-level method the test depends on

  IF unsure what test depends on:
    Run test with real implementation FIRST
    Observe what actually needs to happen
    THEN add minimal mocking at the right level

  Red flags:
    - "I'll mock this to be safe"
    - "This might be slow, better mock it"
    - Mocking without understanding the dependency chain
```

## Anti-Pattern 4: Incomplete Mocks

**The violation:** Creating partial mock data with only the fields
you think the test needs, missing fields that downstream code uses.

**Why this is wrong:**
- Partial mocks hide structural assumptions
- Downstream code may depend on fields you didn't include
- Tests pass but integration fails — mock incomplete, real API complete
- False confidence — test proves nothing about real behaviour

**The Iron Rule:** Mock the COMPLETE data structure as it exists in
reality, not just fields your immediate test uses.

**The fix:** Mirror real API completeness. Check what fields the real
response/object contains and include all of them.

### Gate Function

```
BEFORE creating mock responses:
  Check: "What fields does the real API response contain?"

  Actions:
    1. Examine actual API response from docs/examples
    2. Include ALL fields system might consume downstream
    3. Verify mock matches real response schema completely

  Critical:
    If you're creating a mock, you must understand the ENTIRE structure
    Partial mocks fail silently when code depends on omitted fields

  If uncertain: Include all documented fields
```

## Anti-Pattern 5: Integration Tests as Afterthought

**The violation:** Claiming implementation is complete without tests.

**Why this is wrong:**
- Testing is part of implementation, not optional follow-up
- TDD would have caught this
- Can't claim complete without tests

**The fix:** Follow TDD — test first, implement to pass, then claim
complete.

## When Mocks Become Too Complex

**Warning signs:**
- Mock setup longer than test logic
- Mocking everything to make test pass
- Mocks missing methods real components have
- Test breaks when mock changes

**Consider:** Integration tests with real components are often simpler
than complex mocks. The language-specific dev skills (`java-dev`,
`ts-dev`, `python-dev`) each prescribe when to use real implementations
vs mocks for their ecosystem.

## TDD Prevents These Anti-Patterns

1. **Write test first** → Forces you to think about what you're actually testing
2. **Watch it fail** → Confirms test tests real behaviour, not mocks
3. **Minimal implementation** → No test-only methods creep in
4. **Real dependencies** → You see what the test actually needs before mocking

**If you're testing mock behaviour, you violated TDD** — you added
mocks without watching the test fail against real code first.

## Quick Reference

| Anti-Pattern | Fix |
|--------------|-----|
| Assert on mock elements | Test real component or unmock it |
| Test-only methods in production | Move to test utilities |
| Mock without understanding | Understand dependencies first, mock minimally |
| Incomplete mocks | Mirror real API completely |
| Tests as afterthought | TDD — tests first |
| Over-complex mocks | Consider integration tests |

## Red Flags

- Assertions checking for mock-specific test IDs
- Methods only called in test files
- Mock setup is >50% of test
- Test fails when you remove mock
- Can't explain why mock is needed
- Mocking "just to be safe"

## The Bottom Line

**Mocks are tools to isolate, not things to test.**

If TDD reveals you're testing mock behaviour, you've gone wrong.

Fix: Test real behaviour or question why you're mocking at all.
