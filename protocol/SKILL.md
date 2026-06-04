---
name: protocol
description: >
  Use when working with project-level protocol files — project-specific rules, architectural
  constraints, and conventions that apply within a single project. Session-time operations:
  CAPTURE (create a new protocol entry), SWEEP (scan session for rules worth formalising),
  SEARCH (find protocols by keyword), HEALTH (validate schema completeness and ref integrity).
  DEEP-SCAN is stubbed — requires Hortora audits 1–4 to implement. NOT for universal technical
  knowledge (use forage for that). NOT for architectural decisions (use adr).
---

# Protocol — Project-Level Rule Operations

## What Protocols Are

Standing architectural rules, design patterns, and conventions that keep a project or
platform coherent. A protocol answers "how do we do this consistently?" — not "how do
I avoid this library gotcha?" Protocols are hypotheses, not dogma: test them against
the problem at hand; update them when they don't fit.

**Not a protocol:**
- Universal technical gotcha → use `forage`
- One-off architectural decision → use `adr`
- Rule that only applies in one file → use an inline comment

**Garden techniques as upstream sources:**
A garden technique is a candidate for promotion to a protocol. The difference:
- **Technique** (garden/forage): "this works and most developers wouldn't reach for it" — descriptive, universal, optional
- **Protocol**: "we have evaluated this and committed to applying it consistently here" — prescriptive, project-specific, enforced

Not every technique becomes a protocol. Situational or context-dependent knowledge stays as a technique. Techniques that have been validated in the project and need consistent enforcement become protocols.

When a protocol is derived from a garden technique, record the upstream link in both directions:
- Set `garden_ref` in the protocol frontmatter to the GE-ID of the technique
- Add `protocol: "PP-ID"` to the garden entry via forage REVISE (`protocol-link` kind)

A protocol without a garden technique backing it is a rule with no rationale — fragile, because nobody knows why it exists. A technique without a protocol is available but optional.

---

## Standard Protocol Structure — Three-Tier Model

Protocols are organised in three tiers. Every project using this skill should have this structure under `$PROTOCOLS_DIR/`:

```
protocols/
├── INDEX.md                  ← navigation hub; quick-ref tables pointing into sub-indexes
├── universal/
│   ├── INDEX.md              ← rules applicable to any project using this tech stack
│   └── <slug>.md
├── <platform>/               ← named after this platform/product (e.g. quarkus/, casehub/)
│   ├── INDEX.md              ← rules specific to this platform's architecture
│   └── <slug>.md
└── <domain>/                 ← topic area within the platform (e.g. agentic/, upstream/, cdi/)
    ├── INDEX.md              ← optional; use when domain has 4+ rules
    └── <slug>.md
```

**Scope maps to tier:**

| `scope` value | Tier | Where to write |
|---------------|------|----------------|
| `universal` | Universal — any project using this tech stack | `universal/<slug>.md` |
| `platform` | Platform — this platform's foundational rules | `<platform>/<slug>.md` |
| `repo` | Repo-specific rules for one module/repo | `<domain>/<slug>.md` |
| `application` | App-tier rules (apps built on this platform) | `application/<slug>.md` or `<domain>/<slug>.md` |

**Index table format — always three columns:**

```markdown
| File | Rule Summary | Applies To |
|------|-------------|------------|
| [slug.md](slug.md) | One-line directive | Which modules / when |
```

The "Applies To" column is the most important — it tells the reader exactly when to check this rule without having to open the file.

**Top-level `INDEX.md` is a navigation hub**, not a full listing. It contains quick-reference rows (5–10 per tier) pointing at the sub-indexes for the full listing. New sessions read `INDEX.md` first to orient; they navigate to sub-indexes for depth.

---

## Protocol Entry Format

```yaml
---
id: PP-YYYYMMDD-xxxxxx
title: "Short directive title"
type: principle | rule
scope: platform | repo
applies_to: "which modules / contexts"
severity: critical | important | guidance
refs:
  - path/to/relevant/doc.md
violation_hint: "optional — what a violation looks like"
garden_ref: "GE-YYYYMMDD-xxxxxx"  # optional — GE-ID of the garden technique this protocol was derived from
created: YYYY-MM-DD
---

One paragraph. The directive. Minimum context to understand why.
No implementation detail — refs: covers that.
```

