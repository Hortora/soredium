# Handler: diary

Write the diary entry for this work with `write-content`, or revise an existing
entry when this work continues its story.

1. Make it worth reading: what was built, why it matters in practice, what it
   changes for someone using it. Inform, educate, advocate.
2. Diagrams are separate `.svg` files, never inline.
3. Complete frontmatter: `entry_type`, `subtype` for a note, and `projects` as the
   full `owner/repo`.
4. Commit it in the workspace. Open it in Typora.
5. Report: `step_done=diary outcome=completed produced=1`
   If nothing in this session is worth an entry: `outcome=skipped`.
