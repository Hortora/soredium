# Handler: sweep_config

Present the pre-close checklist with all items ON:

```
Pre-close sweep — create before closing?

[x] 1  Knowledge capture   (forage then protocol — sequential)
[x] 2  ADR                 record architectural decisions
[x] 3  Doc sync            (update-claude-md then implementation-doc-sync)
[x] 4  write-content       capture branch narrative as diary entry

Type numbers to toggle, "all" to toggle all, or "go" to proceed:
```

<NEVER-RECOMMEND-SKIPPING>
Present all items ON. Do not recommend skipping. The user decides.
"Go" means proceed with current selections — all ON by default.
Session-bound items (1, 4) cannot be deferred.
</NEVER-RECOMMEND-SKIPPING>

Report selected items back to orchestrator via sweep_selected= argument:
```
python3 work-end/work_end_orchestrator.py ... sweep_selected=forage,protocol,update_claude_md,impl_doc_sync,adr,write_content
```

**Journal validation:** If JOURNAL_DRIFT or UNANCHORED_ENTRIES in
orchestrator output, present decisions interactively before proceeding.
