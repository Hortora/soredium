# Write-Content Skill Restructure — Design Spec

**Date:** 2026-06-01
**Status:** Draft v3 — post-review update
**Scope:** Full restructure of the write-content skill to reflect the Form / Mode / Voice three-layer taxonomy

---

## Problem

The write-content skill was built incrementally. The result is accumulated structure rather than designed structure:

- "Style" conflates three distinct layers — form, mode, and voice — that have different purposes and need different files
- `defaults/` is a catch-all directory whose name signals nothing about what it contains
- `structure-principles.md` covers form-level, mode-level, and voice-level concerns in one file
- Mode is entirely absent as an explicit layer — implied by form sub-type names in `anti-slop.md`
- `article.md` carries mode-level guidance (tutorial steps, explanation narrative rules) inside a form file
- No guidance exists for technical documentation (arc42stories, platform guides, system design docs)
- The pre-draft gate is buried in `mandatory-rules.md` with no explicit workflow step
- Anti-slop per-type guidance is parallel to mode definitions — two files to update when a mode changes

---

## The Three-Layer Taxonomy

Every piece of content is fully specified by three independent dimensions:

| Layer | Question answered | Directory |
|---|---|---|
| **Form** | What kind of content is this? | `forms/` |
| **Mode** | How does it present information? | `modes/` |
| **Voice** | How does it sound? | `voice/`¹ |

¹ Universal voice rules live in `voice/`. Per-mode voice texture (how a specific mode sounds when done right or wrong) lives in each mode file. The top-level Voice directory covers what applies regardless of mode; mode files carry the voice signature intrinsic to that mode.

These are independently selectable at the top level, but each mode carries an intrinsic voice signature — mode-level texture is part of the mode's constraint set, not a separate voice selection. Form does not determine mode; mode does not determine voice. But each mode has a natural voice register that is part of its definition.

**Theoretical grounding:** Form maps to Newman's intent dimension (1827). Mode maps to Anker's mode dimension (~1998) and Diátaxis's documentation types (2017). Voice maps to Kinneavy's encoder dimension (1969). Full convergence documented in `docs/content-taxonomy-article-notes.md`.

---

## Directory Structure — Target State

```
write-content/
  SKILL.md
  mandatory-gates.md     ← New — process control (pre-draft gate, third-party review)
  commands/
    write-content.md
  forms/                 ← Form layer
  modes/                 ← Mode layer (new directory)
  voice/                 ← Voice layer (renamed from defaults/)
```

`mandatory-gates.md` sits at the skill root — not in `voice/`, not in `modes/`. It contains mandatory process gates (control flow), not writing guidance.

---

## Forms Layer — `forms/`

### Files that stay (content reviewed, not rewritten)

| File | What stays | What moves out |
|---|---|---|
| `diary.md` | Form definition, frontmatter rules, length, temporal verification | — (diary.md primarily defers to mandatory-rules.md for voice, which is handled by the mandatory-rules.md split) |
| `note.md` | Form definition, sub-types (log/musing/idea), encoder-dominant framing | — |
| `brief.md` | Form definition, structure pattern, format rules | — |
| `news.md` | Form definition, sourcing rules, opinion separation | — |
| `article.md` | Form definition, decoder-dominant framing, multi-part rules, sub-type descriptions | Mode-level sub-sections (tutorial steps, explanation narrative, how-to warnings) move to modes/; form file keeps sub-type descriptions + pointers to mode files. Essay sub-section expands to include structure pattern (see below) |
| `diary-heading-checks.md` | Unchanged | — |
| `diary-retrospective.md` | Unchanged | — |
| `diary-template.md` | Unchanged | — |
| `diary-visual-elements.md` | Unchanged | — |

### Files that dissolve — three-way split

**`essay.md`** — Essay is Argumentation mode applied to Article form. Content splits three ways:

