---
id: PP-20261120-39e258
title: "Issue references are always written in full, owner/repo#N, never as a bare number"
type: rule
scope: repo
applies_to: "Queue items and state, pause stack entries, stamps, markers, worklog records, script arguments, commit trailers written by tools or by hand"
severity: important
refs:
  - work-end/close.py
violation_hint: "issue: 289 in a stored field; Refs #570 in a commit message; a function that strips the repository from a reference"
created: 2026-11-20
---

Work spans repositories, workspaces, slots and families, so a bare number does not say which issue it means, and in another repository it links to the wrong one. Every field, file, marker, record and commit trailer carries `owner/repo#N`. Treat a bare number as a defect when writing or reviewing. Known exception being removed: the close stamp writes a bare `Refs #N` only inside the issue's own repository, because some older commit-msg hooks accept nothing else.
