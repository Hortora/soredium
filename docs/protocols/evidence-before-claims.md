# Evidence Before Claims

**Core principle:** Run the command. Read the output. THEN claim the result.

No completion claim without fresh verification evidence. If you haven't
run the verification command in this message, you cannot claim it passes.

## The Gate

1. IDENTIFY: What command proves this claim?
2. RUN: Execute the FULL command (fresh, complete)
3. READ: Full output, check exit code, count failures
4. VERIFY: Does output confirm the claim?
5. ONLY THEN: Make the claim

Skip any step = lying, not verifying.

## Applies At

Every completion boundary: commits, PRs, task completion, agent
delegation. This is not optional and not situational.

## Common Failures

| Claim | Requires | Not Sufficient |
|-------|----------|----------------|
| Tests pass | Test command output: 0 failures | Previous run, "should pass" |
| Build succeeds | Build command: exit 0 | Linter passing, logs look good |
| Bug fixed | Test original symptom: passes | Code changed, assumed fixed |
| Agent completed | VCS diff shows changes | Agent reports "success" |
| Requirements met | Line-by-line checklist | Tests passing |

## Red Flags — STOP

- Using "should", "probably", "seems to"
- Expressing satisfaction before verification ("Great!", "Perfect!", "Done!")
- About to commit/push/PR without verification
- Trusting agent success reports
- Relying on partial verification

## Origin

Preserved from the retired `verification-before-completion` skill.
The principle applies at every completion boundary. The work-end
forcing function (Step 2.4) is additive — it handles finding resolution,
not per-boundary evidence.
