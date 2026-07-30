# Design: cc-praxis README + Landing Page
**Status:** In progress — design phase, not yet in writing-plans  
**Session:** Brainstorm started 2026-06-05, interrupted by implementation work  
**Visual companion mockups:** `/Users/mdproctor/claude/cc-praxis/.superpowers/brainstorm/` (various sessions, latest in `33730-*`)

---

## Strategic context (added 2026-06-17)

### The merge idea
cc-praxis and hortora should merge into a single thing — tentatively still called **hortora**. Currently a casehub developer needs to understand and install:

1. **casehub** — the platform being built
2. **hortora** — the knowledge garden (cross-session technical knowledge)
3. **cc-praxis** — the workflow skills (work-start, wrap, code review, commits, etc.)

That's too many concepts for onboarding. The reframe:

> **cc-praxis + hortora = how I do casehub development at scale**

If cc-praxis is merged into hortora, the story becomes: "install hortora, get everything." The workflow skills (currently cc-praxis) become the "development workflow" module within hortora. The knowledge garden (currently hortora) is the "knowledge" module.

### Implications for the README/landing page design
The design work done so far was for cc-praxis as a standalone. If it merges into hortora:
- The landing page/README we were designing may move to hortora instead
- Or cc-praxis keeps its own public-facing presence but positions itself as the workflow half of hortora
- The workspace model, lifecycle stages, and shell examples remain the same — just the branding/home changes

**Open question:** Is cc-praxis disappearing as a name, or does it become a named module within hortora? This decision affects what the landing page is for.

---

## What we're designing

Surface C (decided): **both** README rewrite AND a separate landing page.

- **README** — workflow-first rewrite. Current README is skill-list-first; should lead with the developer workflow narrative.
- **Landing page** — mdproctor.github.io/cc-praxis or similar. Public-facing discovery page for people who haven't installed Claude Code yet.

---

## Core message

cc-praxis is an **augmented developer workflow** centred on the concept of workspaces.

The two key lifecycle commands are:
- **`work-start`** — begin a branch (explicit command, `work` router is a hidden convenience)
- **`wrap`** (handover skill) — end a session mid-branch OR `work-end` to close the branch entirely

### The workspace model
Every project has two git repos:
- **Project repo** — code, DESIGN.md, ADRs
- **Workspace repo** — context: session handover, design journal, plans, diary, specs

Created automatically the first time `work-start` runs in a new project.

---

## Page structure (agreed)

```
Hero
  → one-line pitch + install command

Two repos, one workflow  (workspace model explanation)
  → diagram: project repo ↔ workspace repo
  → caption: "created automatically the first time you run work-start"
  → copy: TBD (see "workspace copy" section below)

The lifecycle — four stages  (overview A)
  1. work-start — branch, issue, scaffold
  2. Implement — commit loop (auto-triggered skills)
  3. work-end — close branch, promote artifacts
  4. wrap — end session, preserve context

A real session, start to finish  (deep dive C)
  → terminal transcript from work-start to wrap
  → shows what fires automatically at each stage

Below the fold
  → Supported stacks (Java · TypeScript · Python)
  → Superpowers integration
  → Install
  → Project setup
```

---

## Lifecycle (fully designed — see lifecycle diagram)

### Happy path
```
Session opens → project-init (hook, auto)
  ↓
work-start  [user command]
  → Platform coherence + protocol check
  → Issue resolve (issue-workflow)
  → Branch in project + workspace repos
  → Scaffold: .meta, JOURNAL.md, design baseline
  → IntelliJ MCP check
  [superpowers: brainstorming → writing-plans (optional)]

  ⟳ Commit loop (repeats)
    → java-dev / ts-dev / python-dev  [auto: file type]
    [superpowers: TDD + systematic-debugging]
    → code-review (cc-praxis)         [auto: pre-commit, per-language]
    [superpowers: verification-before-completion]
    → git-commit                       [user: links issue, update-design]

  [superpowers: requesting-code-review — once at feature complete]
  ↓
work-end  [user command]
  → Pre-close sweep: forage, protocol, adr, write-content
  → Artifact promotion (blog → workspace, ADRs/specs → project)
  → Journal → DESIGN.md
  → Issue closed, blog published
  → Rebase → main + push
  → EPIC-CLOSED.md
  ↓
wrap  [user command — requires: stack empty + all branches work-ended]
  → update-claude-md
  → Cross-session epic hygiene
  → arc42 full stale scan
  → HANDOFF.md committed to workspace main

  ↩ back to work-start for next issue
```