| Content in essay.md | What it is | Destination |
|---|---|---|
| "Structure navigates, prose argues" core principle | Mode mechanics | `modes/argumentation.md` |
| Three appeals (logos, ethos, pathos, priority order, hubris test) | Mode mechanics — argumentation framework | `modes/argumentation.md` |
| "Argumentative, not persuasive" distinction | Mode mechanics | `modes/argumentation.md` |
| Hybrid headings pattern (numbered, colon separator, examples) | Mode mechanics — essay-specific heading behaviour | `modes/argumentation.md` (not `_universal.md`) |
| Prose mechanics (bold lead-ins, counter-args inline, data citations) | Mode mechanics | `modes/argumentation.md` |
| Structure pattern (opening claim → sections → counter-args → limits → closing) | Form structure | `forms/article.md` essay sub-section |
| Multi-part conventions (italic preamble, standalone per part) | Form structure | `forms/article.md` essay sub-section |
| What to avoid | Voice texture | `modes/argumentation.md` voice texture section |
| Journey test for hybrid headings | Structural — already in structure-principles.md §2 | `modes/_universal.md` (with essay/argumentation as canonical example) |

`forms/article.md`'s essay sub-section changes from "See forms/essay.md for full guidance" to "See modes/argumentation.md for mode mechanics" and expands to include the structure pattern and multi-part conventions.

`modes/argumentation.md` gains a third sub-type — essay/sustained — alongside decision and rationale.

### New files

**`technical-documentation.md`** — Multi-mode form for structured technical documents that grow alongside a system and serve as context for LLMs. Covers arc42stories, platform guides, component design docs, onboarding guides maintained alongside a system.

Note: CLAUDE.md files are managed by `update-claude-md` and are NOT in scope for this form.

Contents:
- Form definition: maintained (not published), dual audience (human + LLM), reality-dominant, multi-mode
- Distinguishing test: "Does the subject evolve? If yes → technical documentation. Written once for audience → article."
- Mode map: which mode applies to which section type (arc42stories as canonical example — other docs declare their own)
- Sweet spot principle: defined in `modes/_universal.md` (always loaded) — reference it, do not restate
- The no-content-loss rule: nothing is omitted in restructuring, only relocated
- Multi-mode loading note: write-content targets one section at a time; the mode map is the routing reference
- Dual audience writing rules: explicit guidance on where LLM precision requirements (repetition of context, explicit scope statements, unambiguous verbs) may conflict with human scannability — and how to resolve the tension
- Content migration guide: atomic-fact verification procedure

**Arc42stories mode map (canonical example in `technical-documentation.md`):**

| Section | Mode |
|---|---|
| §8 Crosscutting pointer table | Reference/pointer |
| §8 Anti-patterns | How-to/diagnostic |
| §9.3 "What this delivers" | Explanation/comparative |
| §9.4 Key files | Reference/inventory |
| §9.4 Key wiring | Reference/lookup |
| §9.4 "What it adds" | Explanation/comparative |
| §9.4 Gotchas | How-to/diagnostic |
| §9.4 Pattern to replicate | Tutorial |
| §9.4 Architectural decisions | Argumentation/rationale |
| §10 ADRs | Argumentation/decision |
| §11–12 tables | Reference/lookup |
| §13 Glossary | Reference/lookup |

---

## Modes Layer — `modes/` (new)

### Architecture decision: anti-slop lives in mode files

Per-mode voice guidance moves INTO each mode file as a "Voice texture" section. `voice/anti-slop.md` becomes universal-only (banned words, banned patterns, master instruction). This eliminates the parallel taxonomy (mode file + anti-slop section updated separately) and makes each mode file self-contained.

Per-form voice guidance (Note sub-type voice rules — log/musing/idea; Article/commentary voice; Brief voice; News voice) moves to the respective form files (`forms/note.md`, `forms/article.md`, `forms/brief.md`, `forms/news.md`). This guidance is form-specific, not mode-specific — it describes how a particular form sounds, not how a mode operates.

The "Workflow" section of current `anti-slop.md` ("generate raw → edit ruthlessly"; staged generation; detection test) is process guidance, not voice rules. Detection test is subsumed by Step 7's quality check. "Generate raw → edit ruthlessly" moves to SKILL.md Step 6 as an implementation note. Staged generation is deleted as subsumed.

