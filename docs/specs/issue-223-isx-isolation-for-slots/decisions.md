## D1: Sync mechanism

**Choice:** Use `isx://` git remote protocol (blessed upstream) via `git fetch`/`git merge --ff-only`
**Alternatives:**
- `isx sync` command — convenience wrapper, but local fork extension only (not in blessed upstream)
**Rationale:** Only blessed upstream commands should be used. `isx://` protocol is fully supported via `git-remote-isx` shim + `isx git-remote-helper` subcommand.
**Trade-offs:** Slightly more verbose than `isx sync` — need to add remotes and fetch per-repo
**Exploration:** quick
**Status:** captured

## D2: Template handling

**Choice:** Pick from existing templates — `isx templates list` shows available, user selects
**Alternatives:**
- Auto-create template on first use via `isx project create` — couples slot creation to heavyweight image builds
- Require `--template` flag, error if missing — less ergonomic
**Rationale:** Template creation is heavyweight (builds OS image) and belongs outside the slot workflow. Listing and picking is simple and keeps concerns separate.
**Trade-offs:** User must have a template pre-built before using `--isx`
**Exploration:** quick
**Status:** captured

## D3: Instance naming

**Choice:** Default to branch name, user can override (same pattern as branch naming in work-start Step 5)
**Alternatives:**
- Branch name only (no override) — too rigid
- Slot-prefixed naming like `slot-7-issue-42` — less readable in `isx list`/`isx shell`
**Rationale:** Branch name is already unique and human-readable. `.slot` records the mapping. User override handles edge cases.
**Trade-offs:** None significant
**Exploration:** quick
**Status:** captured

## D4: Remote wiring for slot clones

**Choice:** `slot_manager.py` adds `isx://` remotes to slot clones after `isx branch` creates the instance. No reliance on `isx branch` auto-discovery.
**Alternatives:**
- Let `isx branch` auto-wire originals, copy URLs to slot clones — fragile, depends on host-paths config
**Rationale:** We control exactly which repos are in the slot and where they live in the container. No dependency on ISX auto-discovery finding the right repos.
**Trade-offs:** None — strictly more reliable
**Exploration:** quick
**Status:** captured

## D5: Container-side repo path resolution

**Choice:** Convention-based — assume `/home/agentuser/<repo-name>`. Fail-fast on `git fetch` if wrong.
**Alternatives:**
- Parse template YAML for `path:` values — precise but requires knowing which config file to read
**Rationale:** Convention covers the common case. A failed `git fetch` gives a clear error. Keeps code simple.
**Trade-offs:** Breaks if template uses non-standard paths — user sees a clear fetch error and can adjust
**Exploration:** quick
**Status:** captured

## D6: `work-slot sync` invocation

**Choice:** Support both — `work-slot sync <N>` from anywhere (slot number), and `work-slot sync` from inside a slot clone (auto-detect from CWD)
**Alternatives:**
- Slot number only — consistent with other subcommands but less ergonomic from inside a slot
- CWD-only — breaks the `work-slot <verb> <N>` pattern
**Rationale:** Both invocation styles are natural in different contexts. Auto-detect from CWD uses the same `is_slot_path()` logic already in `slot_manager.py`.
**Trade-offs:** Slightly more code for CWD detection, but the pattern already exists
**Exploration:** quick
**Status:** captured

## D7: Shell offering for ISX slots

**Choice:** Offer both — iTerm tab for the local slot clone (host-side ops: sync, work end) AND `isx shell` for working inside the container
**Alternatives:**
- Replace iTerm with `isx shell` only — user still needs a host terminal for sync and work-end
- iTerm only — user has to manually run `isx shell`
**Rationale:** User needs both environments: container for implementation, host for slot lifecycle ops. Offering both is the complete experience.
**Trade-offs:** Two terminals to manage — but that's inherent to the dual-existence model
**Exploration:** quick
**Status:** captured

## D8: Staleness detection in work-end (from review R1-10)

**Choice:** `work end` checks `.slot` for `isolation: isx`. If present, runs `git ls-remote isx://<instance>/<path>` per repo and compares against local HEAD. If they differ, warns before proceeding. Pre-flight check, not a blocking gate.
**Alternatives:**
- No check — user must remember to sync. Silent data loss if they forget.
- Blocking gate — refuses to proceed without sync. Too rigid; user may intentionally skip ISX commits.
**Rationale:** Dual-existence model introduces a sync-then-close dependency with no enforcement. A lightweight ls-remote comparison catches the common mistake without blocking intentional workflows.
**Trade-offs:** Adds a network round-trip per repo during work-end pre-flight. Negligible cost.
**Exploration:** quick (from review)
**Status:** captured

## D9: Instance name length safety (from review R1-04)

**Choice:** Truncate instance name to fit Incus 63-char limit. Pattern: truncate branch slug, store full mapping in `.slot`. User can still override.
**Alternatives:**
- No truncation — fail at `isx branch` time with an opaque Incus error
- Hash-based naming — `isx-<slot-N>-<hash>` — unreadable in `isx list`
**Rationale:** Branch names can exceed 63 chars (epics with descriptive slugs). Truncation preserves readability while staying within Incus constraints.
**Trade-offs:** Truncated names may lose the tail of the slug — `.slot` preserves the full branch name for lookup
**Exploration:** quick (from review)
**Status:** captured

## D10: ISX availability pre-flight (from review R1-12)

**Choice:** Check `isx` is on PATH before creating the local slot. Fail immediately with a clear message if missing.
**Alternatives:**
- No check — fails mid-creation after local slot scaffolded, leaving an orphaned half-created slot
**Rationale:** Pre-flight avoids cleanup of partially created state. Simple `which isx` check.
**Trade-offs:** None
**Exploration:** quick (from review)
**Status:** captured
