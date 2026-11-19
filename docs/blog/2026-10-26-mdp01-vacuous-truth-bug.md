---
layout: post
title: "The Vacuous Truth Bug"
date: 2026-10-26
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [corruption-detection, parsing, bugs]
---

# The Vacuous Truth Bug

When `all_closed` starts `True` and you iterate over an empty list, it stays `True`. That's vacuous truth — logically correct, practically catastrophic. It's how our corruption detector decided all five open issues were closed, triggered auto-recovery, and transitioned a perfectly good work plan to `drained`.

The corruption triage system (`S3_ACTIVE_ALL_CLOSED`) checks whether every issue in a plan's `covers:` field is closed on GitHub. If they're all closed and the queue is empty, it's a legitimate signal — the plan is done, transition it. The check runs at session start, before any work happens. The auto-recovery is designed to be safe: it transitions state without deleting anything.

The problem was in how it parsed the `covers:` field. Two parsers exist in `plan_io.py`: `parse_covers()` handles bare numbers (`42,43`), and `parse_covers_qualified()` handles the `Owner/Repo#42` format that cross-repo plans use. The corruption detector used the bare parser. Our plan had `Hortora/soredium#448,Hortora/soredium#446,...` — five qualified refs. The bare parser saw none of them. Empty list. `all_closed` never got a chance to become `False`.

A second guard should have caught this. After confirming all covers are closed, the check inspects the queue for uncompleted items — if any exist, it returns no finding (the plan still has work). But the `.plan` file used an old flat format without the `## Queue` section header that `read_plan()` expects. Queue items parsed to empty. Guard didn't fire.

Two bugs, both silent, both producing the same empty result, compounding into a false positive that looked legitimate from every angle. The corruption detail message even listed all five issue numbers — they came from the raw `covers:` string, not from the parser output. Anyone reading the log would see "all covers CLOSED" and believe it.

The fix is one line that matters: `parse_covers_qualified()` instead of `parse_covers()`. Now qualified refs actually get checked against GitHub. We also added an empty-list guard — if parsing produces nothing, that's no signal, not confirmation. And each ref's repo gets passed individually to `gh issue view`, which matters for cross-repo plans where different issues live in different repositories.

The interesting question is why the bare parser existed alongside the qualified one in the first place. `parse_covers()` was written first, for single-repo plans where covers were just `42,43`. When cross-repo support was added, `parse_covers_qualified()` was built — but the existing call sites weren't migrated. The qualified parser handles both formats (bare and qualified), so it's a strict superset. Two other corruption checks (`S15` and `S8`) have the same latent bug. They'll get separate fixes.

Vacuous truth bugs are hard to catch in review because the code reads correctly. The loop over `issue_nums` does exactly the right thing for each element. The problem is that "for each element in an empty collection" executes zero times, and the default that survives is whatever the accumulator started as. In a `for`/`all` pattern, that's always `True`. The defence is the guard we added: if the collection is empty after parsing, return early with no opinion rather than proceeding with a vacuously true one.
