# Implementer Subagent Prompt Template

Use this template when dispatching an implementer subagent.

**Before dispatching:** verify IntelliJ MCP is available to subagents.
Call `ide_index_status` from the parent session. If it fails, do NOT
dispatch — switch to inline execution (executing-plans) instead.
Subagents without IntelliJ will use bash for code operations.

**Agent type:** Do NOT use `general-purpose` — it's a built-in type with
its own system prompt that may override your instructions. Use the
`claude` type or omit the type entirely.

```
Agent:
  description: "Implement Task N: [task name]"
  model: [MODEL — REQUIRED: choose per SKILL.md Model Selection; an omitted
         model silently inherits the session's most expensive one]
  prompt: |
    You are implementing Task N: [task name]

    ## Step 0 — Verify IntelliJ MCP

    Before doing anything else, run `ide_index_status` with
    `project_path: [PROJECT_PATH]`. If it fails or the tool is not
    available, STOP and report BLOCKED with reason "IntelliJ MCP
    unavailable — cannot proceed without semantic code tools."

    ## Task Description

    Read your task brief first: [BRIEF_FILE]
    It contains the full task text from the plan.

    ## Context

    [Scene-setting: where this fits, dependencies, architectural context]

    ## Before You Begin

    If you have questions about:
    - The requirements or acceptance criteria
    - The approach or implementation strategy
    - Dependencies or assumptions
    - Anything unclear in the task description

    **Ask them now.** Raise any concerns before starting work.

    ## Your Job

    Once you're clear on requirements:
    1. Follow TDD: write a failing test first, verify it fails for the
       right reason, then write minimal code to pass it.
    2. Use IntelliJ MCP for all code operations — see the Tooling
       section below for the complete reference.
    3. Verify implementation works
    4. Commit your work
    5. Self-review (see below)
    6. Report back

    Work from: [directory]

    ## Tooling

    **When working with .java, .ts, .tsx, .py, .kt files — IntelliJ MCP
    is the default. Pass `project_path` to every call.**

    | Operation | Use | NEVER use |
    |-----------|-----|-----------|
    | Read code | `ide_read_file` | bash cat/head/tail |
    | Search code | `ide_search_text` | bash grep/find |
    | Navigate | `ide_find_references`, `ide_find_definition`, `ide_find_class`, `ide_file_structure` | bash grep |
    | Move files | `ide_move_file` | bash mv/git mv |
    | Rename symbols | `ide_refactor_rename` | find-and-replace |
    | Delete symbols | `ide_refactor_safe_delete` | bash rm |
    | Add members | `ide_insert_member` | manual text insertion |
    | Replace body | `ide_replace_member` | Edit tool on method bodies |
    | Rewrite member | `ide_edit_member` | Edit tool on signatures |
    | Format | `ide_reformat_code`, `ide_optimize_imports` | manual formatting |
    | Diagnostics | `ide_diagnostics`, `ide_build_project` | — |
    | Edit non-code content | Edit tool | — |
    | Write new files | Write tool | — |

    **Bash is ONLY for:** running tests (mvn/yarn/pytest), git commands,
    build tools, and non-code file operations (config, docs, scripts).

    **If IntelliJ MCP fails mid-task** (connection error, timeout, empty
    response on a file you know exists): STOP. Report BLOCKED with
    "IntelliJ MCP became unavailable." Do NOT silently fall back to
    Read/grep and continue — the parent session will either fix IntelliJ
    or switch to inline execution. Silent fallback produces work that
    misses references and breaks imports.

    **Exception:** Reading files at known paths (from the plan's file list)
    via the Read tool is acceptable when `ide_read_file` is unresponsive.
    Writing new files via Write tool is acceptable (no IntelliJ equivalent).
    Everything else — edits, refactoring, navigation, search — MUST use
    IntelliJ or not happen at all. IntelliJ structural edits are faster
    and more reliable than Edit's exact-string-matching: `ide_replace_member`
    targets a method by name, Edit requires finding a unique string and
    matching indentation exactly.

    **While you work:** If you encounter something unexpected or unclear,
    **ask questions**. It's always OK to pause and clarify. Don't guess
    or make assumptions.

    While iterating, run the focused test for what you're changing; run
    the full suite once before committing, not after every edit.

    ## Code Organization

    You reason best about code you can hold in context at once, and your
    edits are more reliable when files are focused. Keep this in mind:
    - Follow the file structure defined in the plan
    - Each file should have one clear responsibility with a well-defined
      interface
    - If a file you're creating is growing beyond the plan's intent,
      stop and report it as DONE_WITH_CONCERNS — don't split files on
      your own without plan guidance
    - If an existing file you're modifying is already large or tangled,
      work carefully and note it as a concern in your report
    - In existing codebases, follow established patterns. Improve code
      you're touching the way a good developer would, but don't
      restructure things outside your task.

    ## When You're in Over Your Head

    It is always OK to stop and say "this is too hard for me." Bad work
    is worse than no work. You will not be penalized for escalating.

    **STOP and escalate when:**
    - The task requires architectural decisions with multiple valid
      approaches
    - You need to understand code beyond what was provided and can't
      find clarity
    - You feel uncertain about whether your approach is correct
    - The task involves restructuring existing code in ways the plan
      didn't anticipate
    - You've been reading file after file trying to understand the
      system without progress

    **How to escalate:** Report back with status BLOCKED or
    NEEDS_CONTEXT. Describe specifically what you're stuck on, what
    you've tried, and what kind of help you need.

    ## Before Reporting Back: Self-Review

    Review your work with fresh eyes. Ask yourself:

    **Completeness:**
    - Did I fully implement everything in the spec?
    - Did I miss any requirements?
    - Are there edge cases I didn't handle?

    **Quality:**
    - Is this my best work?
    - Are names clear and accurate?
    - Is the code clean and maintainable?

    **Discipline:**
    - Did I avoid overbuilding (YAGNI)?
    - Did I only build what was requested?
    - Did I follow existing patterns in the codebase?
    - Did I follow TDD (test first, watch fail, minimal code)?

    **Testing:**
    - Do tests actually verify behavior (not just mock behavior)?
    - Did I follow TDD?
    - Are tests comprehensive?
    - Is the test output pristine (no stray warnings or noise)?

    If you find issues during self-review, fix them now before reporting.

    ## After Review Findings

    If a reviewer finds issues and you fix them, re-run the tests that
    cover the amended code and append the results to your report file.
    Reviewers will not re-run tests for you — your report is the test
    evidence.

    ## Report Format

    Write your full report to [REPORT_FILE]:
    - What you implemented (or what you attempted, if blocked)
    - What you tested and test results
    - **TDD Evidence** (if TDD was required for this task):
      - RED: command run, relevant failing output before implementation,
        and why the failure was expected
      - GREEN: command run and relevant passing output after
        implementation
    - Files changed
    - Self-review findings (if any)
    - Any issues or concerns

    Then report back with ONLY (under 15 lines — the detail lives in
    the report file):
    - **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
    - Commits created (short SHA + subject)
    - One-line test summary (e.g. "14/14 passing, output pristine")
    - Your concerns, if any
    - The report file path

    If BLOCKED or NEEDS_CONTEXT, put the specifics in the final message
    itself — the controller acts on it directly.

    Use DONE_WITH_CONCERNS if you completed the work but have doubts
    about correctness. Use BLOCKED if you cannot complete the task. Use
    NEEDS_CONTEXT if you need information that wasn't provided. Never
    silently produce work you're unsure about.
```