**type:**
- `rule` — has a concrete, specific prescription, often with an example needed to follow it
- `principle` — directional guidance; references out to detail, no example in the body

**severity:**
- `critical` — violations cause bugs, build failures, or data corruption
- `important` — violations cause problems; workarounds possible but costly
- `guidance` — best practice; violations are technical debt

---

## Locating the Protocols Directory

Before any operation, resolve the protocols path:

```bash
# Find project root
PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)

# Protocols directory
PROTOCOLS_DIR="$PROJECT_ROOT/docs/protocols"
```

If `docs/protocols/` does not exist at the project root, check whether the current
project uses a parent-repo layout (`parent/docs/protocols/`). If still not found,
ask the user to confirm the path before proceeding.

---

## Workflows

### CAPTURE (create a new protocol entry)

Use when: a rule or principle should be formalised as a reusable project protocol.
The user provides the directive; CAPTURE scaffolds and writes the entry.

**Step 1 — Generate ID**

```bash
PP_ID="PP-$(date +%Y%m%d)-$(python3 -c "import secrets; print(secrets.token_hex(3))")"
```

**Step 2 — Derive fields**

Work from what's already known in context. Ask only for what's genuinely unclear.

| Field | Derive from |
|-------|-------------|
| `title` | The directive itself — imperative, one line |
| `type` | `rule` if a concrete prescription; `principle` if directional |
| `scope` | `universal` if any Java/Quarkus project benefits; `platform` if specific to this platform's foundation; `repo` if one repo within the platform; `application` if for apps built on this platform |
| `applies_to` | Which modules, contexts, or conditions trigger this rule |
| `severity` | `critical` if violations cause bugs; `important` if costly; `guidance` otherwise |
| `refs` | Any design docs or related protocols mentioned in context |
| `violation_hint` | What a violation looks like — derive from the problem description |
| `garden_ref` | If the rule was distilled from a known garden technique, note its GE-ID. After writing the protocol, offer to add `protocol: "PP-ID"` to the garden entry via forage REVISE (protocol-link kind). |

**Step 3 — Choose a filename**

Derive a descriptive kebab-case slug from the title, e.g.:
`"Use OCC + explicit counters..."` → `occ-threshold-counters.md`

Check for filename conflicts in the protocols directory before writing.

**Step 4 — Draft and confirm**

Draft the full entry (frontmatter + one-paragraph body). Show it to the user:
> "Does this capture the rule accurately?"

Wait for confirmation before writing.

**Step 5 — Write the entry file**

