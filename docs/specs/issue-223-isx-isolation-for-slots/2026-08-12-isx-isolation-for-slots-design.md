# ISX Isolation for Slots — Design Spec

**Issue:** Hortora/soredium#223
**Branch:** issue-223-isx-isolation-for-slots
**Date:** 2026-08-12

## Overview

ISX isolation adds an optional container layer on top of the existing slot
infrastructure. A slot with `--isx` has **dual existence**: an ISX container
for working (implementation, testing, builds) and lightweight local clones
for landing (sync, push, close).

```
work-slot create #42 --isx
  ├── Local slot (existing)        ← landing zone
  │   ├── slots/<N>/<repo>/        ← git clone --shared
  │   ├── .slot                    ← metadata (+ isolation section)
  │   └── .plan                    ← issue queue
  └── ISX container                ← working environment
      └── /home/agentuser/<repo>/  ← template-provisioned repos
```

### Lifecycle

1. `work-slot create --isx` — creates local slot + ISX instance, wires `isx://` remotes
2. User works inside ISX (`isx shell`) — implements, tests, commits
3. `work-slot sync` — fetches committed work from ISX into local clones
4. `work end` — runs on local clones (staleness pre-flight check first), existing close machinery
5. `work-slot remove` — `isx destroy` + archive local slot

No changes to `work-end` internals — it operates on local clones after sync,
same as today. The only `work-end` addition is the staleness pre-flight.

### ISX commands used (all blessed upstream)

| Command | Purpose |
|---------|---------|
| `isx templates list` | Enumerate available templates for selection |
| `isx branch <name> --from <template>` | Create container instance |
| `isx shell <name>` | Open shell in container |
| `isx destroy <name>` | Destroy container on slot removal |
| `git-remote-isx` + `isx git-remote-helper` | Transport for `isx://` git remotes |

`isx sync` is a local fork extension (not upstream) and is NOT used.

---

## `slot_manager.py` Changes

### 1. `create-slot` with `--isx`

When `isx=yes` is passed to `create_slot()`:

1. **Pre-flight (before any directory creation):** Check `isx` is on PATH.
   Abort immediately if missing — no orphaned half-created slot. This check
   runs at the top of `create_slot()`, before `slot_dir.mkdir()`.
2. Normal slot creation proceeds (local clones, `.m2`, symlinks).
3. **Template selection:** Run `isx templates list`, present choices, user picks.
4. **Instance naming:** Default to branch name, truncated to 63 chars if
   needed (Incus limit). User can override. Store in `.slot`.
5. **Create instance:** `isx branch <instance-name> --from <template>`
6. **Wire remotes:** For each repo in the slot:
   `git -C <slot-clone> remote add isx isx://<instance>/home/agentuser/<repo-name>`
7. **Write isolation metadata to `.slot`** via `write_slot_md()` (see
   Parser/Writer Changes below).

New CLI args for `create-slot`: `isx=yes template=<name> instance=<name>`

### 2. `sync-isx` subcommand

New subcommand. Invocable two ways:
- `work-slot sync <N>` — from anywhere, by slot number
- `work-slot sync` — from inside a slot clone (auto-detect via CWD)

For each project repo in the slot:
1. `git -C <local-clone> fetch isx <branch>`
2. `git -C <local-clone> merge --ff-only isx/<branch>`

**Error paths:**
- Non-ISX slot (no `type: isx` in `.slot`) → error: "This slot has no ISX isolation."
- Instance not running → error from `git fetch` (ISX protocol reports it)
- `--ff-only` fails (diverged histories) → report which repo and stop
- No `isx` remote on a repo → skip with warning

Convention-based path resolution: container repos assumed at
`/home/agentuser/<repo-name>`. If wrong, `git fetch` fails with a clear
error pointing to the path.

### 3. `add-repo` ISX remote wiring

In existing `add_repo()`, after cloning the new repo into the slot:

1. Read `.slot` for `type: isx` and `instance:` name
2. If present, wire the `isx://` remote for the new repo:
   `git -C <new-clone> remote add isx isx://<instance>/home/agentuser/<repo-name>`

This ensures repos added after ISX creation are sync-capable without
manual intervention.

### 4. `remove-slot` / `archive-slot` ISX cleanup

In existing `remove_slot()` and `archive_slot()`, before archiving:

1. Read `.slot` for `type: isx` and `instance:` name
2. If present, run `isx destroy <instance-name>`
3. Warn and continue if destroy fails (instance may already be gone)

Extract into a `_teardown_isx(slot_dir)` helper called from both functions.

### 5. Staleness pre-flight for `work-end`

Embedded in `work_end_context.py` (extends existing precondition output).
When `.slot` has `type: isx`:

