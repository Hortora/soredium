# Handler: review

Review the work of this session before it is wrapped.

1. Dispatch a fresh reviewer (`requesting-code-review`): a session whose context is
   full reviews badly. Give it the branch and the issue.
2. Ask it to check: gaps, correctness, robustness, consistency, coherence, thread
   safety, orphaned or dead code, readability and maintainability, and that
   everything is wired up and reachable, not just present.
3. Classify each finding into one of three dispositions:
   - **Fix** — small and clearly correct. Fix it now, commit it.
   - **File** — real impact, would prioritise it ahead of something already
     in the queue. Goes to `file_issues` step.
   - **Note** — cosmetic, speculative, or a design question with no clear
     answer yet. Acknowledged in the commit message or spec's Known
     Limitations section. Does NOT become a queue item.
   The test for File vs Note: would you actually work on this before
   something already queued? If no, it's a Note.
4. Report: `step_done=review outcome=completed produced=<findings filed as issues>`
   (`produced` counts only File items, not Notes.)
