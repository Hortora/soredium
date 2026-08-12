---
layout: post
title: "Pause means nothing if you can't go somewhere"
date: 2026-06-05
type: phase-update
entry_type: note
subtype: diary
projects: [cc-praxis]
tags: [work-lifecycle, testing, cleanup]
---

Typing `work pause` lands you on main with a paused branch on the stack. The confirmation said: "Resume with: work-resume." That's it. No mention that you could start something new from here.

And if you typed `work` with exactly one paused branch on the stack, it auto-resumed. No question. Just resumed.

So pause was effectively: commit your WIP, switch to main, immediately reverse. That's not pause — that's an elaborate roundtrip with extra steps.

The fix is small. Stack=1 now shows the same picker as stack=2+:

```
You have 1 paused branch:
  1. issue-108-some-work  #108  paused 3 hours ago

Resume it, or start something new? (1 / new)
```

And `work-pause`'s confirmation now ends with: *"You're on main — type work to resume this branch or start new work."*

We also updated `work-start`'s detection block, which had a comment explicitly saying stack=1 auto-routes to work-resume. That comment was the specification for the broken behaviour — it had to go too.

Worth having tests. The lifecycle skills are markdown, not executable code, so the tests are content assertions — we check that the routing table has no separate "1 entry" row, that the confirmation mentions main and new work, that work-start no longer claims auto-resume. Fourteen tests in `tests/test_work_lifecycle.py`, locking the routing rules in place.

One thing caught me during test writing: `assert "automatically" not in skill_text` matched the frontmatter `description:` field, not the routing table I was targeting. The word appeared in both. Had to scope the assertion to pipe-delimited rows only. Related: `**word** automatically` doesn't match `"word automatically"` — markdown bold survives as raw characters in the string. Both are now garden entries.

Alongside the fix, cleared two pieces of clutter: the `quarkus-flow` stub (a one-paragraph file pointing at a garden entry — the actual content had moved out long ago) and `sync-local` from marketplace.json (it's dev-only, shouldn't be advertised to marketplace users). 29 skills now.
