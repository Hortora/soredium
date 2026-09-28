# Handler: present_candidates

The find pipeline has queried for recommended work. Present results.

1. Read recommendation data from the ACTION output (keys from enrichment.py what-next)
2. Present candidates with scores:
   ```
   Recommended next:
     1. #42 — Fix caching bug (score: 12)
     2. #55 — Refactor auth (score: 8)
   Pick a number, type an issue #, or describe what you want to work on.
   ```
3. Also check HANDOFF.md What's Next section if available
4. When user picks items, call the orchestrator with:
   ```
   step_done=present_candidates selected_issues=42:Fix caching bug,55:Refactor auth
   ```
5. If no items selected:
   ```
   step_done=present_candidates selected_issues=
   ```
