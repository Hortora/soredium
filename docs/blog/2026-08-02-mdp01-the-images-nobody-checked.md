---
layout: post
title: "The images nobody checked"
date: 2026-08-02
type: phase-update
entry_type: note
subtype: diary
projects: [soredium]
tags: [promotion, tooling]
---

The artifact promotion pipeline has been solid since the #148 fixes — specs, blogs, and plans all reach their destination. But markdown files can reference images, and the pipeline only ever collected `.md` files. Any `![](diagram.png)` in a spec or blog entry meant the markdown arrived at the destination and the image didn't.

The fix was reference-based scanning rather than directory-wide collection. After the scanner collects `.md` files per category, a new function — `extract_image_refs` — parses each one for `![](path)` and `<img src="path">` references, resolves relative paths against the markdown file's location, and adds the resolved image paths to the artifact list. The downstream promotion pipeline was already binary-safe (`shutil.copy2` doesn't care about file type), so no changes there.

I considered the simpler approach — broaden the file filter to collect all images in the directory alongside the markdown. But that promotes orphaned images nobody references, and there's no way to know at the destination which images matter. Reference-based scanning is precise: if nothing references it, it doesn't move.

The more interesting discovery came from a side investigation. I had Claude audit both blog sites for broken image references. casehubio.github.io was clean — 207 markdown files, zero images. But mdproctor.github.io turned up 18 genuinely broken references across the site. Sparge user-guide screenshots that had never been copied from the sparge repo. CaseHub architecture SVGs sitting in casehub-poc but never published. A `layered-vs-slices.svg` that existed at `/assets/casehub/` but was referenced with a relative path that resolved to the wrong directory. An `article-java-timeline@2x.png` one directory up from where the `../` prefix pointed.

None of these had been noticed because nobody systematically checks whether image paths resolve. The audit script's regex also produced false positives — it truncated `<img src="/assets/hortara/hortora-blog1-img1-the-loop.png">` to just `/assets/hortara/hortora-blog1-img` and reported it as broken, when the full path was fine. Lesson: HTML attribute parsing with simple regex is fragile enough to mislead your own tooling.

The audit script itself needed filtering. It was reporting 80 "lost" artifacts across all slots, but 53 were false positives in three categories: `proj/` symlink paths (the project repo's specs showing up as workspace artifacts), inherited blog entries appearing on every slot clone (the same entry flagged 8 times because it was committed to workspace main before the slots were created), and files already recovered in the previous session. Three filters — `filter_proj_symlinks`, `filter_inherited` (threshold: 3+ slots), and `filter_already_recovered` — brought the count down to 27 genuine findings.

The pattern here is worth noting: when an audit tool reports a number that seems too high, the right response is to categorise the noise rather than dismiss the tool. The 27 real findings are worth investigating. The 53 false positives are worth filtering so they don't drown the signal next time.
