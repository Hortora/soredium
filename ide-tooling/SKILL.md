---
name: ide-tooling
description: >
  Use when mcp__intellij-index__* tools are visible — for ALL code navigation, editing,
  refactoring, and diagnostics. Also invoke for any IDE operation: rename, move, edit member,
  find references, type hierarchy, diagnostics. Never fall back to bash grep or text tools
  for semantic code operations.
---

# IDE Tooling — IntelliJ MCP Guide

## Two MCPs, one routing rule

Two IntelliJ MCP servers may be present. They are NOT interchangeable:

| Server | Use for | Key difference |
|--------|---------|----------------|
| `mcp__intellij-index__*` | Navigation, editing, refactoring, diagnostics, project management | Auto-opens projects via `project_path` |
| `mcp__intellij__*` | Build, run, terminal, formatting | Cannot open projects — only sees already-open windows |

**Always use `mcp__intellij-index__*` for code operations.** Never ask
the user to open a project. Pass `project_path` and the plugin opens
it automatically.

---

## Navigate — understand code before changing it

Use these to explore structure, trace dependencies, and understand
impact before making changes.

| Tool | What it does | When to use |
|------|-------------|-------------|
| `ide_find_references` | All usages of a symbol across the project | **Before any rename, delete, or signature change** — understand full impact |
| `ide_find_definition` | Navigate to where a symbol is declared | Jump to source of a class, method, or variable |
| `ide_find_implementations` | All concrete implementations of an interface or abstract method | Understanding polymorphism, finding all providers |
| `ide_find_super_methods` | Parent methods that a method overrides | Tracing inheritance chain upward |
| `ide_type_hierarchy` | Full inheritance tree (supertypes and subtypes) | Understanding class relationships |
| `ide_call_hierarchy` | Who calls this method / what this method calls | Tracing execution flow, debugging, impact analysis |
| `ide_find_class` | Find a class by name (camelCase, substring, wildcard) | Faster than grep for known class names |
| `ide_find_file` | Find a file by name | Quick file lookup by pattern |
| `ide_find_symbol` | Find any symbol (class, method, field, function) by name | When you know the symbol name but not its location |
| `ide_search_text` | Word index or regex search across project | Fast identifier search, context filtering (code/comments/strings) |
| `ide_file_structure` | Hierarchical structure of a source file (classes, methods, fields) | Understanding file layout. Returns `line` and `endLine` per member — use with `ide_read_file(startLine, endLine)` to read exactly one member |

## Read — examine specific code

| Tool | What it does | When to use |
|------|-------------|-------------|
| `ide_read_file` | Read file content by path or qualified name, with optional line range | Reading specific methods (use `startLine`/`endLine` from `ide_file_structure`). Also reads library/dependency sources from jars |
| `ide_get_active_file` | Currently open file(s) in the editor | Checking what the user is looking at |
| `ide_open_file` | Open a file in the editor, optionally at a specific line | Directing the user's attention to relevant code |

## Edit — structural code changes

Semantic editing that works with methods, fields, and properties —
not line numbers and string matching. Auto-reformats by default.

| Tool | What it does | When to use |
|------|-------------|-------------|
| `ide_edit_member` | Replace entire member declaration (signature + body) | Changing a method's API and implementation together |
| `ide_replace_member` | Replace only the body — signature preserved | Fixing or rewriting implementation without changing the API |
| `ide_insert_member` | Insert new member at a structural position (before/after/first/last) | Adding new methods, fields, or properties |

**Parameters common to all three:** `file` (required), `class` (optional —
omit for top-level Kotlin), `member` (for edit/replace), `content`
(required), `reformat` (default: true), `project_path` (when multiple
projects open).

**Disambiguation:** When a class has overloaded methods, use
`parameterCount` or `line` to target the right one. Ambiguous calls
return a candidate list with signatures, parameter counts, and line
numbers for retry.

**ide_replace_member content format:** Provide the new body WITHOUT
braces for methods (just the statements), or a new initializer
expression for fields.

**Error handling:**
- `ambiguous_member` — retry with `parameterCount` or `line`
- `member_not_found` — check spelling and class name
- `no_body` (abstract method) — use `ide_edit_member` instead

## Refactor — cross-cutting changes that update references

| Tool | What it does | When to use |
|------|-------------|-------------|
| `ide_refactor_rename` | Rename symbol + update all references | **Never use Edit/sed for renames** — IntelliJ updates all callers |
| `ide_move_file` | Move file + update package/imports | **Never use bash mv for source files** |
| `ide_refactor_safe_delete` | Delete symbol, checking for usages first | Lists blocking usages if deletion would break things |
| `ide_optimize_imports` | Remove unused imports, organise remaining | After adding new code or moving classes |
| `ide_reformat_code` | Apply project code style formatting | After manual text edits or when formatting drifts |
| `ide_convert_java_to_kotlin` | Convert Java files to Kotlin | Migration projects |

## Verify — check correctness after changes

