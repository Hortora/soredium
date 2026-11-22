# Work Lifecycle: Maintainer Guide

**Update this file in the same change that makes any part of it untrue, and add what you learn** (a new rule, a failure and its lesson, an area to watch). You are expected to edit it; a lifecycle change without the matching update here is not finished.

For a session that has to maintain or improve soredium's work lifecycle (start, wrap, end, landing, publishing, queues, slots, clones, the worklog) and was not there when it was built.

Written 2026-11-20 against `main` at `14aa10d`; revised after an independent review the same day. Step lists, decision names and file roles were printed from the code, not recalled. Where something is believed but was not checked, it says so. `CLAUDE.md` states the conventions; this guide adds how they work and why. Where the two overlap, `CLAUDE.md` is the reference and this file points to it.

Read sections 1 to 4 before changing anything. Use the rest as reference.

---

## 1. Ten rules that are not negotiable

Each of these exists because breaking it lost or nearly lost real work.

1. **Canonical repos are the sync point and are never edited by hand.** The repos directly under `~/claude/<family>/` are canonical. Never stash, reset, check out, or abort a rebase or merge in one. Another session may be mid-operation there.
2. **Only canonical publishes.** A slot or clone has one remote, `local`, pointing at its canonical repo. Nothing pushes from a slot, a clone or a working branch. Publishing is `project/canonical_sync.py publish <repo>`.
3. **Linear history.** No merge commits on a base branch. Landing is rebase then fast-forward.
4. **No squashing outside the `git-squash` skill.** The ceremony lands a multi-commit branch only when `refs/squash-reviewed/<branch>` equals the branch tip.
5. **A read never writes.** Reading the queue, detecting state and resolving context change no file. See `docs/protocols/a-read-never-writes.md`.
6. **One queue per area of work, never synced.** `queue_io.queue_dir()` is the only place that decides where a queue is. See section 5.
7. **Nothing is deleted.** Not branches (ask the user, always), not attic slots, not `refs/rescue/*`, not files a clone inherited. Tools keep backups under dated names.
8. **A failed step stops; it is never skipped.** A failed commit, land or publish is reported as a failure. Never report success because the next step happened to run.
9. **Issue references are `owner/repo#N` everywhere**, including commit messages written by hand.
10. **Claims are observed, not assumed.** Run it, read the output, then say it. If a claim is about git behaviour, reproduce it in a scratch repo first.

If a change you are about to make conflicts with one of these, stop and ask the user. Do not reason your way around it.

---

## 2. Vocabulary

| Term | Meaning |
|---|---|
| Family | A directory of related repos: `~/claude/hortora/`, `~/claude/casehub/` |
| Canonical repo | `~/claude/<family>/<repo>`. The one copy that talks to GitHub |
| Project repo | The code repo (for example `soredium`) |
| Workspace repo | A companion repo holding methodology artifacts: handoff, blog drafts, specs, plans. For soredium it is `soredium` (`~/claude/public/soredium`) |
| Base branch | `main` (occasionally `master`) |
| Slot | `~/claude/<family>/slots/<N>/`: clones of several project and workspace repos cut for one piece of work, with a `.slot` file at the root. Archived to `slots/attic/<N>/` when done |
| Permanent clone | `~/claude/<family>/clone/<repo>/`: one project clone and its workspace clone, with `.slot` and `.permanent`. Never archived |
| Area of work | One slot, one clone, or one canonical workspace. The unit that owns a queue |
| Queue | The list of issues for an area and its state (`.queue`; older name `.plan`) |
| Landing | Getting a branch's commits onto canonical's base branch, on disk, no network |
| Publishing | Pushing canonical's base branch to GitHub |
| Promotion | Copying finished artifacts (blog entries, specs, ADRs) from the workspace repo into the project repo's `docs/` |
| Stamp | An empty commit on a closed branch: `chore: branch closed — landed as <SHA> on <base>` |
| Ceremony | `work-end/close.py`: the code that lands, stamps and advances the queue |

