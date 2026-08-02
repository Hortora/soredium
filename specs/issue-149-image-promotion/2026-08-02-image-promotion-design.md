# Image Promotion for Markdown Artifacts

**Issue:** #149
**Date:** 2026-08-02
**Status:** Approved

## Problem

Markdown files promoted by the artifact pipeline (specs, ADRs, blog entries, plans) may reference images via `![](path)` or `<img src="path">`. The scanner (`workspace_artifacts.scan()`) currently collects only `.md` files (except snapshots). Referenced images are silently left behind during promotion and blog publishing, resulting in broken image links at the destination.

## Approach: Reference-Based Scanning

Parse collected `.md` files for image references and add only the referenced (and existing) image paths to the artifact list. This is precise — no orphaned images are promoted — and requires no changes to the downstream promotion pipeline, which is already binary-safe.

### What Changes

| Component | Change |
|-----------|--------|
| `workspace_artifacts.py` | New `extract_image_refs()` function; `scan()` calls it after collecting `.md` files |
| `blog_dest.py` | Call `extract_image_refs()` on unpublished blog entries; copy images alongside entries |
| `artifact_promote.py` | None — already binary-safe |
| `close_artifacts.py` | None — passes whatever `scan()` returns |
| `blog_publish.py` | None — already binary-safe |

### What Doesn't Change

- Scanner return type: still `dict[str, list[str]]` — image paths are additional entries in each category
- Promotion functions: `shutil.copy2` and `git checkout` handle any file type
- Blog publish `copy-entry`: uses `read_bytes`/`write_bytes` — binary-safe
- `PROMOTED` count: images count as promoted artifacts (correct)
- Routing: images route with their parent markdown's category

## Core Function: `extract_image_refs`

```python
def extract_image_refs(md_path: Path, root: Path) -> list[str]:
    """Extract image paths referenced by a markdown file.
    
    Returns paths relative to root, matching scan() convention.
    Only includes references where the resolved file exists on disk.
    """
```

**Location:** `workspace_artifacts.py` — imported by both scanner and `blog_dest.py`.

**Patterns matched:**
- Markdown: `![...](path)` — regex: `!\[[^\]]*\]\(([^)]+)\)`
- HTML: `<img ... src="path">` — regex: `<img[^>]+src=["']([^"']+)["']`

**Filtered out:**
- External URLs: `http://`, `https://`
- Protocol URIs: `chrome://`, `data:`
- Template variables: paths containing `{` or `}`

**Resolution:**
- Relative paths resolved against the `.md` file's parent directory
- Only paths where the resolved file exists on disk are returned — log a warning for missing refs (not silent)
- Returns paths relative to `root` (the workspace), matching the scanner's convention

## Scanner Integration

After `_scan_dir()` collects `.md` files for a category, iterate over them and call `extract_image_refs()`. Append returned image paths to the category's artifact list, deduplicating (multiple `.md` files may reference the same image). Applies to all markdown categories: specs, adr, blog, plans. Snapshots already use `ext: None` and remain unchanged.

## Blog Publishing Integration

`blog_dest.py` globs `*.md` to find unpublished entries. After identifying unpublished entries, call `extract_image_refs()` on each. Copy referenced images to the blog destination preserving relative structure — if `2026-08-01-entry.md` references `images/diagram.png`, the image lands at `<blog_dest>/images/diagram.png` (same relative path from the entry). Create parent directories as needed. `blog_publish.py` stays unaware of images — `blog_dest.py` handles the copy directly.

## Image Path Handling

Promoted images preserve relative structure. If `specs/issue-42/design.md` references `images/arch.svg`, both `design.md` and `images/arch.svg` are promoted maintaining the same relative path relationship. No markdown content rewriting.

## Tests

### Unit Tests (`test_workspace_artifacts.py`)

| Test | What it verifies |
|------|-----------------|
| `test_image_refs_extracted_from_markdown_syntax` | `![alt](images/photo.png)` adds image to scan results |
| `test_image_refs_extracted_from_html_img_tag` | `<img src="images/photo.png">` same |
| `test_external_urls_excluded` | `http://` and `https://` URLs not collected |
| `test_template_vars_excluded` | `{thumb_src}` not collected |
| `test_missing_image_refs_warned` | Ref in markdown but file missing on disk — skipped with warning logged |
| `test_image_refs_across_all_categories` | Images in specs, adr, blog, plans all collected |
| `test_non_md_files_in_specs_ignored` | Update existing test — non-referenced images still excluded |
| `test_nested_image_paths_preserved` | `images/sub/deep.png` relative structure maintained |

### Unit Tests (`test_blog_dest.py`)

| Test | What it verifies |
|------|-----------------|
| `test_blog_image_copied_to_destination` | Unpublished entry with image ref → image copied alongside entry |
| `test_blog_image_relative_structure_preserved` | `images/photo.png` ref → lands at `<dest>/images/photo.png` |

### Integration Tests (`test_close_artifacts.py`)

| Test | What it verifies |
|------|-----------------|
| `test_image_promoted_alongside_markdown` | End-to-end: markdown with image ref → both promoted |
| `test_blog_image_promoted_to_blog_dest` | Blog entry with image → image lands at blog destination |

### Out of Scope

- Image content validity — we copy bytes, not interpret them
- Duplicate image refs across multiple markdown files — `shutil.copy2` overwrites idempotently