| Tool | What it does | When to use |
|------|-------------|-------------|
| `ide_diagnostics` | Errors, warnings, quick-fix intentions for a file. Also build errors and test results | After editing — check for compilation errors, unused imports, type mismatches |
| `ide_build_project` | Compile the project | After code changes — verify everything compiles |
| `ide_index_status` | Check if IDE is ready for semantic operations | Before batch operations — indexing may still be in progress |
| `ide_sync_files` | Sync IDE's virtual file system with external changes | After files created/modified outside the IDE (e.g., by agents) |
| `ide_reload_project` | Re-resolve dependencies (Maven/Gradle reload) | After modifying pom.xml, build.gradle, or dependency config |

## Project — manage what's open and active

| Tool | What it does | When to use |
|------|-------------|-------------|
| `ide_open_project` | Open a project and wait for indexing | When you need a project that isn't open yet |
| `ide_open_workspace` | Open multiple Maven projects as one workspace | Cross-project refactoring across sibling repos |
| `ide_import_modules` | Import external project directories as modules | Adding cross-project code intelligence |
| `ide_close_project` | Close a project to free memory | When done with a project |
| `ide_project_status` | All open/managed projects and their states | **Use this, not `get_project_modules`** |
| `ide_set_project_mode` | Set lifecycle mode (active/background/dormant/closed) | Managing memory across projects |
| `ide_set_all_project_modes` | Set mode for all managed projects at once | Batch lifecycle management |
| `ide_get_project_modes` | Current mode of all managed projects | Checking what's active |
| `ide_enroll_all_projects` | Enroll open projects in lifecycle management | First-time setup |
| `ide_release_project` | Release from lifecycle management | Returning control to the user |
| `ide_release_all_projects` | Release all managed projects | Session cleanup |
| `ide_lifecycle_log` | Recent lifecycle events | Diagnosing why a project closed or changed state |
| `ide_set_lifecycle_log_file` | Enable/disable writing lifecycle events to disk | Post-mortem analysis |
| `ide_set_power_save_mode` | Toggle Power Save Mode (IDE-wide) | Reduce CPU when not actively editing |
| `ide_install_plugin` | Install a plugin into the IDE | Plugin management |
| `ide_restart` | Restart the IDE | After plugin install (MCP connection drops) |

---

## Editing preference hierarchy

When authoring code, prefer tools in this order:

1. **Structural edits** (`ide_edit_member`, `ide_replace_member`,
   `ide_insert_member`) — for class members. Semantically aware,
   auto-reformats, handles overloads.
2. **Semantic refactoring** (`ide_refactor_rename`, `ide_move_file`,
   `ide_refactor_safe_delete`) — for cross-cutting reference updates.
3. **Text edits** (Edit tool) — for non-structural changes: config
   files, markdown, non-class code, file-level changes outside any
   class body.

**When IntelliJ MCP is unavailable:** For non-structural text edits
(config, markdown, non-class code), use Edit/Write directly — no MCP
needed. For semantic operations (rename, move, find-references), check
`ide_index_status` first — the project may still be indexing. If no
MCP server is available for a semantic operation, stop and inform the
user rather than silently falling back.

---

## Multi-repo workspaces

If a project named `ide-workspace-*` is already open (visible in
`ide_project_status`), use its path as `project_path` — it provides
cross-project code intelligence across all modules.

If no workspace is open and you need cross-project refactoring, call
`ide_open_workspace` with the common parent directory.

## Lifecycle-managed projects

Projects may be sleeping to free memory. **Never ask the user to open
a project.**

1. **Always include `project_path` and proceed silently** — it
   auto-opens any project with a `.idea` directory. Do not warn the
   user. Do not ask them to open it. Just pass `project_path`.
2. **Use `ide_project_status` to see all open projects** — not
   `get_project_modules`.
3. **If you get `no_project_open`** — retry with a `project_path`
   from the error's `managed_closed_projects` list.

---

## `mcp__intellij__*` — built-in server (limited scope)

Use only for operations `intellij-index` cannot do. **Cannot auto-open
projects** — if a project isn't open, these tools fail silently.

| Tool | When |
|------|------|
| `build_project` | Build/compile |
| `execute_run_configuration` | Run named test or app configuration |
| `execute_terminal_command` | Shell command in IDE terminal |
| `get_project_dependencies` | Library dependency list |
| `list_directory_tree` | Browse directory tree |

Prefer `intellij-index` equivalents where they exist:
- `get_file_problems` → use `ide_diagnostics`
- `get_project_modules` → use `ide_project_status`
- `find_files_by_name_keyword` → use `ide_find_file`
- `replace_text_in_file` → use `ide_edit_member` / `ide_replace_member`

---

## Skill Chaining

**Used as prerequisite by:** `java-dev`, `python-dev`, `ts-dev`,
`test-driven-development`, `systematic-debugging`,
`subagent-driven-development`, `executing-plans`,
`dispatching-parallel-agents`, `brainstorming`

**Complements:**
- `verification-before-completion` — `ide_build_project` and `ide_diagnostics`
  are verification tools used as part of the VBC gate function
- `writing-plans` — IDE navigation tools inform file structure analysis
  during plan creation