A family opts in to permanent clones with the marker `~/claude/<family>/.clone-enabled`. Today only `hortora` has it, and only `soredium` has a clone. In casehub people still work in canonical repos and numbered slots.

---

## 3. How to work on this codebase

### 3.1 Where

Work on soredium happens in the permanent clone, not in canonical:

```
~/claude/hortora/clone/soredium/
    .slot  .permanent  .queue  .queue-root
    soredium/          project clone   (remote: local)
    wsp-soredium/      workspace clone (remote: local)
```

Open the session in `wsp-soredium/`. Running `work` in canonical soredium stops with `STOP_REASON=canonical_repo_of_clone_family` and tells you where to go.

### 3.2 The loop for one item

```
cd ~/claude/hortora/clone/soredium/wsp-soredium
python3 ~/.claude/skills/project/work.py start issue_n=<N> "issue_title=<title>"
python3 ~/.claude/skills/project/work.py start step_done=<step> outcome=completed|skipped [key=value]
# ... edit in ../soredium, test, commit there ...
python3 ~/.claude/skills/project/work.py end          # or: wrap
```

Each call prints `ACTION=<step>`. A judgment step names a handler file under `work/handlers/`; read it, do what it says, then report with `step_done=<step> outcome=completed|skipped`. Mechanical steps run by themselves.

- **Start the item before editing.** Edits made first land on the clone's `main` and get carried as strays.
- **Never start work on an issue the queue shows as closed.** `start` answers `DECISION=named_issue_already_closed`. File a follow-up issue and start that.
- **Commit after every change that passes its tests.** Commit messages need an issue reference: `Refs Hortora/soredium#N`.
- **Check the result of a test run before committing.** A pipe to `tail` hides the exit status; read the summary line.

### 3.3 After landing

```
cd ~/claude/hortora/soredium
python3 scripts/claude-skill sync-local --all -y          # install into ~/.claude/skills
python3 project/canonical_sync.py publish <repo>          # only with the user's go-ahead
```

`work end` publishes the repos in its `SCOPE=` line; typing it is the go-ahead for exactly those. Anything else needs the user to say so each time.

Sessions that loaded a skill before an install keep the old text until they reload it. The Python scripts they call are the new ones immediately.

### 3.4 Running tests

- `python3 -m pytest tests/<file> -q -n 8` . Use `-n 8` (pytest-xdist) always; suites build real git repos.
- In a **canonical** repo add `-p no:cacheprovider` so the run leaves no files behind.
- The full suite is about 5,200 tests and takes about 40 minutes. Run it in the background and wait for the notification. Do not poll.
- Fast, high-value subsets:
  - queues: `tests/test_queue_io.py tests/test_queue_home.py tests/test_notes_store.py tests/test_queue_notes_integration.py tests/test_ctx_reads_only.py`
  - wrap and end: `tests/test_work_wrap_end.py tests/test_wrap_scope.py` (several minutes)
  - ceremony: `tests/test_close.py tests/test_close_batch.py tests/test_close_integration.py tests/test_clone_work_end.py` (10 minutes or more)
  - landing and publishing: `tests/test_canonical_sync.py tests/test_landed_check.py`
  - worklog: `tests/test_worktrace.py tests/test_worklog.py`
- `tests/conftest.py` sets a generated `GIT_CONFIG_GLOBAL` and a session-wide temporary `HORTORA_WORKLOG_DB` at import. Tests must never reach `~/.gitconfig` hooks or `~/.hortora/worklog.db`. If you add another machine-wide resource, isolate it the same way: at conftest import, not only in a per-test fixture.

### 3.5 This machine's command restrictions

Hooks block some shell forms. When a command is refused, change its form; do not retry it.

