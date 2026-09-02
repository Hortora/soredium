#!/bin/bash
# Pre-commit hook: validate .plan queue lines are repo-qualified.
# Install: cp to .git/hooks/pre-commit in workspace repos.

staged=$(git diff --cached --name-only | grep '\.plan$')
[ -z "$staged" ] && exit 0

for f in $staged; do
    bare=$(git show ":$f" | grep -nE '^\s*- \[[ x]\] #[0-9]' | head -1)
    if [ -n "$bare" ]; then
        echo "ERROR: Bare issue number in $f line $(echo "$bare" | cut -d: -f1)"
        echo "  All queue items must use owner/repo#N format."
        echo "  Run: python3 scripts/migrate_plan_repos.py to fix."
        exit 1
    fi
done
exit 0
