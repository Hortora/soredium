---
id: PP-20261009-fb0403
title: "Pipeline git operations must use project/git_util.py"
type: rule
scope: repo
applies_to: "Any Python file in work-end/, verification/, or project/ that runs git commands"
severity: important
refs:
  - project/git_util.py
violation_hint: "A file defines `def git(` or `def _git(` locally, or calls subprocess.run(['git', ...]) directly instead of importing from git_util"
created: 2026-10-09
---

All pipeline git operations must import `git` from `project/git_util.py` — never define a local helper or call `subprocess.run(["git", ...])` directly. Thin wrappers that delegate to `git_util.git()` with a different default timeout or return type are acceptable; standalone implementations are not. This prevents the 16-copy divergence that caused a 63% fix ratio in the pipeline (see #423).