- Use `git -C <path> ...`, never `cd <path> && git ...`.
- Do not use `grep` or `cp` on the command line in project directories (a hook blocks them). Read files with the Read tool, or write a small Python script to the scratchpad and run it.
- No shell loops, no `find -exec`, no backslash line continuations, no multi-line `python3 -c "..."`. Put anything longer in a script file.
- zsh does not split a variable into words: `$CMD arg` runs one program named by the whole string. Use a wrapper script.
- A commit to `HANDOFF.md` is blocked until `handover/wrap_orchestrator.py` has completed. That is deliberate.
- `.plan`, `.queue`, `.meta`, `.slot` are written only through `plan_manager.py`, `queue_io` and `slot_io`. Never edit them directly.
- Never use or suggest `--no-verify`.

---

## 4. The lifecycle

### 4.1 Commands

All go through `project/work.py <command>`. Routing decisions come from `project/work_route.py:route()`, never from the model.

Steps as defined in `PIPELINES` (`*` marks a judgment step with a handler):

| Command | Steps |
|---|---|
| `start` | process_archive_requests, sync_main, resolve_issue*, stacked_pr_detect, branch_name*, flyway_scan, create_branches, recover_plan, recover_plan_offer*, design_routing, scaffold, commit_scaffold, platform_coherence*, check_protocols*, garden_search, load_specs, check_intellij, brainstorm_offer* |
| `continue` | auto_resolve_transient, lifecycle_continue*, sync_queue_branch, health_check, load_specs, load_context* |
| `done` / `next` | lifecycle_next*, advance_issue, tick_github, context_refresh, deferred_check* |
| `pause` | wip_commit_project, wip_commit_workspace, push_and_stack (nothing is pushed, despite the name) |
| `resume` | stack_pick*, pop_stack, checkout_branches, rebase, reset_wip, sync_queue_branch, context_resume* |
| `find` | refresh_cache, query_recommendations, present_candidates*, populate_queue |
| `wrap` | review*, diary*, file_issues*, item_finished*, mark_done, commit_queue, handoff* |
| `end` | review*, diary*, file_issues*, item_finished*, mark_done, commit_queue, land, promote_backlog, publish, publish_blog, handoff* |

`work` and `work continue` are "carry on": `work.py continue`, which resumes the active item. `work start` (no issue) and `work next` are "move on": `work.py start` / `work.py next`, which gate on active work — the user must release the current item (done, deferred, or move down) before the next one starts. `work done` marks the active item done without starting anything.

### 4.2 Gates that run before a pipeline

In `work.py main()`, in this order. Each can stop the command and print why.

1. `apply_clone_guard`: no new work in a canonical repo of a clone-enabled family.
2. `sequence_branch_check` (wrap, end): the branch the queue names must be checked out somewhere here. Checked **before** any repair.
3. `apply_alignment`: project and workspace must agree on a branch. Two states are repaired automatically; anything else is `ACTION=decision` with `OPTIONS=`.
4. `apply_move_on_gate`: handles `step_done=move_on_gate` from a prior `current_item_not_released` decision. Executes the user's choice (mark-done, defer-active, move-down) and re-routes as `continue`.
5. `apply_route`: for the routed commands; `_named_start` registers a named issue in the queue. For `start`/`next` with an active item, checks for dirty tree then returns `DECISION=current_item_not_released`.
6. `sequence_preflight` (wrap, end): prints `SCOPE=`, `RESUMING=`, or stops with `nothing_to_end`.
7. `begin_run`: step progress in `.work-progress` belongs to one run. For `wrap` and `end` the run key is the command alone, so a retry resumes whatever the queue now says.

Stops and decisions you will see: `canonical_repo_of_clone_family`, `nothing_to_end`, `active_branch_not_checked_out`, `current_item_not_released`, `workspace_not_level`, `alignment_*`, `named_issue_already_closed`, `named_issue_done_awaiting_close`, `another_item_active`.

### 4.3 An item's states in the queue

```
- [ ] owner/repo#N — title                      unchecked
- [ ] owner/repo#N — title        ← active      being worked on
- [ ] owner/repo#N — title ← done on <branch>   finished, not yet landed
- [x] owner/repo#N — title                      closed by the ceremony
```

