---
layout: post
title: "The layer we didn't know was missing"
date: 2026-06-02
type: phase-update
entry_type: note
subtype: diary
projects: [cc-praxis, casehub]
tags: [write-content, arc42stories, taxonomy, modes, writing-theory]
---

Two threads had been running in parallel for a while. One was content structure and voice — the write-content taxonomy, the research into how Newman and Kinneavy and Diátaxis all arrive at the same underlying set of distinctions. The other was casehub-devtown's ARC42STORIES.MD, which had been accumulating content in its own way.

I looked at both and saw the connection. DevTown's arc42stories was the ideal application surface for everything we'd been developing. And applying it there would force the theory to become concrete — which would harden the skill in ways that pure theory couldn't.

That's what this session was: using arc42stories as the proving ground to flush out what the write-content skill still lacked.

What it lacked was mode.

## Form, Mode, Voice — the layer we were missing

The write-content skill had two layers: what kind of content it is (form), and how it sounds (voice). What it didn't have was how it *presents* information. That's the middle layer. Form tells you what you're writing. Voice tells you how it sounds. Mode tells you how information is structured and delivered to the reader.

We'd been collapsing mode into form and into voice. The per-type guidance in anti-slop.md — `### Article/tutorial`, `### Article/explanation` — was actually mode guidance masquerading as voice guidance. The forms themselves were carrying mode rules that should have lived somewhere else. Everything worked, after a fashion, but nothing was quite in the right place.

