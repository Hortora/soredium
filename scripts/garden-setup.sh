#!/usr/bin/env bash
# garden-setup.sh — One-time sparse blobless clone of the Hortora garden.
#
# Usage: bash garden-setup.sh [garden_url] [target_dir]
# Defaults:
#   garden_url = https://github.com/Hortora/garden.git
#   target_dir = $HORTORA_GARDEN or ~/.hortora/garden

set -euo pipefail

GARDEN_URL="${1:-https://github.com/Hortora/garden.git}"
TARGET_DIR="${2:-${HORTORA_GARDEN:-$HOME/.hortora/garden}}"

if [ -d "$TARGET_DIR/.git" ]; then
  echo "Garden already cloned at $TARGET_DIR"
  echo "To update index files: git -C $TARGET_DIR pull --filter=blob:none"
  exit 0
fi

echo "Cloning garden (blobless, no checkout)..."
git clone --filter=blob:none --no-checkout "$GARDEN_URL" "$TARGET_DIR"
cd "$TARGET_DIR"

echo "Configuring sparse checkout..."
git sparse-checkout init
git sparse-checkout set \
  SCHEMA.md \
  GARDEN.md \
  CHECKED.md \
  "_index/" \
  "_summaries/" \
  "labels/" \
  "*/INDEX.md" \
  "*/README.md"

git checkout main

echo ""
echo "Garden ready at $TARGET_DIR"
echo "Index files materialised. Entry bodies fetched on demand via git cat-file."
echo ""
echo "Session start (fast, fetches index changes only):"
echo "  git -C $TARGET_DIR pull --filter=blob:none"
echo ""
echo "Read an entry body:"
echo "  git -C $TARGET_DIR cat-file blob HEAD:quarkus/cdi/GE-0123.md"
