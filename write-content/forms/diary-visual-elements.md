# Visual Elements Reference

Used by diary form Step 3–4. Visual content makes posts readable and credible.

---

## SVG Diagrams (mandatory)

**Eagerly look for every opportunity to include SVG diagrams.** This is
the primary visual element — not an optional enhancement. Claude generates
the SVG directly; no external tools needed. Don't stop at one: scan every
section of the entry and draw a diagram wherever structure would be
clearer shown than told. Most entries should have two or more.

**What to diagram** (actively look for all of these):

| Type | When to use | Example |
|------|-------------|---------|
| Before/after | Architecture or data flow changed | Old pipeline → new pipeline |
| Component interaction | Multiple parts working together | Service A calls B via C |
| Decision flow | Alternatives were weighed | Three options, one chosen |
| State machine | Lifecycle states and transitions | Queue item: open → active → done → closed |
| Layer diagram | Where new code sits in the stack | Handler → pipeline → script → git |

**How to create:**

1. Write the SVG content — keep it clean and readable:
   - Use `viewBox` for responsive sizing
   - Use readable fonts (`font-family: system-ui, sans-serif`)
   - Keep colours minimal — two or three, with good contrast
   - Label every element — no unlabelled boxes or arrows
2. Save to `images/<entry-slug>-<description>.svg` alongside the entry
3. Reference with `![Description](images/<filename>.svg)`

**Style:**
- Prefer horizontal flow (left to right) for sequences
- Prefer vertical flow (top to bottom) for hierarchies
- Use rounded rectangles for components, arrows for flow
- Include a brief title or caption in the diagram itself
- Keep it simple — if it needs more than ~15 elements, split into two diagrams

---

## Code Blocks

Show the actual code that matters. Not a summary, not a reference to a file — the
real snippet. If the logic is interesting, show it. Short is better; extract the
5–10 lines that tell the story.

---

## Illustrations

Small images that give the post additional visual interest. Sources:
- Web search for a relevant diagram, photo, or graphic (`WebSearch` + `WebFetch`)
- AI-generated illustration for the specific concept (note source in alt text)

Save to `blog/images/<YYYY-MM-DD-slug-description>.png` and reference as:

```markdown
![alt text describing the image](images/YYYY-MM-DD-slug-description.png)
```

Illustrations are supplementary — they add variety but do not replace the
mandatory SVG diagram requirement.

---

## Screenshots

**Mandatory for any UI work.**

- Clip to the relevant component or area — full-page screenshots create scroll and lose focus
- If multiple states matter (before/after, hover, error), include both clipped side by side or sequentially
- The user provides the screenshot file; save to `blog/images/` alongside the entry
- Reference with descriptive alt text: `![The skill chain graph showing bidirectional links](images/...)` not `![screenshot]`

**If a section covers UI work and has no screenshot, the entry is incomplete.**