### Mode files — 6 files

**`_universal.md`** — Loaded first before any specific mode file.

Contents:
- Scannability as the cross-cutting requirement, with form-aware table:

| Form | What scanning gives the reader |
|---|---|
| Brief | The complete picture — scanning IS the experience |
| Note | Enough to know if it's relevant |
| Article | The argument skeleton — enough to decide to read |
| Technical documentation | The fact skeleton — every label is a fact, scanning gives the inventory |
| News | The fact — enough to act on or ignore |

- The sweet spot: label is the fact, body is the reasoning
- One idea per sentence; lead with conclusion; no preamble, no summary
- The AI sensor problem: LLMs default to prose end; mode-first generation is the fix *(intentional rewrite of structure-principles.md §5 — mechanism differs from original)*
- Element selection decision tree (bullets/tables/prose — from structure-principles.md §3)
- Heading test: journey test + position test; never bare structural labels
- Tutorial disambiguation: "Tutorial mode" is the constraint set; "Article/tutorial" is the form sub-type. The same concept at different layers — Article/tutorial always uses tutorial mode; technical-documentation "Pattern to replicate" sections also use tutorial mode.

---

**`explanations.md`** — Two sub-types as sections, with decision rule in preamble.

**Decision rule:**
- Primary: Is the subject a **concept** (timeless, needs a mental model) or a **change** (delta, before/after state)?
  - Concept → discursive
  - Change → comparative
- Confirming test: does the author's experience of arriving at understanding matter? Yes → discursive. No → comparative.
- Length check: if it cannot fit in 2–4 sentences + bullets → probably discursive.
- Edge case: explaining a design decision the author made — if the author's reasoning IS the content → discursive. If the explanation would read the same with a different author → comparative.

**Discursive sub-type:** Author-centric. Personal voice allowed. Analogies from unexpected domains. "I used to think X, but it turns out Y." No length cap. Used by: Article/explanation, diary entries with teaching intent.
Key rules: show the evolution of understanding; reader arrives without a mental model and leaves with one; ends when mental model is complete.

**Comparative sub-type:** System-centric. No personal voice. Before/After contrast as the organising principle. Hard length cap (2–4 sentences + bullets). Used by: Technical documentation "What it adds", design documents, architecture descriptions.
Key rules: lead with Before:/After: contrast; no process narration ("we found", "this led to"); no chaining with dashes; active specific verbs ("displaces", "fires", "opens") not generic ("is designed to", "allows for"); "This" and "It" may not open a sentence.

**Voice texture — discursive:**
Right: personal honesty about uncertainty ("I still don't fully understand why"); analogies from unexpected domains; evolution of understanding visible in the prose.
Wrong: clinical distance, passive voice, "this demonstrates", treating the reader as a stranger.

**Voice texture — comparative:**
Right: specific nouns (class names, file paths, error messages), specific verbs ("displaces", "fires"), explicit Before:/After: contrast, confident claims.
Wrong: "in many ways", "it could be argued", "this is interesting because", gerund openings, passive voice, chained clauses with dashes.

---

**`how-to.md`** — Two sub-types as sections, with decision rule in preamble.

**Decision rule:**
- Primary: What is the reader's starting state?
  - Working state, trying to accomplish a task → procedural
  - Broken or wrong state, trying to recover → diagnostic
- The Symptom → Cause → Fix structure is the diagnostic marker. If a section opens with a symptom → diagnostic, even if fix steps use imperative syntax.
- Procedural ends when the task is accomplished. Diagnostic ends when the broken state is resolved.

**Procedural sub-type:** Steps to accomplish a task from a working state. Assumes some prior knowledge. Used by: Article/how-to, onboarding steps, setup instructions.
Key rules: goal stated clearly upfront; steps in logical order; include warnings and edge cases; "why this step, not that" where non-obvious; ends when task is complete.

**Diagnostic sub-type:** Symptom → Cause → Fix. Reader starts from a broken or wrong state. Used by: Technical documentation Gotchas, anti-patterns sections, troubleshooting guides.
Key rules: Symptom is observable (what appears in logs, tests, UI); Cause is the root mechanism, not the symptom restated; Fix is the exact action, not a direction. No hedging. "Might", "could", "generally" are forbidden in Fix statements.

