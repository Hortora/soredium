# Verify Image References Before Stamp and Publication

**Issue:** soredium#484
**Date:** 2026-11-03

## Problem

Markdown files with broken image references get promoted and published without
verification. Images stranded in workspace/slot directories are never promoted
alongside the .md content. 290 broken image references were found across 238
repos, including 63 on the public casehubio.github.io site.

## Solution

Two-layer approach: **co-promote** images alongside .md files during artifact
promotion (fixes the root cause), then **verify** at stamp time and before
publication (catches stragglers).

## Architecture

### Layer 1: Image extraction (shared utility)

**File:** `verification/repo_checks.py`

New function `extract_image_refs(md_file: Path) -> list[tuple[str, Path]]`
that parses a .md file and returns `(raw_ref, resolved_path)` pairs for all
local image references. Reuses the existing `_IMAGE_RE`, `_HTML_IMG_RE`, and
`_SKIP_IMAGE_REFS` constants. Skips URLs, placeholders, chrome:// refs.

`check_broken_images()` is refactored to call `extract_image_refs()` internally
and filter for non-existent resolved paths — no behavior change, just
deduplication.

### Layer 2: Image co-promotion in artifact_promote.py

When `artifact_promote.py` copies a `.md` file to a destination (via
`to_project()` or `to_workspace_main()`), it also:

1. Calls `extract_image_refs()` on the **source** .md file
2. For each referenced image that exists at the source location, copies it
   to the same relative path at the destination
3. `git add`s the image files alongside the .md

This ensures images travel with their markdown content during work-end
promotion. The import path: `artifact_promote.py` imports
`extract_image_refs` from `verification.repo_checks`.

### Layer 3: Verification gate in close_verify.py

New check `check_promoted_images()` in `verification/close_checks.py`:

- After promotion completes and before stamp, scans promoted .md files at
  their destination paths
- Calls `check_broken_images()` on each promoted .md
- Returns WARN-level findings (not blocking) — co-promotion should have
  fixed the root cause; remaining breaks are pre-existing or external

Added to `_run_branch_checks()` in `close_verify.py`. Runs as part of the
existing `verify` step — no new orchestrator step needed.

### Layer 4: Pre-publish check in publish-blog

Between destination validation (Step 5) and file copy (Step 6) in
`publish-blog/SKILL.md`:

- Call `check_broken_images()` on each entry being published
- If broken refs found, warn with the list and ask to proceed or abort
- When copying entries to destinations, also copy referenced image files
  alongside the .md entries (same `extract_image_refs()` pattern)

## File Changes

| File | Change |
|------|--------|
| `verification/repo_checks.py` | Add `extract_image_refs()`, refactor `check_broken_images()` to use it |
| `work-end/artifact_promote.py` | Import `extract_image_refs`, co-promote images in `to_project()` and `to_workspace_main()` |
| `verification/close_checks.py` | Add `check_promoted_images()` |
| `verification/close_verify.py` | Add image check to `_run_branch_checks()` |
| `publish-blog/SKILL.md` | Add image verification step between Steps 5-6, image co-copy in Step 6 |
| `tests/test_repo_checks.py` (new) | Tests for `extract_image_refs()` and `check_broken_images()` |
| `tests/test_image_promotion.py` (new) | Tests for image co-promotion in artifact_promote |
| `tests/test_close_checks_images.py` (new) | Tests for `check_promoted_images()` |

## Edge Cases

| Case | Behavior |
|------|----------|
| Image ref is a URL (http/https) | Skipped — not a local file reference |
| Image ref uses placeholder (`{thumb_src}`) | Skipped via `_SKIP_IMAGE_REFS` |
| Image ref points outside repo root | Skipped — don't copy files from arbitrary paths |
| Image already exists at destination | Overwrite silently (idempotent) |
| Source .md references image that doesn't exist at source | Skip co-promotion (nothing to copy), verify will report it |
| Jekyll root-relative path (`/assets/img/...`) | Resolved against repo root per existing check_broken_images logic |
| Nested image directory (`images/screenshots/fig1.png`) | Full relative path preserved at destination |
| Same image referenced by multiple .md files | Copied once per promotion (shutil.copy2 is idempotent) |

## Testing Strategy

### Unit tests for extract_image_refs

- Markdown image syntax: `![alt](path)`, `![](path)`, `![alt](path "title")`
- HTML image syntax: `<img src="path">`, `<img src='path'>`
- URL skipping: http, https, data, //
- Placeholder skipping: `x`, `path`, `{thumb_src}`
- Relative path resolution against .md parent
- Root-relative path resolution against repo root
- Non-existent images still returned (extraction, not verification)

### Unit tests for check_broken_images (refactored)

- Existing behavior preserved: returns findings for non-existent images
- No findings for valid image references
- No findings for URL references

### Integration tests for image co-promotion

- .md file with image ref → both .md and image appear at destination
- .md file with missing image → .md promoted, image not (no error)
- Nested image directory structure preserved
- Multiple .md files referencing same image — single copy at destination

### Integration tests for close_verify image check

- All images present → no findings
- Missing image after promotion → WARN finding (not ERROR)

## References

- soredium#484 — this issue
- soredium#483 — image promotion gap (original report)
- `verification/repo_checks.py:280-334` — existing `check_broken_images()` and regex constants
- `work-end/artifact_promote.py` — promotion subcommands
- `work-end/close_artifacts.py` — unified promotion orchestrator
- `verification/close_verify.py` — close-time verification composition
- `publish-blog/SKILL.md:286-288` — existing success criteria for image verification
