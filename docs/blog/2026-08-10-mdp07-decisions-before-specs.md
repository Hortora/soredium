---
layout: post
title: "Decisions Before Specs"
date: 2026-08-10
entry_type: note
subtype: diary
projects: [soredium]
tags: [design-review, decision-validation, brainstorming, ordered-dimensions]
---

I've been pasting the same prompt into every brainstorming session for months. Platform coherence checks, boundary rules, capability ownership, architecture docs — a wall of paths that changes per project. Every session, I paste it. Every session, I wonder why the system doesn't just know where to look.

That prompt became the seed for something larger. The real insight wasn't "automate the prompt" — it was noticing that the brainstorming pipeline has a structural gap. We produce specs, then review them. But the *decisions* that shape the spec — the moments where I pick approach A over B and C — those dissolve into conversation history. There's nothing structured to challenge, nothing for the next session to reference.

## The pipeline we built

The old flow was linear: brainstorm → write spec → review spec → plan. Decisions happened during brainstorming but weren't captured. The new flow makes them explicit:

1. **Brainstorming captures decisions as they happen.** Every time 2+ options are presented and I pick one, the choice goes to `decisions.md` with the alternatives, rationale, and trade-offs. Not requirements ("do you need real-time?" — that's a constraint). Not clarifications. Only contested choices where I selected from alternatives.

2. **Decision review validates before the spec is written.** An independent reviewer challenges each decision adversarially — is the rationale sound? Are there alternatives the brainstorm didn't surface? Does this duplicate something the platform already has? This catches problems at the source, before I invest in writing 500 lines of spec prose built on a bad choice.

3. **Three exploration depths.** Quick pick for low-impact choices. Deep analysis (steelman each option, devil's advocate, internet search, first principles) for moderate impact. Multi-agent debate — N advocates arguing for different approaches, a mediator synthesising — for high-stakes decisions. I've been doing the middle tier ad hoc for months, typing "use ultrathink and first principles" every time. Now it's systematic.

4. **Ordered dimensional reviews.** Post-spec review used to run coherence, structure, and robustness in parallel, then cross-cutting. Now they can run sequentially, each dimension seeing prior findings. Structure identifies a boundary issue; coherence checks completeness on both sides of that boundary; robustness probes failure modes at the intersection.

## The ordered review validation

We ran the first ordered review on the spec for this very feature. The numbers told the story:

| Dimension | Issues found |
|-----------|-------------|
| Structure | 12 |
| Coherence | 22 |
| Robustness | 16 |
| Cross-cutting | 5 |

Coherence found nearly twice the issues of structure. Not because the spec had more coherence problems — because coherence could see structure's findings and ask sharper questions. "STR-R1-01 says this boundary is unclear — are the requirements complete on both sides?" That question doesn't exist in parallel mode.

## SOURCES.md

The prompt I kept pasting — boundary rules, capability ownership, architecture docs — became `SOURCES.md`. A per-project file that declares where documentation lives. CLAUDE.md inlines it (always in context), brainstorming references it at decision points ("does this already exist?"), and decision-review's reviewer checks each decision against it for platform coherence.

Different projects have different docs in different places. SOURCES.md replaces hardcoded paths with a discoverable, per-project declaration.

## What's next

Multi-agent debate hasn't been tested live yet — the advocate/mediator pattern is designed but unexercised. The first real use will show whether independent advocates genuinely surface arguments a single Claude session misses, or whether the mediator just picks the recommendation the brainstorming session would have given anyway. I suspect the value is real, based on how much separate subagents catch in design review that a single session doesn't — but the debate pattern adds a layer of structured argumentation on top.

The pipeline state model is designed for drafthouse (casehubio/drafthouse#72) to render visually. Every state transition writes to `pipeline.state` — an external tool can poll it and show where you are in the design process. That's infrastructure waiting for its consumer.