**Voice texture:**
Right: Symptom names what the reader will actually see. Fix gives the exact command, class name, or configuration change. No softening.
Wrong: "you might see", "this could indicate", "consider doing X".

---

**`reference.md`** — Three sub-types as sections.

**Lookup:** Find a specific term or fact. Glossary, API reference, configuration options. No prose paragraphs; tables or bullet lists only; no explanation of why; no narrative.

**Pointer:** Points to authoritative content elsewhere. Minimal inline content. One-line descriptions of what the reference contains and why to go there. Does not duplicate the referenced content.

**Inventory:** Enumerate what exists with one-line descriptions. Key files lists, crosscutting tables. Each entry answers "what is this and what does it do" not "this file contains X."

**Voice texture (all sub-types):**
Right: dense, telegraphic, specific. File path → em dash → one sentence. Class name → what it does.
Wrong: narrative framing, explaining the reader's journey, contextualising the list.

---

**`argumentation.md`** — Three sub-types as sections.

**Decision sub-type:** ADR format. Context → Decision → Consequences. Records a choice made and why.
Key rules: name the alternative considered; state the tradeoff accepted; name the consequences, including unwanted ones. No hedging the decision.

**Rationale sub-type:** Inline reasoning. Why this approach over the alternatives considered. Shorter, no formal ADR structure.
Key rules: state the alternative explicitly; name the tradeoff accepted. "Why X rather than Y: Z." One paragraph maximum. Does not hedge the conclusion.

**Essay/sustained sub-type:** Extended argument over numbered sections. Opens with a claim, earns it through evidence and counter-arguments, closes without hedging.
Key rules (from essay.md): three appeals priority (logos → ethos → pathos); "argumentative, not persuasive" — evidence and expertise, not emotional appeals; hybrid headings (number + context + theme); bold lead-ins for key claims; counter-arguments addressed inline, not deferred; hubris test (does the conclusion claim more than the evidence supports?).

**Voice texture — decision and rationale:**
Right: direct claim, named alternative, explicit tradeoff, confident conclusion.
Wrong: "one might argue", "it's worth considering", conclusions that hedge ("this approach may have merit").

**Voice texture — essay/sustained:**
Right: strong personal voice carrying the argument; logos-first (evidence and expertise, not credential-listing); one surprising or contrarian point mandated; passion reinforces evidence, never substitutes for it; conclusion states the position directly.
Wrong: appeals to authority without evidence, emotional claims substituting for argument, conclusions that hedge the position, argument that runs parallel to the evidence rather than through it.

---

**`tutorial.md`** — Single sub-type.

Numbered domain-agnostic steps for acquiring a capability. The reader does something and leaves able to do it again.
Used by: Technical documentation "Pattern to replicate" sections, Article/tutorial.

Key rules: steps are imperative sentences; each step is one action; optional "because X" clause when non-obvious; written for zero assumed domain knowledge; include friction points ("I got stuck here because" — for Article/tutorial; omit personal voice for technical documentation); ends when the reader can do the thing.

**Voice texture:**
Right: "Create a module with zero framework imports. Add a `@DefaultBean` baseline service. Because X, place the port interface in the review module, not the app module."
Wrong: vague steps, undocumented pre-conditions, steps that bundle two actions.

---

## Voice Layer — `voice/` (renamed from `defaults/`)

### Files that stay

**`common-voice.md`** — Default fallback voice. Expand with worked examples showing right vs. wrong for each rule. Currently states rules; examples make them actionable.

**`anti-slop.md`** — Updated scope: universal-only. Per-mode guidance moves into mode files; per-form guidance moves into form files. Remaining content: universal banned words, universal structural patterns (no preamble, no trailing summary, no template footers, no "it's important to note"), and the master anti-slop instruction. The "Workflow" process section is deleted as subsumed (detection test → Step 7; generate raw → Step 6 note). Shorter and more stable than current version.

