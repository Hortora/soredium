---
layout: post
title: "The Skill That Ate Itself"
date: 2026-06-05
type: phase-update
entry_type: note
subtype: diary
projects: [cc-praxis]
tags: [skills, architecture, routers, consolidation]
---

The previous entry ended with 43 skills installed. This one begins with 30. Everything deleted was load we were carrying without knowing it.

The session started from a specific complaint: the command palette was full of skill names that had no business being there. `/java-code-review`, `/java-security-audit`, `/maven-dependency-update` — three separate commands for the same concern, each loading its full language-specific content every time a Java developer tried to review code. In a Python project, the Java rules still loaded. The palette still showed the Java command. The skills were conceptually correct but architecturally naive.

The fix was a routing layer. Each cross-language concern — code review, security audit, dependency management, design doc sync, git commit, project health — becomes a thin router that reads the project type from CLAUDE.md and loads exactly one content file. `code-review/java.md`, `code-review/typescript.md`, `code-review/python.md`. Three files in one directory, none of them discoverable as skills. A Java developer loading `/code-review` never sees Python review rules. They never could.

This matters more than it sounds. Claude Code loads a skill's full SKILL.md when it triggers. Before routers, "install everything" meant every Java review rule, every TypeScript async pattern, every Python mutable-default gotcha arriving in context every time any of them triggered. After routers, only the relevant file loads. The content files aren't skills — no frontmatter, no slash commands, no discovery. They're just markdown that the router reads.

We applied the same pattern to `project-health`, which had accumulated six language sections inline over several sessions. It was 1,228 lines. The router is 260. The Java, TypeScript, Python, skills-repo, blog, and custom sections each live in their own file, loaded on demand. The irony of a project health skill failing its own token-budget check wasn't lost on us.

Then there's what we removed outright. `install-skills`, `uninstall-skills`, the web installer at `scripts/web_installer.py`, the `cc-praxis` UI launcher, `generate_web_app_data.py`, `docs/index.html`. These existed because the original architecture had per-language skills that were genuinely heavy — you didn't want to install Java content in a Python project. Bundles and selective install were real solutions to a real problem. The router pattern dissolved that problem. With routers, "install everything" is the right answer. There is no cross-language waste. The install infrastructure became solutions to a problem that no longer exists.

The one piece of install machinery we archived rather than deleted: `archive/skill-installer-ui` is sitting on GitHub in case the selective-install question comes back. If the skill collection expands into genuinely different domains — content creation, development, specialised tooling — and users want only a slice, the archived code is the starting point. For now it's dead weight that's been set aside rather than discarded.

One deletion had nothing to do with the router work: `smoke-test-mcp-plugin`. It was a skill for building and verifying a specific IntelliJ plugin that lives in a completely different project. It had ended up in cc-praxis at some point for convenience and stayed there, accreting. A sign of how easy it is for a skill collection to become a junk drawer. The skill is still installed on the machine — the other project will take ownership — but cc-praxis no longer pretends to maintain it.

Where it landed: 30 skills, 18 slash commands, a router pattern that scales cleanly to new languages (add a content file, update the dispatch table), and an install story that fits in one sentence.