Route to the correct tier directory based on `scope` (see Three-Tier Model above):
- `universal` → `$PROTOCOLS_DIR/universal/<slug>.md`
- `platform` → `$PROTOCOLS_DIR/<platform-name>/<slug>.md` (use the platform's name, e.g. `quarkus/`, `casehub/`)
- `repo` or domain-specific → `$PROTOCOLS_DIR/<domain>/<slug>.md`

Create the subdirectory if needed.

**Step 6 — Commit**

```bash
PROTOCOLS_GIT_ROOT=$(git -C "$PROTOCOLS_DIR" rev-parse --show-toplevel)
git -C "$PROTOCOLS_GIT_ROOT" add <relative-path-to-entry>
git -C "$PROTOCOLS_GIT_ROOT" commit -m "protocol(PP-YYYYMMDD-xxxxxx): <slug>"
```

**Step 7 — Update the indexes**

Two updates required:

**7a — Sub-index** (`$PROTOCOLS_DIR/<tier>/INDEX.md`): add a row in the three-column table,
creating the sub-index file if this is the first entry in this tier:

```markdown
| File | Rule Summary | Applies To |
|------|-------------|------------|
| [slug.md](slug.md) | One-line directive | Which modules / when |
```

**7b — Top-level navigation hub** (`$PROTOCOLS_DIR/INDEX.md`): add a quick-reference row
under the relevant tier section (5–10 rows per section max; link to sub-index for the full list).
If this is the first rule in a tier, create the section header and add a link to the sub-index.

Commit both index updates in the same commit as the protocol file.

**Step 8 — Report**

Tell the user the protocol ID, filename, and that it was committed.

---

### SWEEP (scan session for rules worth formalising)

Use at the end of a session or when triggered by handover. Reviews the conversation
for patterns and constraints that should become protocols. Unlike forage SWEEP
(which finds universal technical knowledge), protocol SWEEP finds project-specific
rules that recurred or were enforced informally.

**Step 1 — Scan for implicit rules**

Review the session for:
- "We should always..." or "never..." statements about this project
- Constraints enforced more than once (same rule applied to different files)
- Workarounds that became de facto policy
- Patterns copied across modules without a written source of truth

For each candidate, propose explicitly:
> "We established that [X] — this looks like a standing rule worth formalising as a protocol. Worth capturing?"

**Step 2 — Scan for rule violations discovered**

Review the session for cases where an existing protocol was violated:
- A file was found that broke a rule, was corrected, and the rule re-confirmed
- A new module was set up and had to be taught the same constraint as existing modules

For each: check if the violation_hint on the existing protocol is clear enough.
If not, offer to enrich it via the existing entry.

**Step 3 — Submit confirmed entries**

For each confirmed entry, run CAPTURE Steps 1–8 from context. Do NOT ask the user
to re-describe rules already established in the session.

**Step 4 — Report**

Tell the user: N candidates found, M confirmed and committed. If nothing surfaced:
"No new protocol candidates found in this session."

---

### SEARCH (find protocols by keyword)

Use when: looking for existing rules before writing new code, or when checking
whether a constraint is already formalised.

**Step 1 — Resolve path and search**

```bash
PROJECT_ROOT=$(git rev-parse --show-toplevel)
PROTOCOLS_DIR="$PROJECT_ROOT/docs/protocols"

# Search title, applies_to, violation_hint in all protocol files
grep -rli "<keyword>" "$PROTOCOLS_DIR" --include="*.md" | grep -v INDEX | grep -v PENDING
```

**Step 2 — For each match, extract and show the frontmatter**

```bash
# Show frontmatter + first paragraph of body for context
head -20 "$PROTOCOLS_DIR/<match>.md"
```

**Step 3 — Return matches**

Present each matching protocol as:
> **PP-YYYYMMDD-xxxxxx** — `<title>`
> Applies to: `<applies_to>` | Severity: `<severity>`
> `<violation_hint>` (if present)

If no matches: "No protocol found for '<keyword>' in this project."

---

### HEALTH (validate schema completeness and ref integrity)

Use when: checking the state of the protocols directory before adding new entries,
or as a periodic sanity check.

**Step 1 — Count entries**

```bash
PROJECT_ROOT=$(git rev-parse --show-toplevel)
ls "$PROJECT_ROOT/docs/protocols/"*.md | grep -v INDEX | grep -v PENDING | wc -l
```

**Step 2 — Check required fields**

For each protocol file, verify YAML frontmatter contains all required fields:
`id`, `title`, `type`, `scope`, `applies_to`, `severity`, `created`.

```python
import pathlib, yaml

REQUIRED = {"id", "title", "type", "scope", "applies_to", "severity", "created"}
VALID_TYPES = {"rule", "principle"}
VALID_SCOPES = {"universal", "platform", "repo", "application"}
VALID_SEVERITIES = {"critical", "important", "guidance"}

protocols_dir = pathlib.Path("docs/protocols")
issues = []

for f in sorted(protocols_dir.glob("*.md")):
    if f.name in ("INDEX.md", "PENDING-MODULE-UPDATES.md"):
        continue
    text = f.read_text()
    if not text.startswith("---"):
        issues.append(f"{f.name}: no YAML frontmatter")
        continue
    parts = text.split("---", 2)
    try:
        fm = yaml.safe_load(parts[1])
    except Exception as e:
        issues.append(f"{f.name}: invalid YAML — {e}")
        continue
    missing = REQUIRED - set(fm.keys())
    if missing:
        issues.append(f"{f.name}: missing fields — {', '.join(sorted(missing))}")
    if fm.get("type") not in VALID_TYPES:
        issues.append(f"{f.name}: invalid type '{fm.get('type')}' (expected: rule, principle)")
    if fm.get("scope") not in VALID_SCOPES:
        issues.append(f"{f.name}: invalid scope '{fm.get('scope')}' (expected: platform, repo)")
    if fm.get("severity") not in VALID_SEVERITIES:
        issues.append(f"{f.name}: invalid severity '{fm.get('severity')}' (expected: critical, important, guidance)")

print(f"\nTotal: {count} protocols")
if issues:
    print(f"Issues ({len(issues)}):")
    for i in issues:
        print(f"  ⚠️  {i}")
else:
    print("✅ All protocols pass schema validation")
```

**Step 3 — Check ref integrity**

For each `refs:` entry in any protocol, verify the referenced file exists:

```bash
# For each ref path in each protocol, check existence
```

Report broken refs as:
> ⚠️ `<protocol-file>` refs `<ref-path>` — file not found

**Step 4 — Report**

```
HEALTH report — docs/protocols/
  Total entries:   N
  Schema valid:    N (or: M issues found)
  Broken refs:     N (or: none)
```

---

### DEEP-SCAN (not yet implemented)

DEEP-SCAN will perform gap analysis, relevance classification, and violation detection
across the protocol layer. It requires the four audits from the Hortora methodology
design to complete first — particularly Audit 2 (convention split: universal vs
casehub-specific) and Audit 3 (folder structure validation).

> **Not yet implemented** — DEEP-SCAN requires Audits 1–4 from
> `spec/docs/design/2026-05-05-hortora-project-knowledge-methodology.md`
> to validate the folder structure and content classification assumptions
> before gap detection can be built. Stub this operation until the audits complete.

---

## Common Pitfalls

| Mistake | Why It's Wrong | Fix |
|---------|----------------|-----|
| Capturing a universal gotcha as a protocol | Protocols are project-specific | If it applies outside this project, use forage instead |
| Capturing an ADR as a protocol | ADRs are one-off decisions; protocols are standing rules | Use `adr` skill for architectural decision records |
| Leaving refs pointing to non-existent files | HEALTH will flag these; context for future sessions is broken | Run HEALTH and fix broken refs before committing |
| Not updating the correct index after CAPTURE | Index is the fast-path for SEARCH | Update both the tier sub-index AND the top-level navigation hub (see Three-Tier Model) |
| Writing implementation detail in the protocol body | Protocols are directives, not tutorials | refs: out to design docs; keep body to one paragraph |
| Using type=rule for a high-level principle | Misleads readers about expected specificity | `principle` for directional; `rule` for specific + example |

---

## Success Criteria

CAPTURE is complete when:
- ✅ PP-ID generated (`PP-YYYYMMDD-xxxxxx` format)
- ✅ Entry file written to the correct tier subdirectory under `$PROTOCOLS_DIR` (see Three-Tier Model)
- ✅ User confirmed the draft before writing
- ✅ Entry committed to the protocols repo
- ✅ Sub-index (`<tier>/INDEX.md`) updated with three-column row
- ✅ Top-level `INDEX.md` navigation hub updated with quick-reference row

SWEEP is complete when:
- ✅ Session reviewed for implicit rules and re-enforced constraints
- ✅ Each candidate proposed explicitly before capturing
- ✅ Confirmed entries written via CAPTURE and committed
- ✅ Report given: N candidates found, M captured

SEARCH is complete when:
- ✅ All protocol files searched for the keyword
- ✅ Matching entries returned with id, title, applies_to, severity, and violation_hint

HEALTH is complete when:
- ✅ All files checked for required YAML frontmatter fields
- ✅ type, scope, severity validated against allowed values
- ✅ All refs checked for file existence
- ✅ Summary report given

---

## Skill Chaining

**Invoked by:**
- User directly ("protocol CAPTURE", "add a protocol", "protocol SEARCH", "protocol HEALTH")
- `handover` — protocol SWEEP is added to the wrap checklist alongside forage sweep

**Complements:**
- `forage` — garden techniques are the upstream source for protocol decisions. When a protocol is derived from a technique, link back via `garden_ref` in the protocol frontmatter and add `protocol: "PP-ID"` to the garden entry via forage REVISE (protocol-link kind).
- `adr` — one-off architectural decisions; protocol handles recurring standing rules

**Does NOT handle:**
- Universal garden entries (use `forage`)
- Architectural decision records (use `adr`)
- Content classification or gap analysis (DEEP-SCAN — not yet implemented)

**Protocols location:** `<project-root>/docs/protocols/`
