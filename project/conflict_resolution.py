#!/usr/bin/env python3
"""Three-tier conflict resolution for rebase operations.

Tier 1: Auto-resolve lifecycle files (take ours)
Tier 2: LLM semantic resolution (yield ACTION=resolve_conflict)
Tier 3: Human intervention (yield ACTION=user_input)
"""

LIFECYCLE_AUTO_RESOLVE = {
    ".plan", "JOURNAL.md", ".close-progress", ".work-progress",
    ".close-log.jsonl", ".artifacts-promoted", ".close-progress.tmp",
    ".work-progress.tmp", ".execute-progress", ".land-ledger.jsonl",
}


def classify_conflict(conflicted_files: list[str]) -> tuple[list[str], list[str]]:
    auto = [f for f in conflicted_files if f in LIFECYCLE_AUTO_RESOLVE]
    remaining = [f for f in conflicted_files if f not in LIFECYCLE_AUTO_RESOLVE]
    return auto, remaining


def make_rebase_error_handler():
    def handler(step, ctx, result):
        if result.get("ERROR") != "rebase_conflict":
            return None
        files_raw = result.get("CONFLICTED_FILES", "")
        if not files_raw:
            return None
        files = [f.strip() for f in files_raw.split(",") if f.strip()]
        auto, remaining = classify_conflict(files)

        if not remaining:
            return None

        return {
            "ACTION": "resolve_conflict",
            "FILES": ",".join(remaining),
            "AUTO_RESOLVED": ",".join(auto),
            "CONTEXT": "rebase_conflict",
        }
    return handler
