# Slot .gitignore Baseline — Design Spec

**Issue:** Hortora/soredium#247
**Date:** 2026-08-18
**Branch:** issue-247-slot-gitignore-baseline

## Problem

When `work-slot` creates a slot, `setup_maven_config()` writes `.mvn/slot-settings.xml`
and `.mvn/maven.config` into each cloned repo and appends them to `.gitignore`. These
`.gitignore` modifications are never committed — they get swept into squash commits during
`work-end`, where code review flags them as unexplained out-of-scope changes.

Additionally, `.worktrees/` and `.claude/` are common infrastructure directories that
some repos have in `.gitignore` and some don't. Slots should ensure a baseline set of
patterns exists in every repo.

Found during slot 110 close (casehubio/parent#405).

## Design

### Rename and expand: `setup_maven_config()` → `setup_slot_repo()`

Rename the existing function to reflect its broader scope. It handles all per-repo
infrastructure setup during slot creation:

1. Maven config (existing logic — `.mvn/maven.config`, `.mvn/slot-settings.xml`, slot settings)
2. Gitignore baseline (new — ensure infrastructure patterns exist in `.gitignore`)

The function modifies files only — it does **not** commit. This follows the codebase
precedent where every setup function in `slot_manager.py` modifies files without
committing (`_exclude_symlinks`, `_symlink_gitignored_assets`, `configure_slot_remotes`,
`_unignore_subdir`, `replicate_claude_md`).

The gitignore logic currently embedded in `setup_maven_config()` (lines 395-403) moves
into the expanded baseline check, which adds the full pattern set.

### Pattern matching: line-by-line, not substring

The existing code uses `if e not in content` — a whole-file substring check. This is
broken for the new patterns: `.claude` is a substring of `.claude/`, so if only `.claude/`
exists, the substring check falsely reports `.claude` as present and skips it.

The new implementation must use **line-by-line matching**: read `.gitignore` into lines,
strip whitespace from each line, and check for exact equality against each baseline
pattern. This correctly handles:
- `.claude/` present but `.claude` absent → adds `.claude`
- `.claude` present but `.claude/` absent → adds `.claude/`
- Comments containing pattern text (e.g., `# .claude/ is generated`) → not a false match

### Baseline patterns

```
.mvn/maven.config
.mvn/slot-settings.xml
.worktrees
.worktrees/
.claude
.claude/
```

Both bare and trailing-slash forms are needed for `.worktrees` and `.claude` because
git treats symlinks as regular files — a pattern with a trailing slash (`name/`) matches
directories only and silently skips symlinks (GE-20260809-96d41c).

The `.mvn/` patterns don't need bare forms because `.mvn/maven.config` and
`.mvn/slot-settings.xml` are files, not directories or symlinks.

### Caller commits

The caller (`create_slot` / `add_repo`) commits `.gitignore` after calling
`setup_slot_repo()` — only if the gitignore was actually modified.

`setup_slot_repo()` returns a result indicating whether `.gitignore` was changed.
The caller uses this to decide whether to commit:

```python
changed = setup_slot_repo(clone_dest, m2_dir)
if changed:
    run_cmd(["git", "-C", str(clone_dest), "add", ".gitignore"])
    run_cmd(["git", "-C", str(clone_dest), "commit", "-m",
             "chore: add slot infrastructure to .gitignore"])
```

### Commit message

```
chore: add slot infrastructure to .gitignore
```

This message is recognizable by both human reviewers and the squash analysis as
infrastructure setup. The `chore:` prefix is classified as SQUASH by git-squash
squash-policy (row 6), so it will be folded into the first work commit during
the work-end squash pass. (The pre-push hook uses a narrower regex and won't
match this specific message — that's fine, the squash happens at work-end.)

### Idempotency

The gitignore logic is idempotent:
- If all patterns already exist in `.gitignore`, no changes are made and the caller
  skips the commit
- If some patterns exist, only missing ones are appended
- Running twice produces the same result as running once

### Edge cases

- **No `.gitignore` file**: Create one with all baseline patterns
- **`.gitignore` exists with some patterns**: Append only missing ones
- **`.gitignore` has patterns in different forms** (e.g., `.claude/` exists but `.claude`
  doesn't): Each pattern is checked independently — the bare form is added even if the
  slash form exists, and vice versa
- **Non-git directory**: Should not happen (called after `git clone`), but if it does,
  the caller's `git commit` will fail harmlessly

## Tests

Per protocol `externalised-scripts-require-tests`, tests must be committed with the
script changes. Test class: `TestSetupSlotRepo` in `tests/test_slot_manager.py`
(renamed from `TestSetupMavenConfig`).

Required coverage:

1. **Happy path — gitignore**: No `.gitignore` — creates file with all baseline patterns,
   returns changed=True
2. **Partial existing**: Some patterns present — appends missing, returns changed=True
3. **All present**: All patterns exist — no changes, returns changed=False
4. **Idempotent**: Calling twice produces same result
5. **Preserves existing content**: Other `.gitignore` entries are not removed or reordered
6. **Both symlink forms**: Verifies both `.claude` and `.claude/` are added independently
7. **Maven config unchanged**: Existing Maven config tests continue to pass (function
   rename only — Maven logic is unchanged)

## Scope

**In scope:**
- Rename `setup_maven_config()` → `setup_slot_repo()`
- Expand with gitignore baseline logic (check + append missing patterns)
- Return value indicating whether `.gitignore` was modified
- Caller-level commit in `create_slot` and `add_repo`
- Tests for gitignore baseline behaviour
- Update existing tests for the rename

**Out of scope:**
- Mechanical pre-push hook scope checking (no such check exists in soredium)
- Retroactive fix of existing slots (they work fine, just have noisy diffs)
- Changes to the squash or code-review skills
- Workspace clone gitignore (workspace clones don't call `setup_maven_config` today
  and don't need Maven patterns)

## References

- [slot_manager.py:361-403] — current `setup_maven_config` with embedded gitignore logic
- [slot_manager.py:536-582] — `create_slot` flow
- [slot_manager.py:699-736] — `add_repo` flow
- [GE-20260809-96d41c] — .gitignore trailing-slash patterns silently skip symlinks
- [GE-20260805-ffef3b] — Maven .mvn/maven.config parser quirk (already handled)
- [externalised-scripts-require-tests] — protocol: scripts ship with tests
- [casehubio/parent#405] — epic where the problem was discovered (slot 110)
- [decision review R1-03] — rename alternative (stronger than extraction)
- [decision review R1-07, R1-10] — caller-level commit follows codebase precedent
- [spec review R1-01] — line-by-line matching required (substring check is broken for bare/slash pairs)
- [spec review R1-02] — squash-policy row 6 is the correct mechanism, not pre-push hook regex
