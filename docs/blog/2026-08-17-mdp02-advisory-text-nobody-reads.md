---
layout: post
title: "Advisory Text That Nobody Reads"
date: 2026-08-17
entry_type: note
subtype: diary
projects: [soredium]
tags: [write-content, skill-design, content-management]
---

## The Problem Nobody Noticed

The write-content skill has had this paragraph in it for months:

> A diary entry can span multiple sessions. Write what you have now — the next session can read the unpublished draft and append to it.

Good advice. The kind of advice nobody follows, because there's no mechanism behind it. Every invocation of the diary form creates a new file with an incremented sequence number. `mdp01`, `mdp02`, `mdp03`. The skill doesn't check whether an entry already exists for this branch. It doesn't read prior entries. It generates a fresh filename and writes to it.

The result: a branch that spans two sessions gets two blog entries covering the same ground. The `series:` frontmatter field links them, but linking isn't deduplication. The first entry says "we built X." The second entry says "we built X, and also Y." The overlap sits there, published, adding nothing.

## Advisory vs Mechanical

This is a pattern worth naming. An advisory instruction in a skill body — "the next session *can* read the unpublished draft" — sounds like a feature. It isn't. It's a hope. The LLM might follow it, might not, and there's no mechanical check to remind it. The gap between "you can do this" and "the skill checks for this" is where silent failures live.

The diary form already had the right data to make the decision. Step 1 scans `BLOG_DIR` for entries with matching `series:` frontmatter. It reads the branch name. It knows whether prior entries exist. It just didn't *do* anything with that information beyond adding a continuity note at the top of the new entry.

## The Fix

A new Step 1b — between the existing series check and the gathering step. If prior entries exist with matching `series:`, read the most recent one and present a choice:

```
Prior entry found: 2026-08-16-mdp01-lifecycle-hardening.md
  "Lifecycle Hardening" — 2026-08-16, 847 words

  [R] Revise — update this entry with new content   ← default
  [N] New — create a separate entry in the series
```

Default to Revise when the existing entry covers work this session continued. Default to New when the work direction changed enough that the entries would stand as distinct narratives. If revising, the skill writes to the existing file — same path, same filename, no new sequence number. Step 3 drafts a coherent rewrite integrating old and new material, not an append.

Two files, 58 lines. The form file gains a decision step and a revise path in the write step. The SKILL.md replaces the advisory paragraph with a reference to the mechanical check.

The principle is simple: if a skill has information that would change its behaviour, it should act on that information. Text that says "you can" when it means "you should" is a bug in the skill, not in the LLM.
