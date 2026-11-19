# Handler: review

Review the work of this session before it is wrapped.

1. Dispatch a fresh reviewer (`requesting-code-review`): a session whose context is
   full reviews badly. Give it the branch and the issue.
2. Ask it to check: gaps, correctness, robustness, consistency, coherence, thread
   safety, orphaned or dead code, readability and maintainability, and that
   everything is wired up and reachable, not just present.
3. Fix what is small and clearly correct, and commit it. Everything else is a
   finding for the `file_issues` step: keep the list.
4. Report: `step_done=review outcome=completed produced=<findings left for issues>`