### Pause/resume (exception path)
`work-pause` → WIP committed + stacked → both repos on main  
`work-resume` → stack picker → rebase onto main → WIP reset  
Must work-end all paused branches before wrap is allowed.

### Two code reviews (both run, complementary)
| | cc-praxis `code-review` | `superpowers:requesting-code-review` |
|--|--|--|
| Trigger | Auto, before every commit | Deliberate, once at feature complete |
| Scope | Per-language quality gate | Full feature review |
| Timing | Throughout commit loop | Before work-end |

---

## Workspace section copy (not yet decided)

Three options proposed. None selected — user to decide in next session.

**Option 1:**  
*"Your project repo has your code. The workspace sits alongside it with the things that don't belong in the codebase — session handover, design journal, plans, diary. Open Claude in the workspace; it loads the project automatically."*

**Option 2 (recommended):**  
*"Two repos. The project repo is for code. The workspace is for Claude — your last handover, the design journal, plans, and the session diary. Commits go to the project; methodology artifacts go to the workspace."*

**Option 3:**  
*"The workspace lives next to your project repo. It holds what Claude needs between sessions: where you left off, what decisions were made, what's planned. Code goes in the project. Everything else goes in the workspace."*

**User feedback on original copy:** "total AI slop" — the previous version used "separates your code from your context / holds everything that makes the work possible / both stay in sync" which was called out as vague filler.

---

## Shell example content (drafted in terminal transcript section)

```
# Session opens — project-init runs silently
⚡ Resuming from handover — 1 open issue, main is clean

$ work-start
⚡ Branch: issue-42-auth-flow  (project + workspace)
📋 Issue #42 — Add OAuth flow · protocols checked
📖 Garden: 2 relevant entries surfaced

# Implementing
→ java-dev loaded (pom.xml detected)
→ superpowers:TDD active

$ commit
→ code-review: no issues
→ update-design: DESIGN.md + JOURNAL.md synced
✅ feat(auth): add OAuth callback  Refs #42

# ... 3 more commits ...

$ work-end
→ superpowers:requesting-code-review: passed
✅ Journal → DESIGN.md · issue #42 closed
✅ Blog published · rebased → main · pushed

$ wrap
✅ Handover committed — next session resumes in one message
```

---

## Design decisions recorded

| Decision | Chosen | Alternatives rejected |
|----------|--------|----------------------|
| Surface | C — README + landing page | A (README only), B (landing page only) |
| Entry point shown | `work-start` (explicit) | `work` router (hidden convenience) |
| Narrative approach | B — lead with workflow directly | A (before/after), C (workspace-as-frame) |
| workspace copy | TBD — pick from 3 options above | Original "AI slop" version |
| `wrap` gate | Hard gate: stack empty + all branches work-ended | Prompt to handle open branches |
| `wrap` content | update-claude-md, epic hygiene, arc42 stale, HANDOFF.md only | Removed items work-end already does |
| Two code reviews | Both shown as complementary | "vs" framing (wrong) |
| `work` router | Hidden — not featured in docs | Shown as primary |

---

## Open questions for next session

1. **Strategic: merge into hortora?** If yes — is this landing page for cc-praxis standalone or for hortora-with-cc-praxis-inside? Does the install story change?
2. **Workspace copy** — pick one of the three options above (or rewrite)
3. **Hero copy** — not drafted yet. One-line pitch needed.
4. **README vs landing page depth** — how much does the README abbreviate vs the landing page?
5. **Superpowers positioning** — shown throughout the lifecycle diagram. Do we explicitly mention superpowers on the landing page or treat it as an optional add-on?

---

## Implementation remaining (after design approved)

- [ ] Design spec approved → writing-plans
- [ ] Write README (workflow-first rewrite)
- [ ] Build landing page (GitHub Pages / Jekyll)
- [ ] Generate shell examples (real commands, real output)
- [ ] Diagrams for workspace model

---

## Visual companion mockups

Server was running at various ports during brainstorm. Latest mockup files at:
```
/Users/mdproctor/claude/cc-praxis/.superpowers/brainstorm/33730-1780895835/content/
  lifecycle-loops.html        ← nested loops diagram
  lifecycle-v6.html           ← final agreed lifecycle (gate before wrap)
  page-structure-v2.html      ← page structure with workspace section
```

To restart: run `start-server.sh --project-dir /Users/mdproctor/claude/cc-praxis` and copy latest html files to new session's content dir.