`mark_done` writes "done on branch" and makes the next item active. That changes `covers` in the queue state to the next item (this caused two bugs; see section 9).

Items stack by default: a new branch is cut from the previous item's branch while that item is unlanded. `refs/soredium/base/<branch>` and `refs/soredium/parent/<branch>` record what each branch was cut from (`project/branch_base.py`). An item marked `(from main)` starts from the base branch.

### 4.4 wrap versus end

- **wrap**: review, diary, loose ends filed and queued, "is the item finished?", mark done if so, handoff. It never lands, promotes, publishes, closes or stamps.
- **end**: the same, plus land everything marked done, promote, publish the covered repos and their landed blog entries.
- `item_finished` is never skippable and requires `finished=yes` or `finished=no`. With `no`, the active item is left exactly as it is and only earlier done items land (`close(workspace, land_active=False)`).
- `end` can be run part-way through a queue, any number of times.
- On a mechanical failure the sequence prints `ACTION=error STEP=<name> ERROR=<code>` and stops. Fix the cause and run the same command again; it resumes at that step.

Errors from the `land` step and what to do:

| ERROR | Do |
|---|---|
| `promotion_needed` | Run the `PROMOTE_COMMANDS` line it printed (check the `covers=` value is the finished item's reference), then re-mark the squash review and retry |
| `squash_review_needed` | Run the `git-squash` skill on that branch; it records the review. Retry |
| `land_failed` | Read `DETAIL`. Usually uncommitted changes or a rebase conflict. Nothing was landed |

---

## 5. Queues

### 5.1 The rule

`project/queue_io.py:queue_dir(workspace)` returns the one directory that holds the queue:

1. a slot or clone with `.slot` **and** the marker `.queue-root`: the area root, whichever directory inside it you asked from
2. a workspace whose `.notes` worktree (branch `notes`) already holds `.queue`: `.notes`
3. a workspace with its own `.queue` or `.plan`: the workspace
4. a workspace with a `.notes` worktree and no queue yet: `.notes`
5. otherwise the workspace

Every tool goes through `read_queue(workspace)` and `write_queue(workspace, queue)`, or asks `queue_dir`. `read_queue(dir, exact=True)` reads the file in that very directory and is only for listing.

### 5.2 Why

`.queue` is a tracked file in each workspace repo, so `git clone` copies that repo's whole backlog into every workspace clone. Without the rule, a slot of several repos has several differing queues plus a stale root copy, and which one a tool uses depends on the current directory (casehub slot 196 had five).

### 5.3 Switching an area

Which areas are switched is operational state: it is kept in the workspace `HANDOFF.md`, not here. As of 2026-11-20 only the hortora clone was switched.

An existing slot is switched by its owner, one at a time:

```
python3 ~/.claude/skills/project/queue_home.py show  <slot-dir>
python3 ~/.claude/skills/project/queue_home.py adopt <slot-dir> from=<dir> [--apply]
```

`adopt` is a dry run without `--apply`. It copies the chosen queue to the root, keeps the old root copy as `.queue.before-adopt-<date>`, writes `.queue-root` last, and removes nothing.

New permanent clones are switched at creation (`clone_manager.create_clone`). New numbered slots are not yet (Hortora/soredium#580). The notes store (`project/notes_store.py`) is dormant: nothing creates the worktree outside tests, so rules 2 and 4 do not fire yet (Hortora/soredium#581).

### 5.4 Things that must stay true

- In a marked area, the `.queue` and `.plan` inside workspace clones are inherited backlog, not this area's work. Never read them as a fallback, never commit them, never call them stale, never delete them.
- No script builds `<workspace>/.queue` by hand. If you find one, route it through `queue_dir`.
- `write_queue` retires an older `.plan` (renames it to `.plan.bak`) only on the write that first creates `.queue`. A workspace that tracks both keeps both.

### 5.5 Other state files

| File | Where | Notes |
|---|---|---|
| `.work-progress` | workspace | Step progress for the current pipeline run (`project/progress.py`). Tracked in git and modified by the pipeline. `close.py:commit_pipeline_files` commits it before rebase; still tracked until the second half of Hortora/soredium#587 untracks it |
| `.pause-stack` | workspace `main` | Paused branches (`project/stack.py`). Entries still store bare issue numbers |
| `.close-state` | workspace | Written while the ceremony lands. A stale one is ignored |
| `.landed` | slot root | Slot is ready for archive. Never written for a permanent clone |
| `.wrap-log.jsonl`, `.land-ledger.jsonl` | workspace | Logs written by the orchestrators. Same lifecycle as `.work-progress`: committed by `commit_pipeline_files` before rebase |

---

## 6. Architecture

### 6.1 Files that matter

| File | Size | Role |
|---|---|---|
| `project/work.py` | large | Pipelines, gates, routing glue. The entry point for every command |
| `project/orchestrator_engine.py` | medium | `run_loop`: runs mechanical steps, yields judgment steps |
| `project/work_route.py` | small | `route()`: what `continue` should do |
| `project/queue_io.py` | medium | Queue parse and write, `queue_dir`, `.plan` migration |
| `project/queue_home.py` | small | `show`, `adopt`, `mark` for root queues |
| `project/notes_store.py` | small | `.notes` worktree store; no remotes |
| `work-slot/plan_manager.py` | large | Queue edits by path: append, activate, mark-done, advance, detect. Older code; writes whatever path it is given |
| `project/canonical_sync.py` | large | `locate`, `land`, `land_all`, `publish_base`, `follow`, `checked_out`, backup. The only code that moves base branches |
| `work-end/close.py` | large | The ceremony |
| `work-end/scope.py` | medium | What one `work end` may touch: `covered`, `land`, `publish`, `promote_backlog`, `publish_blog`, `commit_queue` |
| `work-end/artifact_promote.py`, `artifact_sweep.py` | medium | Promotion |
| `publish-blog/blog_routing.py`, `blog_publish.py` | medium | Which site an entry goes to; copying and committing |
| `project/branch_base.py`, `squash_marker.py` | small | The refs that record branch origin and squash review |
| `project/topology.py`, `ctx.py`, `work_state.py` | medium | Where am I: layout, context, state. Read-only |
| `project/alignment.py` | small | Project and workspace branch agreement |
| `project/clone_manager.py` | small | Permanent clones |
| `work-slot/slot_lifecycle.py` | large | Slot create, archive, restore |
| `project/worktrace.py` | small | The one worklog recorder |
| `scripts/worklog.py` | medium | The SQLite worklog (`~/.hortora/worklog.db`) |
| `hooks/push-guard.py` | small | Blocks `git push` from a slot or working branch |

Size: large is over 1,000 lines, medium 300 to 1,000, small under 300. Small files are the focused deciders; start there.

Legacy, do not extend: `project/lifecycle.py`, `project/work_chain.py`.

### 6.2 How a landing works

`canonical_sync.land_all(work)`:

1. `locate(repo)` finds the canonical repo behind a clone (its `local` remote), the base branch and the publishing remote.
2. Takes a landing lock per canonical repo.
3. Rebases every branch first, because rebase is the only step that can conflict. Nothing has moved yet.
4. For each branch: `hold` (canonical fetches the branch from the clone into a landing ref), `advance` (canonical's base ref moves by fast-forward), release, then the clone follows.
5. Returns the new base SHA and how many commits canonical now has that the remote lacks.

Canonical being ahead of its remote is normal: landed work waiting to be published.

`follow(repo)` reports how a clone's base branch relates to canonical: `current`, `fast-forward`, `diverged`, `blocked`. A **diverged** clone base (commits on both sides) is never replayed onto canonical; the ceremony reports it under `not_landed`.

### 6.3 What the ceremony does

`close.py:_close(workspace, land_active)`:

1. Refuses if a repo is mid-rebase or mid-merge, or branches are misaligned.
2. Reads the queue, builds one entry per done item plus the active one, resolves each to targets (repo, branch).
3. Orders entries by what each branch was cut from; queue order only breaks ties.
4. Refuses with `promotion_needed` if workspace artifacts are not yet in the project.
5. Refuses with `squash_review_needed` if a multi-commit project branch has no review record for its tip.
6. Preflight, then writes `.close-state`.
7. Lands each entry, stamps each branch, clears the base and review refs, marks the item complete.
8. Advances the queue. In a slot, carries stray commits (work on a clone's own base branch) unless that base had diverged. Marks a drained numbered slot `.landed`. A permanent clone is settled and never archived.
9. Reports `LANDED_*`, `CLOSED_ITEM=`, `CARRIED=`, `NOT_LANDED=`, `UNPUBLISHED=`, `UNPROMOTED_BACKLOG=`.

It never squashes, never pushes, never archives.

### 6.4 Refs and markers

| Ref or file | Written by | Meaning |
|---|---|---|
| `refs/soredium/base/<branch>` | `branch_base.record` | Commit the branch was cut from |
| `refs/soredium/parent/<branch>` | `branch_base` | Branch it was stacked on |
| `refs/squash-reviewed/<branch>` | `squash_marker.mark` (via `git-squash`) | Tip that was reviewed |
| `refs/backup/<clone>/<branch>` | post-commit backup hook | Copy of a clone's branch held in canonical |
| `refs/rescue/*` | by hand, before history rewrites | Never delete |
| `.slot`, `.permanent`, `.queue-root`, `.landed`, `.clone-enabled`, `.workspace` | various | Area markers; see sections 2 and 5 |

### 6.5 Publishing

- `canonical_sync.publish_base(repo)`: fetch, settle canonical's base onto the remote if it moved, push (never forced), mirror. Refuses a repo whose pre-push hook is the retired one and names `scripts/install_linear_pre_push.py`.
- `scope.covered(workspace)` is the list of canonical repos one `work end` may publish. "Publish all" means that list and nothing else.
- Blog routing: `~/.claude/blog-routing.yaml`, plus a workspace override (`soredium/blog-routing.yaml`). One resolution detail is not what a reader would assume and was the fix for a real mis-publish: a fallback rule applies only when no project rule matched at all, never in addition to one. An untyped entry is a note. Nothing reaches an organisation's site without a rule naming its project. Run the plan and read the destinations before publishing anything by hand.
- The `publish_blog` step also refreshes already-published entries whose source changed. On 2026-11-20 that was 21 entries with repaired frontmatter.

### 6.6 The worklog

`project/worktrace.py record(action, /, repo=, branch=, **details)` writes one row to `events`. The script that performs an action calls it. Which script records which action is listed in `CLAUDE.md` under Key Skills, `worktrace.py`.

Read it with `python3 ~/.claude/skills/project/worktrace.py show limit=40 [action=<name>]`.

Rules: recording never fails the action (one `WARN=worklog_not_recorded` line on stderr); the fixed parameters are positional-only so a detail called `action` or `repo` cannot collide; only functions present in every installed `worklog.py` are called, because an older copy at `~/.claude/lib/worklog.py` may be the one imported.

---

## 7. How to change things safely

A procedure that works for a model without the full history in its head.

1. **Find the single place.** Most behaviours have one deciding function: `queue_dir`, `route`, `locate`, `follow`, `covered`, `review_status`. Change that, not its callers.
2. **Write the failing test first, on real repos in `tmp_path`.** No mocks for git. Copy a fixture from the nearest existing test file.
3. **Make the harness supply what a real caller supplies.** For "must not be led to X", hand the code X and assert X's bytes and `git status` are unchanged afterwards.
4. **Break the rule on purpose and watch the test fail.** Commit your work first, replace the deciding function's body with the old behaviour, run the tests, confirm they fail, then `git checkout -- <file>`. A test that passes with the rule removed proves nothing.
5. **For anything that reads:** enforce rule 5 with a before and after snapshot test (`tests/test_ctx_reads_only.py` is the pattern).
6. **Run the suites for every file you touched**, then the full suite in the background before landing.
7. **Check the real machine, read-only.** List files, read them, use plain `git -C ... status/log/rev-parse`. Use `queue_home.py show` for queues.
8. **Land and install, then use it for real once** and read the worklog trace. Tests did not find the two defects the first live `work end` found.
9. **Update the docs in the same change**: `CLAUDE.md` (Key Skills, Developer Workflow), `README.md` Repository Structure for a new script, `docs/protocols/` for a new standing rule.

When to stop and ask the user instead of deciding:

- anything that publishes outside a `work end` scope
- anything that rewrites history, deletes a branch or removes a file you did not create
- switching a slot's queue (`adopt --apply`) or converting a workspace layout
- two readings of the user's intent that would lead to different files being changed
- a state the tools call a `decision`: present the `OPTIONS=` with a recommendation

Reviewing someone else's branch (another session's work): read the diff and run its tests yourself. Do not accept a report. Look specifically for removed assertions, ignored return codes, `rmtree`, `reset --hard`, `push`, commits without a pathspec, and bare issue numbers. Take the commit onto your own branch with `git fetch local <branch>` and `git cherry-pick`; never touch or delete the original branch.

---

## 8. Areas to watch

Ordered by how much damage a mistake does.

1. **Anything that writes to a canonical repo.** `advance`, `checked_out`, `publish_base`, `artifact_promote`. A bug here affects every session on the machine.
2. **Old slots.** `casehub/slots/207` holds a clone whose `main` has diverged from canonical by more than a thousand commits each way. The ceremony refuses to carry a diverged base, but any new "carry" or "catch up" logic must repeat that check.
3. **Marked areas reaching inherited files.** A reviewer found four such paths after the first implementation (health checks, `plan_manager.detect`, state detection fallback, scaffold with `force=yes`). Three are fixed. Assume more exist in code that was not read: `plan_manager.py` CLI commands, handler markdown that tells a session which path to pass, `work_route.py`, `alignment_repair.py` (Hortora/soredium#584).
4. **Shared root queue with no lock.** Two sessions in one switched slot do read-modify-write on the same file; the last writer wins (Hortora/soredium#579).
5. **`covers` after `mark_done`.** It names the next item. Anything that uses `queue.state.covers` after an item is marked done is talking about the wrong issue. The promote command printed by the ceremony does this today.
6. **Run keys and progress.** `.work-progress` decides what is skipped. A wrong key either restarts a sequence or treats old steps as done. If a command behaves as if it "already did that", print `.work-progress`.
7. **Blog routing.** One wrong rule publishes to an organisation's public site. Removing published entries meant rewriting that site's history. Always run the plan first.
8. **Module shadowing.** In a subprocess the installed copy of a shared module (`~/.claude/lib`, `~/.claude/skills/project`) can be imported instead of the sibling file. New code must not assume a just-added function exists in an imported shared module. `tests/conftest.py` pins the repo's copies for in-process tests only.
9. **Tests that touch real resources.** An environment dict built at module import bypasses per-test isolation. 797 test rows had reached the real worklog before this was found.
10. **Silent `except Exception: pass`.** `work-start/scaffold.py` still swallows worklog errors this way. Prefer one warning line.
11. **Message matching on git output.** Git has several wordings for the same condition. Ask git a question (`status --porcelain -- <file>`) instead of matching text.
12. **Hook-driven side effects.** A global hook dispatcher chains to each repo's `.git/hooks`; post-commit runs the backup hook in clones. Commits made by tools (queue, stamp, notes) pass through commit-msg hooks and need an issue reference or a `no-issue:` line.

---

## 9. What went wrong before, and the lesson

Read this as a list of mistakes not to repeat.

| What happened | Lesson |
|---|---|
| A context resolver, run only to inspect a slot, renamed its `.plan` and wrote a `.queue`. Two more writes hid in other read paths | Reads never write. Prove it with a byte-for-byte snapshot test |
| The fix for that retired `.plan` on every queue write and deleted a tracked file in the next ceremony | Run the real ceremony once before installing. Install order matters |
| 120 blog entries were published on an approval for "18"; 87 went to the wrong organisation's site | Never approve or act on a count you did not produce yourself. Run the plan and read destinations |
| A change removed a clean-status assertion and hid a bug that moved a branch | A removed or weakened assertion is the first thing to look for in review |
| A promotion script reported success when its commit had failed | Check every return code. "Nothing to commit" is the only benign failure, and test for it by asking git, not by matching text |
| Tests for the root-queue rule passed with the rule deleted | Break the rule on purpose before trusting a test |
| A recorder that "never raises" crashed a command: a detail named `action` collided with its parameter | Binding errors happen before the function body. Use positional-only parameters |
| A retried `work end` restarted from the review after the queue advanced | State that identifies "this run" must not depend on things the run itself changes |
| Commits were made three times with a failing test because the status was hidden by a pipe | Read the summary line. Do not chain the commit to the test with `;` |
| Edits were made before starting an item and sat on the clone's `main` | Start the item first |
| A session took "publish all" to mean every repo on the machine | Scope is enforced in code (`scope.covered`), not left to interpretation |
| A notes store was built to push and pull queues, with a hard reset on conflict | If data has one owner, do not build sync for it |

---

## 10. Areas to improve

The backlog is not kept here. It is the epic Hortora/soredium#595 and the queue (`queue_home.py show ~/claude/hortora/clone/soredium`).

What a session needs to know because it changes how things behave today:

- **`.work-progress` and `.wrap-log.jsonl` are tracked and modified by the pipeline.** `close.py:commit_pipeline_files` now commits them before rebase, so the ceremony no longer leaves workspace clones on closed branches (Hortora/soredium#587 first half). They are still tracked; untracking is the second half. A ceremony with anything in `not_landed` stops before publish (`scope.py land()` exits 1).
- **`queue.state.covers` names the next item once an item is marked done.** The promote command the ceremony prints carries it; correct the `covers=` value by hand.
- **Old layouts exist on this machine** (found 2026-11-19): eight workspaces and one slot use only `.plan`; five workspaces keep lifecycle files under `design/`. They are read in place and reported as `LEGACY_LAYOUT=`. Conversion is `python3 work-slot/plan_migrate.py to-root <workspace>`, one at a time, with the owner's agreement.
- **`casehub-ops` has a plain `.notes` directory** holding `NOTES.md`. The notes store refuses it; nothing may replace it.
- **The handover skill names `garden_feedback_table.py`, which is not installed.** Skip that step with a reason when no garden entries were retrieved.
- **Context budget.** A session watches its remaining context: it suggests `work wrap` when a task runs long, and after each finished item recommends continue, `work end` then continue, or stop. Until Hortora/soredium#586 lands this is done by judgement.

---

## 11. Where to read next

| For | Read |
|---|---|
| The landing design and stage order | Hortora/soredium#515 |
| The queue design, the review of the first store, the slot findings | Comments on Hortora/soredium#567 dated 2026-11-19 |
| Standing rules | `docs/protocols/INDEX.md` |
| Git behaviours the design relies on, pinned by tests | `tests/test_git_landing_behaviour.py` |
| What the tools did, in order | `python3 ~/.claude/skills/project/worktrace.py show limit=60` |
| The narrative of how this was found | `docs/blog/2026-11-19-mdp01-five-queues-in-one-slot.md`, `docs/blog/2026-11-05-mdp01-the-file-that-should-never-be-deleted.md` |
| Current operational state | `HANDOFF.md` in the workspace |
| Project conventions | `CLAUDE.md` (Landing Rules, Key Skills, Developer Workflow) |

Keep this file current. When a section stops being true, fix it in the same change that made it untrue.
