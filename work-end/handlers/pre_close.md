# Pre-close Precondition Handling

Handle preconditions from `work_end_context.py` JSON output.

## Preconditions

| Precondition | Status | Action |
|-------------|--------|--------|
| `branch_alignment` | `fail` | Hard stop — both repos must be on the same branch |
| `clean_tree` | `fail` | See dirty tree protocol below |
| `meta_exists` | `needs_input` (detail: `no-meta`) | Infer issue from branch name, confirm with user |
| `meta_exists` | `needs_input` (detail: `stale-plan`) | Remove stale .plan, proceed without lifecycle |
| `meta_exists` | `pass` | Proceed |

## Dirty Tree Protocol

**ONLY acceptable actions:**

1. `git stash push -u -m "work-end: stashing uncommitted changes"`
2. `git add -A && git commit -m "wip: uncommitted changes before work-end"`

**NEVER use:** `git reset --hard`, `git checkout -- .`, `git clean -fd`

The dirty files may belong to another session. A `git reset --hard`
destroyed hours of work in a real incident.

## Lifecycle Entry

Auto-resolve transient states before entering closing:review:

| `META_STATE` | Action |
|-------------|--------|
| `scaffolded` | Transition `auto_setup` → `active` |
| `transitioning` | Transition `auto_refresh` → `active` |
| `active` | Ready |
| `closing:*` | Offer to continue from that gate |

## Queue Gate

If `HAS_PLAN=yes`, run `plan_manager.py detect`. If mid-queue, redirect
to `work next` instead of closing.

## Main Mode

If `ON_MAIN=yes`, work-end runs in main mode — same ceremony minus
rebase, squash, stamp. Diff against `drained-sha` from `.plan`'s
`## State`.
