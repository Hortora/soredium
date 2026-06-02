---
name: smoke-test-mcp-plugin
description: >
  Use when the jetbrains-index-mcp-plugin has been built with buildPlugin, installed
  via ide_install_plugin, and IntelliJ restarted — to verify all MCP tools work
  before committing or raising a PR. Also use when something feels wrong with the
  plugin after a restart and a systematic check is needed.
---

Read `smoke-tests/mcp-protocol.md` from the plugin project, then execute every test
case in order. Report PASS/FAIL per test. If any test fails, diagnose before continuing.

## Setup

Locate the plugin project path. The protocol file is at:
```
<plugin-project>/smoke-tests/mcp-protocol.md
```

Read it fully before starting. The meta-protocol section explains:
- How to call the MCP server via HTTP directly (not via Claude's MCP schema)
- How to confirm IntelliJ actually restarted (restarter.log check)
- How to detect "old code still running" vs a new bug
- Fallback when `ide_restart` doesn't fire

## Execution

Work through every test case in order. For each test:

1. Make the HTTP call as described
2. Check the response against the PASS/FAIL criteria in the protocol
3. Report the result: **PASS** or **FAIL — [reason]**
4. On FAIL: follow the diagnostic hints in the protocol before moving on

Run fork-only tests (section "Fork-only tests") when working in the fork.
Skip them when verifying an upstream build.

## After all tests

Write a summary table: tool | result | notes.

Flag any FAIL that indicates a regression (test was passing before this build).
Flag any FAIL that indicates a new protocol gap (the protocol didn't anticipate this failure mode).

## Common pitfalls

| Pitfall | What happens | Fix |
|---------|-------------|-----|
| Skipping companion skill reinstall | AI uses wrong IntelliJ MCP (`mcp__intellij__*` instead of `mcp__intellij-index__*`) | After every restart: click "Get Companion Skill" in the tool window or copy skill files manually |
| Using Claude's MCP schema | Stale tool list from session start, missing new tools | Call via curl directly |
| Not checking restarter.log | `ide_restart` appears to work but old code still runs | Always verify log entry |
| Testing before indexing completes | `ide_index_status` returns `isDumbMode: true`, tool calls fail | Wait for `isDumbMode: false` |
| Wrong project_path | Multi-project error fires before tool validation | Pass the plugin project path on every call |