The breakthrough was recognising that mode is orthogonal to both. A diary entry (form) can use explanation/discursive mode (the author's journey of understanding) with Mark Proctor's personal voice. An arc42stories Gotcha section uses how-to/diagnostic mode (Symptom → Cause → Fix) with common voice. The form doesn't determine the mode. The mode doesn't determine the voice. They compose.

Once the three layers were named, the right word for the middle layer was obvious: *mode*. Kinneavy called it "aim." Britton called it "function." Diátaxis calls it "type." Newman — writing in 1827 — called it "modes." We chose mode deliberately: it has the deepest lineage and was already sitting in our four-dimension paper framework under Anker.

## Five independent frameworks, same answer

That parenthetical is worth expanding. The research document (`docs/content-taxonomy-article-notes.md`) has been building a case over several sessions that the content taxonomy we arrived at from practice — Note, Article, Brief, Essay — maps directly onto frameworks developed independently across 200 years, from completely different starting points, by people who had no knowledge of each other.

Newman (1827): narration, description, exposition, argumentation.
Kinneavy (1969): expressive, referential, literary, persuasive.
Britton (1970): transactional, expressive, poetic.
Diátaxis (2017): tutorial, how-to, reference, explanation.
This work (2026): note, article, brief, diary.

The concept of *mode* — how information is organised and presented — converges across all five. The terminology doesn't converge. But Kinneavy himself documented this kind of convergence in 1969 across eight scholars and called it "almost fearful symmetry."

What we added to the research document this session:

**The structure–prose spectrum.** All writing sits on a spectrum from pure structure (JSON, YAML — maximally machine-readable, zero natural language) to pure prose (the novel — no headings, no labels, no lists). Our taxonomy occupies a band in the middle: Brief near the structure end, Essay near the prose end. The key insight is that LLMs default to the prose end — statistical pressure from a training corpus dominated by prose. Anti-slop guidance is a correction pushing toward the required mode. But anti-slop has been treating symptoms. Wrong mode is the root cause.

**The multi-mode document.** Every framework treats mode as a property of the whole document — a text is a tutorial, or an explanation, or a reference. None address documents that contain multiple modes across sections. Arc42stories has six: Reference, How-to/diagnostic, Explanation/comparative, Tutorial, Argumentation, and How-to/procedural. CLAUDE.md files. Platform guides. Technical specifications. This may be the dominant pattern in technical documentation, and none of the five frameworks have language for it.

**Mode sub-types.** At a first level, the modes are what they are. At a second level, some modes have genuinely different constraint sets between sub-types:

- Explanation/discursive vs comparative — author-centric journey vs system-centric before/after delta
- How-to/procedural vs diagnostic — steps from working state vs Symptom → Cause → Fix from broken state
- Reference/lookup vs pointer vs inventory — find a term vs point to authority vs enumerate what exists
- Argumentation/decision vs rationale vs essay/sustained — ADR format vs inline reasoning vs extended argument

The distinction between discursive and comparative explanation turned out to be the most practically important one. "What it adds" sections in arc42stories had only narrative instruction — "teaching narrative, what this layer introduces" — and drifted to prose in every implementation. The comparative sub-type prescribes Before:/After: contrast, a length cap, explicit "Not closed here" scope boundaries, and no personal voice. That's not taste. That's the constraint set that locks the section into the right mode and prevents drift.

## The write-content restructure

The taxonomy settled, we rebuilt the skill to match it.

Three directories now, one per layer:

```
write-content/
  forms/     ← what kind of content (Note, Article, Diary, Brief, Technical Documentation)
  modes/     ← how it presents (Tutorial, Explanations, How-to, Reference, Argumentation)
  voice/     ← how it sounds (common-voice, anti-slop, mandatory-rules)
  mandatory-gates.md   ← process control (pre-draft gate, third-party review)
  SKILL.md
```

`defaults/` is gone. The name said nothing; the new directory names signal the taxonomy from the structure alone. `essay.md` dissolved into a three-way split: structure pattern into article.md, mode mechanics into modes/argumentation.md (as a new essay/sustained sub-type alongside decision and rationale), voice texture into the argumentation mode file. `structure-principles.md` distributed its content across `modes/_universal.md` (scannability, heading test, element selection), `SKILL.md` (encoder/decoder framework as form routing theory), and `voice/anti-slop.md` (sentence/paragraph rules).

The process gates — pre-draft voice classification, factual accuracy verification, third-party reference review — moved out of `voice/mandatory-rules.md` and into `mandatory-gates.md` at the skill root. They were never voice rules. They're control flow. Burying them in voice was the wrong taxonomy.

The SKILL.md workflow went from six steps to seven. Step 5 is now the pre-draft gate — a hard stop before writing begins. Step 7 is quality check plus third-party review. The gate runs *before* the draft; the review runs *after*. The ordering matters: verify your register and facts before generating prose, not after.

Anti-slop became universal-only. The per-type sections (`### Article/tutorial: include real friction points...`) moved into mode files as "Voice texture" sections. Each mode file is now self-contained: structural constraint set, decision rule for sub-types, and voice texture in one place. No parallel taxonomy — no separate anti-slop section to maintain alongside each mode file.

25 files changed, 1,887 insertions, 810 deletions across four commits on issue-109.

## Technical documentation as a form

The new form that made all of this necessary is `forms/technical-documentation.md`. It declares:

- The distinguishing test: does the subject evolve? Maintained alongside the system? Dual audience (human + LLM)? → technical documentation
- The mode map: a table assigning a mode to every section type
- Dual audience writing rules: where LLM precision and human scannability conflict and how to resolve the tension
- The no-content-loss rule: when restructuring, nothing is omitted — only relocated
- The content migration guide: atomic-fact enumeration before rewriting, coverage verification after

The arc42stories canonical mode map lives here as the reference example. Other technical documentation declares its own. The principle — one declared mode per section type — is the same.

## Arc42stories — writing style lands in the spec

The arc42stories spec (`arc42stories-spec.md`) now has a Writing Style section. It contains the mode map, the structural prescription for "What it adds" (the section most prone to prose drift), and a pointer to `write-content/voice/anti-slop.md` for the universal banned patterns. No duplication — the spec names the files, it doesn't reproduce their content.

The "What it adds" prescription is worth quoting directly:

```
**Before:** [Previous state] — what existed, in one clause.
**After:** [Component] — what displaced or extended it, in one clause.

What this layer adds:
- **[Named capability]** — [specific mechanism]; [what it enables]

Not closed here: [Layer N] ([what it still lacks]).
```

Before this prescription existed, every implementation of "What it adds" drifted to prose. Not because the authors were careless — because the spec gave only a content description ("teaching narrative, what this layer introduces") with no structural constraint. The drift was predictable. The fix is equally predictable: give it a structure. The structure *is* the mode.

We verified this against the devtown ARC42STORIES.MD. The sections that were already in the right mode — Gotchas, Pattern to replicate, Key files — all had explicit structural prescriptions from the first commit of the spec. `Format: **Symptom** → Cause → Fix`. `Numbered steps`. `path/to/File.java — [what it is and what it does]`. The sections that drifted had narrative instructions only.

The lesson: structural prescription prevents mode drift. If you want a section to stay in How-to/diagnostic mode across every implementation, prescribe the structure. The mode follows.

## What "label is the fact, body is the reasoning" actually means

The sweet spot between pure structure (Brief — labels only, scanning IS the experience) and pure prose (Explanation — prose carries the reasoning) has a name now. We called it Structural, then realised it was just a discipline applied within any mode:

Every entry has a label that could stand alone as a fact. The body adds reasoning, not more facts. Strip all labels and read only those — the result should be a complete factual skeleton with no gaps. If a fact only exists in the body, it's invisible to scanning. And invisibility to scanning means invisibility to the LLM loading the document for session context.

This resolves the dual audience tension cleanly. Humans scan; LLMs need precision. Labels serve both: they're the scannable anchor for humans and the unambiguous fact for LLMs. Bodies serve both: they're readable explanation for humans and self-contained reasoning for LLMs. The structure isn't a compromise — it's better for both audiences simultaneously.

## The clinical session is next

devtown's ARC42STORIES.MD is styled. The arc42stories spec prescribes the Writing Style. The write-content skill has the modes and mode files installed. casehub-clinical has a complete LAYER-LOG.md (seven layers), two DESIGN.md files, five ADRs, and twenty blog entries — no ARC42STORIES.MD.

Issue #54 is the migration. Before it starts, one prerequisite: the Layer 5 extension from issue #48 (AeEscalationListener + IrbDecisionListener observer fallback) needs to land in LAYER-LOG.md. That's the source material.

The modes are ready. The spec prescribes the structure. The migration is mechanical from there.
