## D1: Scope — verify AND auto-promote images

**Choice:** Both verification gating and automatic image co-promotion
**Alternatives:**
- Verify only — gates on broken images but doesn't fix them; leaves manual image placement burden on users
**Rationale:** The root cause is images not traveling with .md files during promotion. Verification alone catches the symptom; co-promotion fixes the cause.
**Trade-offs:** Slightly more complex implementation in close_artifacts.py
**Sources:** issue #484 body, verification/repo_checks.py:285 (check_broken_images), work-end/close_artifacts.py
**Exploration:** quick
**Status:** captured

## D2: Architecture — layered promote-then-verify

**Choice:** Co-promote images in close_artifacts.py/artifact_promote.py, verify in close_verify.py, pre-check in publish-blog
**Alternatives:**
- Verify-and-fail-early before promote step — catches problems sooner but doesn't fix them; blocks without co-promoting images
**Rationale:** close_artifacts.py already knows source/destination paths (natural place to add image co-promotion). close_verify.py already runs all verification checks (natural place to add image verification). publish-blog success criteria already list image verification as a requirement.
**Trade-offs:** Two-pass approach (promote + verify) vs single-pass. Acceptable because promote is cheap and verify is already running.
**Sources:** work-end/close_artifacts.py, work-end/close_verify.py, publish-blog/SKILL.md:286
**Exploration:** quick
**Status:** captured

## D3: Image discovery — parse .md refs

**Choice:** Extract image paths by parsing markdown syntax in each .md file during promotion
**Alternatives:**
- Directory scan — copy entire images/ directories alongside .md; simpler but copies unused images
- Both — parse refs + directory scan fallback; overkill for this use case
**Rationale:** Precise — only referenced images travel. Avoids accumulating stray images at destinations. The regex patterns already exist in check_broken_images.
**Trade-offs:** Won't catch images referenced via CSS or JavaScript; acceptable since we're targeting markdown content
**Sources:** verification/repo_checks.py:280-281 (_IMAGE_RE, _HTML_IMG_RE)
**Exploration:** quick
**Status:** captured

## D4: Code location — extract_image_refs in repo_checks.py

**Choice:** New `extract_image_refs(md_file)` function in `verification/repo_checks.py` alongside `check_broken_images()`
**Alternatives:**
- Inline in close_artifacts.py — simpler but duplicates the regex/parsing logic
**Rationale:** Shares `_IMAGE_RE`, `_HTML_IMG_RE`, `_SKIP_IMAGE_REFS` constants with check_broken_images. Single source of truth for image reference parsing. Both check_broken_images and extract_image_refs need the same parsing; factoring extraction out lets check_broken_images call it internally.
**Trade-offs:** Verification module gains a helper that's consumed by promotion code — acceptable cross-module dependency
**Sources:** verification/repo_checks.py:280-283
**Exploration:** quick
**Status:** captured

## D5: Verify severity — warning only

**Choice:** Broken images at the verify step (closing:stamped) are WARN, not ERROR — reported but don't block close
**Alternatives:**
- Blocking (ERROR) — prevents close if any promoted .md has broken image refs; strictest but may block on pre-existing issues in unrelated files
**Rationale:** Co-promotion in the promote step should fix the root cause. Remaining broken refs at verify time are likely pre-existing issues or external resources. Blocking would create friction without proportional safety benefit.
**Trade-offs:** A broken image could ship to a blog destination without being caught as a hard gate. Acceptable because publish-blog has its own pre-copy check that warns interactively.
**Depends on:** D2 (layered architecture — promote fixes, verify catches)
**Sources:** verification/close_verify.py:26-29 (BLOCKING_CATEGORIES)
**Exploration:** quick
**Status:** captured
