---
id: PP-20260602-abf3f6
title: "write-content skill files observe three-layer taxonomy — form files carry what/why only; mode files carry how; voice files carry register and anti-slop"
type: rule
scope: repo
applies_to: "write-content/ skill directory — forms/, modes/, voice/"
severity: important
refs:
  - write-content/SKILL.md
  - write-content/forms/article.md
  - write-content/modes/explanations.md
  - write-content/voice/anti-slop.md
violation_hint: "Mode constraints (structural rules, length caps, decision rules, voice texture) appear inside a forms/ file; or voice guidance (register, anti-slop) appears inside a modes/ file"
created: 2026-06-02
---

The write-content skill is organised into three directories that map to three orthogonal dimensions: `forms/` (what kind of content — intent, audience, when to choose it), `modes/` (how information is presented — structural constraints, decision rules between sub-types, voice texture), and `voice/` (how it sounds — register rules, anti-slop, process gates). A form file answers "what is this and why would I write it?". A mode file answers "how do I structure it?". A voice file answers "how should it sound?". No directory should carry content that belongs to another layer — if structural constraints or voice texture appear in a form file, they are in the wrong place and will be duplicated or missed when the mode is used from a different form.