**`mandatory-rules.md`** — Retains: I/we/Claude register rules (the substantive voice guidance), code block rules (two valid reasons only), image rules (diary, article, technical-documentation), content focus rule (omit process/tooling narration unless explicitly requested). Does NOT retain: heading rules (→ `modes/_universal.md`), structure rules (→ `modes/_universal.md`), factual accuracy (→ `mandatory-gates.md`), third-party reference review (→ `mandatory-gates.md`), pre-draft gate (→ `mandatory-gates.md`).

### Files that dissolve

**`structure-principles.md`** — Content distributed:

| Section | Destination |
|---|---|
| §1 Scannability (principle + form table) | `modes/_universal.md` (table updated — Essay row replaced, Technical documentation row added) |
| §2 Heading test | `modes/_universal.md` |
| §3 Element selection | `modes/_universal.md` |
| §4 Encoder/decoder framework | `SKILL.md` Step 1 (form routing theory) |
| §5 Sentence/paragraph rules | `modes/_universal.md` (structural rules); `voice/anti-slop.md` (voice rules) |
| §6 Cross-posting rules | `SKILL.md` Step 1 (form routing) |

### New files

**`mandatory-gates.md`** — At skill root (not in `voice/`). Contains mandatory process control, not writing guidance.

Contents:
- Pre-draft gate: voice classification (I/we/Claude decisions per section), factual accuracy verification (magnitude/duration/count claims verified against git/context), style guide check. Must complete before writing begins.
- Third-party reference review: after drafting, before writing to disk. Scan complete draft; flag every sentence referencing a named person or identifiable group; present each flagged sentence with options (Keep / Rephrase / Delete); wait for author decision. Zero unresolved flags before writing to disk.

---

## SKILL.md — Updated Workflow (7 steps)

### Step 0 — Load voice
Load personal style file if configured (`~/claude-workspace/writing-styles/`); otherwise load `voice/common-voice.md`. Always load `voice/anti-slop.md` and `voice/mandatory-rules.md`.

### Step 1 — Determine form
Use the intent test to classify content type.

