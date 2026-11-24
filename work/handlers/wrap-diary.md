# Handler: diary

**The default is to write an entry.** Every session that did real work gets a
diary entry. The only exception is truly trivial chore work — a typo fix, a
config tweak, a one-line rename with no design reasoning. Even then, explain
why you recommend skipping and let the user decide.

Write the diary entry for this work with `write-content`, or revise an existing
entry when this work continues its story.

1. Make it worth reading: what was built, why it matters in practice, what it
   changes for someone using it. Inform, educate, advocate.
2. **At least one SVG diagram** illustrating the work — before/after, component
   interaction, decision flow, state machine, or layer diagram. Save as
   separate `.svg` files in `images/` alongside the entry, never inline. This
   is mandatory: an entry without a diagram is incomplete.
3. Complete frontmatter: `entry_type`, `subtype` for a note, and `projects` as the
   full `owner/repo`.
4. Commit it in the workspace. Open it in Typora.
5. Report: `step_done=diary outcome=completed produced=1`

**Diagram gate:** Before reporting `outcome=completed`, verify the entry
references at least one `.svg` file and that file exists on disk. If no
diagram was created, do not report complete — create one first.

**To skip:** only when the session was trivial chore work. Present the
recommendation to skip with the reason, and wait for the user to confirm
before reporting `outcome=skipped`.