For each repo:
1. `git ls-remote isx://<instance>/home/agentuser/<repo-name>` — get remote HEAD
2. Compare against local clone HEAD
3. Output `ISX_STALE=yes` or `ISX_STALE=no` with per-repo delta

work-end's existing precondition handling surfaces the warning. The LLM
asks to continue or sync first. Non-blocking — user can proceed.

No changes to `work-end/SKILL.md` — the staleness signal flows through
the same precondition mechanism as `clean_tree` and `meta_exists`.

### 6. `list-slots` isolation column

`list_slots()` return dict gains `isolation` field (`isx` or `none`).
Output format: `SLOT=<N> BRANCH=<branch> REPOS=<repos> STATE=<state> ISOLATION=<type>`

---

## `.slot` Metadata

Existing `.slot` format gains a new optional section:

```markdown
# Slot 7 — issue-42-fix-scoring

## Issue
Hortora/soredium#42
Covers: 42

## What to do
Fix the scoring engine regression

## Repos
- soredium (primary)

## Isolation
type: isx
instance: issue-42-fix-scoring
template: tpl-java

## Created
2026-08-12, branch: issue-42-fix-scoring
```

The `## Isolation` section is only present for ISX slots. All ISX-aware
code paths check for its presence before acting.

### Parser/Writer Changes

**`parse_slot_md()`** — extend the state-machine parser to handle
`## Isolation`. Returns three new fields:
- `isolation_type` — `"isx"` or `""` (empty if no isolation section)
- `isx_instance` — instance name string
- `isx_template` — template name string

**`write_slot_md()`** — accept optional `isolation_type`, `isx_instance`,
`isx_template` parameters. When `isolation_type` is non-empty, write the
`## Isolation` section after `## Repos`.

---

## SKILL.md Changes

### `work-slot/SKILL.md`

**Step 1 (Gather input)** — add to input list:
- `--isx` — create with ISX container isolation
- If `--isx`: show `isx templates list` output, user picks template.
  Optional instance name override (defaults to branch name, truncated to 63 chars).

**Step 4 (Create the slot)** — `create-slot` with `isx=yes` handles
pre-flight, instance creation, and remote wiring internally. The SKILL
passes `isx=yes template=<name> instance=<name>` to the script.

**Step 8 (Shell offering)** — for ISX slots, offer both:
1. iTerm tab for host-side ops (sync, work-end)
2. `isx shell <instance>` for container work

**New section: `work-slot sync`** — document the subcommand with both
invocation patterns.

**Existing section: `work-slot remove`** — add note that ISX instances
are destroyed before archiving.

### No changes to `work-end/SKILL.md`

Staleness check flows through `work_end_context.py` precondition output.

### `work-start/SKILL.md` — resume path ISX shell offering

On resume, if `.slot` has `type: isx`, offer `isx shell <instance>` in
the resume summary (same offering as creation Step 8). The user needs
the container shell in every session, not just the first one.

---

## Testing

Per `externalised-scripts-require-tests` protocol:

| Function | Tests |
|----------|-------|
| ISX extension of `create_slot` | Happy path, missing `isx` binary, invalid template, instance name truncation (63 char limit) |
| `sync_isx()` | Happy path (ff-only succeeds), non-ISX slot error, diverged histories error, missing remote skip |
| ISX cleanup in remove/archive | Instance exists, instance already gone, no ISX metadata in `.slot` |
| ISX wiring in `add_repo()` | ISX slot gets remote, non-ISX slot unchanged |
| `parse_slot_md()` isolation parsing | With and without `## Isolation` section |
| `list_slots()` isolation field | ISX slot shows `isx`, non-ISX shows `none` |
| Staleness pre-flight | Heads match (no warning), heads differ (warning), instance unreachable |

Tests mock `subprocess.run` calls to `isx` and `git` — no actual containers
in unit tests.

---

## Scope Boundaries

### In scope

- `--isx` flag on `create-slot` with template selection and instance creation
- `sync-isx` subcommand (slot number and CWD auto-detect)
- ISX remote wiring in `add-repo` for ISX slots
- ISX destroy on `remove-slot` / `archive-slot`
- `.slot` isolation metadata (`## Isolation` section) with parser/writer extensions
- `list-slots` isolation column
- Staleness pre-flight in `work_end_context.py`
- ISX shell offering on work-start resume path
- Instance name truncation to 63 chars
- ISX availability pre-flight
- SKILL.md updates for work-slot
- Unit tests for all new code paths

### Not in scope

- Running `work end` inside ISX — always host-side after sync
- Running sweeps inside ISX — need LLM session on host
- Multi-container slots — one ISX instance per slot
- Casehub integration — soredium/hortora first
- Template auto-creation — user creates templates separately via `isx project create`
- `isx sync` command — local fork extension, not blessed upstream