**Encoder/decoder theory (routing basis):**
- Note = encoder-dominant (assume shared context, don't over-explain)
- Article = decoder-dominant (cold reader, provide context)
- Brief = reality-dominant (scanning IS the experience)
- Technical documentation = reality-dominant, multi-mode, maintained alongside system

**Intent table additions for technical documentation:**

| Intent | Form |
|---|---|
| "I want to write/update documentation that grows alongside a system" | Technical documentation |
| "I want to document how this component works for developers and Claude" | Technical documentation |
| "I want to write/update arc42stories / design doc / platform guide" | Technical documentation |

**Distinguishing note:** Technical documentation is maintained, not published. If the content will be updated as the system evolves → technical documentation. If written once for an audience → article. When in doubt: does the subject evolve? If yes, technical documentation.

**Cross-posting rules** (from structure-principles.md §6): primary type determination via strip test, intent test, structure test. Format: `primary_type/subtype + secondary_type/subtype`.

### Step 2 — Load form file
Load from `forms/`. For technical-documentation: load `forms/technical-documentation.md` which contains the mode map.

**For technical documentation:** before proceeding to Step 3, identify the target section and its mode from the mode map in `forms/technical-documentation.md`. Mode selection happens here — at form-load time — not mid-generation.

### Step 3 — Determine mode
- For single-mode forms: mode follows from form + sub-type (Article/tutorial → Tutorial mode).
- For technical-documentation: consult the mode map in `forms/technical-documentation.md`. **Write-content targets one section at a time for technical documentation.** The mode map is the routing reference the user consults before invoking write-content; it is not something the model loads to switch modes mid-generation.

### Step 4 — Load mode files
Load `modes/_universal.md` always. Load the specific mode file for the section being written (e.g., `modes/how-to.md` for a Gotchas section, `modes/explanations.md` for a "What it adds" section).

### Step 5 — Pre-draft gate
Load `mandatory-gates.md`. Run before writing:
- Voice classification: **For forms with author participation (diary, article, note, brief, news):** decide I/we/Claude register for this piece. **For technical documentation:** confirm target section, its mode from the mode map, and that the correct mode file is loaded.
- Factual accuracy: verify any duration/count/magnitude claims against git log or context
- Style guide check: confirm personal style guide loaded if author has one

Do not proceed to Step 6 until gate is complete.

### Step 6 — Write
Generate content following: form file (structure, length, what's required), mode file (constraint set, voice texture), voice files (register, anti-slop).

*Implementation note: generate raw, then edit ruthlessly. First pass captures content; editing pass removes AI-naturalized filler, hedging, and false balance.*

### Step 7 — Quality check + third-party review
Quality check:
- Does it scan? (labels give the skeleton; strip them, read only labels — complete factual skeleton with no gaps?)
- Does it apply the correct mode? (Gotcha uses Symptom/Cause/Fix; wiring uses bold lead-in + 1-3 sentences)
- Does it sound human? (no banned words, no AI patterns)
- Does it end when the point is made?

Third-party review (from mandatory-gates.md): scan draft for named persons or identifiable groups; flag each; wait for author decision before writing to disk.

---

## Path Migration

Every reference to old paths in SKILL.md and Skill Chaining sections must be updated:

| Old path | New path | Notes |
|---|---|---|
| `defaults/structure-principles.md` | `modes/_universal.md` | Dissolved — content distributed |
| `defaults/anti-slop.md` | `voice/anti-slop.md` | Directory renamed |
| `defaults/common-voice.md` | `voice/common-voice.md` | Directory renamed |
| `defaults/mandatory-rules.md` | `voice/mandatory-rules.md` + `mandatory-gates.md` | Split |
| `forms/essay.md` | Dissolved | `forms/article.md` essay section + `modes/argumentation.md` |

Implementation checklist item: audit every path reference in SKILL.md (step instructions, Loads section, Skill Chaining bullets) against this table.

---

## Files Changed — Summary

| File | Action | Notes |
|---|---|---|
| `defaults/` directory | Rename to `voice/` | |
| `defaults/structure-principles.md` | Delete — content distributed | See distribution table above |
| `forms/essay.md` | Delete — three-way split | Structure → article.md; mode mechanics → argumentation.md; voice → argumentation.md voice texture |
| `defaults/common-voice.md` | Move to `voice/`; add worked examples | |
| `defaults/anti-slop.md` | Move to `voice/`; scope to universal-only | Per-mode sections move into mode files |
| `defaults/mandatory-rules.md` | Move to `voice/`; remove process gates | Process gates extract to mandatory-gates.md |
| `forms/article.md` | Update | Remove mode-level sub-sections; expand essay sub-section with structure pattern; add pointers to mode files. **Separation principle:** form files retain "what this sub-type is and why you'd choose it"; mode files carry "how to write it." Apply per bullet when deciding what to move. |
| `SKILL.md` | Rewrite workflow (Steps 0–7); add encoder/decoder theory to Step 1; add technical-documentation routing; add path references to mandatory-gates.md | |
| `mandatory-gates.md` | Create at skill root | Pre-draft gate + third-party review |
| `modes/` directory | Create | |
| `modes/_universal.md` | Create | Universal structural rules; updated scannability table |
| `modes/explanations.md` | Create | Discursive + comparative sub-types; decision rule in preamble |
| `modes/how-to.md` | Create | Procedural + diagnostic sub-types; decision rule in preamble |
| `modes/reference.md` | Create | Lookup + pointer + inventory sub-types |
| `modes/argumentation.md` | Create | Decision + rationale + essay/sustained sub-types |
| `modes/tutorial.md` | Create | Single sub-type; disambiguation note re: Article/tutorial naming |
| `forms/technical-documentation.md` | Create | Multi-mode form; arc42stories mode map; migration guide |

---

## Out of Scope

- Arc42stories spec update (writing style section) — separate task; depends on this restructure completing first
- Update-design skill update — separate task; loads from this skill
- Personal voice files in `~/claude-workspace/writing-styles/` — unchanged
- Corpus analysis work — unchanged
