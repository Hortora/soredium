# Handler: load_context

Used by both `continue` and `resume` pipelines. The branch exists and mechanical setup is done. Orient the session.

1. Read `META_STATE`, `HAS_HANDOFF`, `HANDOFF_PATH` from the ACTION output
2. If `.plan` exists: read it for queue progress and active issue. Display:
   ```
   ━━━ Queue state ━━━
   Active issue: #N — title
   ━━━━━━━━━━━━━━━━━━━
   ```
3. If handoff exists: read and summarise last session's narrative
4. Run health check if not already done by the pipeline
5. Summarise what the last session accomplished and continue working

After orienting, call the orchestrator with:
```
step_done=load_context
```

Do NOT invoke work-start — the branch and scaffold already exist.
