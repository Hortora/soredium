# Form: README

A README is a multi-mode document. Different sections serve different purposes
and must be written under different mode constraints. The critical mistake is
applying a single mode (usually Reference/Brief) to the whole document — this
causes explanatory sections to be stripped to tables and loses information that
has no table equivalent.

The rule: **tables replace table-amenable content; prose carries the reasoning
that tables cannot represent.** Do not strip explanatory sections to tables.
Compact them; do not delete them.

**Voice:** Always system-centric throughout. No I/we/Claude register even when a
personal style file is loaded. The personal style applies for energy, directness,
and anti-slop — not for personal register.

---

## Section mode map

Process the README section by section, switching mode as you go:

| Section | Mode | Rules |
|---|---|---|
| **Lead** (one-liner + short paragraph) | Reference / lookup | 1–3 sentences. What it is, what gap it fills. Dense, no padding. No "this is a framework for…" framing — state the thing. |
| **Why it exists / Problem** | Explanation / discursive | 2–5 sentences. Concrete. What breaks or is missing without this. Skip if the lead covers it. |
| **Per-capability explanations** | Explanation / discursive | Bold lead-in per capability. 2–4 sentences each. Explain what it does AND why it matters — the reasoning that has no table equivalent. Do not compress to a single-line table entry if context is needed. |
| **Module / component table** | Reference / inventory | One line per entry. Answers "what is this and what does it do" — not "this file contains X". |
| **Integration / dependency table** | Reference / pointer | One line per entry. Points outward: what it depends on and why. |
| **Configuration / wiring** | Reference / lookup | Telegraphic. Bold lead-in + 1–2 sentences. |
| **Status / epics table** | Reference / inventory | Table only. ✅ / 🔲 or equivalent. |
| **Documentation / tracking links** | Reference / pointer | Flat list. One clause per link: what it covers. |

---

## The stripping trap

When applying anti-slop and Reference mode rules globally, the temptation is to
compress everything to tables. This is wrong for README. The mode map above is
deliberate: per-capability explanations exist because some information cannot be
expressed as a table row without losing the reasoning.

**Test before compressing:** Could a developer who hasn't been in the design
discussions understand *why* this capability matters from the table entry alone?
If no — the prose is load-bearing and must stay, tightened but not removed.

---

## Format rules

- Lead with what the project is; don't build up to it
- Bold lead-ins for per-capability sections (not headings — the section is the heading)
- Tables for module structure, dependencies, status
- No preamble ("this README explains…")
- No summary at the end
- End when the last section ends

---

## What to avoid

- Compressing per-capability explanations to one-line table entries when context is needed
- Prose where a table clearly works (module lists, dependency lists, status)
- Long paragraphs in the lead — compress to 1–3 sentences
- Narrative framing ("In order to understand X, we first need to look at Y…")
- Rhetorical questions
- AI slop patterns (see `voice/anti-slop.md`)
