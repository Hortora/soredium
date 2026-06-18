---
id: PP-20260522-6e976f
title: "Taxonomy subtype values must reflect the character of the content, not technical aesthetics"
type: principle
scope: repo
applies_to: "any taxonomy value additions or renames in soredium blog/note schema"
severity: important
refs:
  - docs/superpowers/specs/2026-05-22-diary-to-log-sweep-design.md
violation_hint: "A value that sounds more 'technical' or 'tidy' but doesn't match the actual character of the content — e.g. renaming 'diary' to 'log' for personal narrative writing because 'log' feels more consistent"
created: 2026-05-22
---

When naming or renaming taxonomy values (such as `subtype` in blog/note frontmatter), choose the word that accurately describes what the content *is*, not the word that sounds most technically consistent or tidy. Personal, in-the-moment, narrative project writing is a diary — not a log. A log implies dry, chronological, technical records. Renaming to match a naming pattern at the cost of semantic accuracy creates drift between the taxonomy and the content character, forcing descriptive language in skills and documentation to fight the taxonomy rather than align with it. When evaluating a proposed rename, ask: "Does this word match the character of the content, or only the naming convention?"
