#!/usr/bin/env python3
"""
Audit all archived slots for unmerged branches in non-primary repos.

Scans .slot files to find multi-repo slots, then checks each repo's
original clone to verify the slot branch was merged to main and stamped.

Accounts for stamp commits: a stamped branch with 1 unmerged commit where
that commit IS the stamp is expected behaviour — the stamp never goes to
main. Only flags genuinely unmerged work.

Usage:
    python3 scripts/audit_slot_merges.py <family-root>
    python3 scripts/audit_slot_merges.py <family-root> --all    # include single-repo
    python3 scripts/audit_slot_merges.py <family-root> --verbose # show all slots
    python3 scripts/audit_slot_merges.py <family-root> --all --fix  # stamp UNSTAMPED branches
"""

import re
import subprocess
import sys
from pathlib import Path


def parse_slot(slot_path: Path) -> tuple[int | None, str | None, list[str], str | None]:
    text = slot_path.read_text()
    m = re.search(r"# Slot (\d+)", text)
    slot_num = int(m.group(1)) if m else None
    m = re.search(r"branch:\s*(\S+)", text)
    branch = m.group(1) if m else None

    repos: list[str] = []
    primary = None
    in_repos = False
    for line in text.splitlines():
        if line.strip() == "## Repos":
            in_repos = True
            continue
        if in_repos:
            if line.startswith("##"):
                break
            rm = re.match(r"-\s+(\S+)", line.strip())
            if rm:
                repo_name = rm.group(1)
                repos.append(repo_name)
                if "(primary)" in line:
                    primary = repo_name
    return slot_num, branch, repos, primary


def git(repo_path: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo_path)] + list(args),
        capture_output=True, text=True, timeout=10,
    )
    return r.stdout.strip()


def check_repo_branch(repo_path: Path, branch: str) -> dict:
    result: dict = {}
    if not repo_path.exists():
        result["exists"] = False
        return result
    result["exists"] = True

    branches = git(repo_path, "branch", "--list", branch)
    result["branch_exists"] = bool(branches)
    if not result["branch_exists"]:
        result["branch_deleted"] = True
        return result

    unmerged_raw = git(repo_path, "log", "--oneline", f"main..{branch}")
    unmerged_lines = unmerged_raw.splitlines() if unmerged_raw else []
    result["unmerged_count"] = len(unmerged_lines)
    result["unmerged_commits"] = unmerged_raw

    last_msg = git(repo_path, "log", "-1", "--format=%s", branch)
    result["last_commit_msg"] = last_msg
    result["is_stamped"] = last_msg.startswith("chore: branch closed")

    # Check if the only unmerged commit is the stamp itself
    if result["is_stamped"] and result["unmerged_count"] >= 1:
        # The stamp is always the last commit. Check if it's the ONLY unmerged one.
        if result["unmerged_count"] == 1:
            result["stamp_only"] = True
        else:
            result["stamp_only"] = False
            # Real unmerged count is total minus the stamp
            result["real_unmerged_count"] = result["unmerged_count"] - 1

    # For new-format stamps, extract and verify landing SHA
    sha_match = re.search(r"landed as ([0-9a-f]+)", last_msg)
    if sha_match:
        landing_sha = sha_match.group(1)
        result["landing_sha"] = landing_sha
        # Check if stamp references a different repo
        repo_match = re.search(r"on (\S+) main", last_msg)
        if repo_match and repo_match.group(1) != "main":
            result["cross_repo_landing"] = repo_match.group(1)
            result["landing_verified"] = True  # trust cross-repo stamps
        else:
            r = subprocess.run(
                ["git", "-C", str(repo_path), "merge-base", "--is-ancestor",
                 landing_sha, "main"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                result["landing_verified"] = True
            else:
                # SHA might have changed due to rebase — check by commit message
                second_to_last = git(repo_path, "log", "-1", "--skip=1",
                                     "--format=%s", branch) if result["unmerged_count"] > 1 else ""
                if second_to_last:
                    content_check = git(repo_path, "log", "--oneline",
                                       f"--grep={second_to_last[:40]}", "main")
                    result["landing_verified"] = bool(content_check)
                    if content_check:
                        result["landing_via_content"] = content_check.split()[0]
                else:
                    result["landing_verified"] = False

    # Check for "superseded" stamps — intentionally not merged
    if "superseded" in last_msg.lower():
        result["superseded"] = True

    return result


def find_slot_dirs(family_root: Path) -> list[tuple[Path, str]]:
    dirs: list[tuple[Path, str]] = []
    for loc_name, label in [
        ("worktrees/attic", "archived"),
        ("slots/attic", "archived"),
        ("worktrees", "active"),
        ("slots", "active"),
    ]:
        base = family_root / loc_name
        if not base.exists():
            continue
        for d in base.iterdir():
            if not d.is_dir() or d.name == "attic":
                continue
            if (d / ".slot").exists():
                dirs.append((d, label))
            else:
                for sub in d.iterdir():
                    if sub.is_dir() and (sub / ".slot").exists():
                        dirs.append((sub, label))
    return dirs


def classify_status(info: dict) -> str:
    """Classify a repo's branch status.

    Returns:
        OK — properly merged and stamped (or stamp-only)
        BRANCH_DELETED — branch no longer exists
        MISSING_REPO — repo not found on disk
        UNSTAMPED — merged but missing stamp commit
        SUPERSEDED — intentionally abandoned in favour of another branch
        LANDED_VERIFIED — stamp has landing SHA confirmed on main; pre-rebase
            commits expected to differ
        UNMERGED(N) — N real commits not on main, no evidence of landing
    """
    if not info.get("exists"):
        return "MISSING_REPO"
    if info.get("branch_deleted") or not info.get("branch_exists"):
        return "BRANCH_DELETED"
    if info.get("superseded"):
        return "SUPERSEDED"
    if info.get("stamp_only"):
        return "OK"
    if info.get("is_stamped") and info.get("landing_verified"):
        return "LANDED_VERIFIED"
    if info.get("unmerged_count", 0) == 0:
        if info.get("is_stamped"):
            return "OK"
        return "UNSTAMPED"
    # Stamped with old format (no landing SHA) — can't verify programmatically
    # but stamp implies work was landed via rebase (pre-rebase commits differ)
    if info.get("is_stamped") and not info.get("landing_sha"):
        return "STAMPED_OLD_FORMAT"
    # Stamped with landing SHA but SHA not on main — possible data loss
    if info.get("is_stamped") and info.get("landing_sha") and not info.get("landing_verified"):
        real = info.get("real_unmerged_count", info["unmerged_count"])
        return f"LANDING_FAILED({real})"
    if info.get("is_stamped"):
        real = info.get("real_unmerged_count", info["unmerged_count"])
        return f"UNMERGED({real})"
    return f"UNMERGED({info['unmerged_count']})"


def find_landing_sha(repo_path: Path, branch: str) -> str | None:
    """Find the SHA on main that corresponds to the branch's content.

    Strategy 1: If branch commits are ancestors of main (ff-merge), use
    the branch tip SHA directly.
    Strategy 2: Search main for commits with matching subjects (squash-merge).
    """
    r = subprocess.run(
        ["git", "-C", str(repo_path), "merge-base", "--is-ancestor",
         branch, "main"],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode == 0:
        return git(repo_path, "rev-parse", branch)

    unmerged_raw = git(repo_path, "log", "--oneline", f"main..{branch}")
    if not unmerged_raw:
        return git(repo_path, "rev-parse", "main")

    for line in unmerged_raw.splitlines():
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue
        subject = parts[1]
        if subject.startswith("chore: branch closed"):
            continue
        match = git(repo_path, "log", "--oneline", "-1",
                     f"--grep={subject[:50]}", "main")
        if match:
            return match.split()[0]
    return None


def fix_unstamped(repo_path: Path, branch: str) -> str:
    """Attempt to stamp an UNSTAMPED branch. Returns disposition string."""
    landing_sha = find_landing_sha(repo_path, branch)
    if not landing_sha:
        return "SKIP_NO_LANDING_SHA"

    r = subprocess.run(
        ["git", "-C", str(repo_path), "checkout", branch],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode != 0:
        return f"SKIP_CHECKOUT_FAILED"

    stamp_msg = (
        f"chore: branch closed — landed as {landing_sha} on main\n\n"
        f"  no-issue: retroactive stamp from slot audit"
    )
    r = subprocess.run(
        ["git", "-C", str(repo_path), "commit", "--allow-empty", "-m", stamp_msg],
        capture_output=True, text=True, timeout=10,
    )
    _git_checkout_main(repo_path)

    if r.returncode != 0:
        return "SKIP_COMMIT_FAILED"
    return "STAMPED"


def _git_checkout_main(repo_path: Path) -> None:
    subprocess.run(
        ["git", "-C", str(repo_path), "checkout", "main"],
        capture_output=True, text=True, timeout=10,
    )


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    family_root = Path(sys.argv[1])
    show_all = "--all" in sys.argv
    verbose = "--verbose" in sys.argv
    fix_mode = "--fix" in sys.argv

    slot_dirs = find_slot_dirs(family_root)
    slot_dirs.sort(
        key=lambda x: int(m.group(1))
        if (m := re.search(r"(\d+)", x[0].name))
        else 0
    )

    problems: list[dict] = []
    fix_results: list[dict] = []
    total = 0
    multi_repo_count = 0

    for slot_dir, status in slot_dirs:
        slot_num, branch, repos, primary = parse_slot(slot_dir / ".slot")
        if not repos or not branch:
            continue

        total += 1
        is_multi = len(repos) > 1
        if is_multi:
            multi_repo_count += 1
        if not show_all and not is_multi:
            continue

        slot_issues: list[str] = []
        all_ok = True

        for repo_name in repos:
            repo_path = family_root / repo_name
            is_primary = repo_name == primary
            info = check_repo_branch(repo_path, branch)
            classification = classify_status(info)

            marker = "*" if is_primary else " "

            benign = {"OK", "BRANCH_DELETED", "MISSING_REPO",
                      "LANDED_VERIFIED", "SUPERSEDED", "STAMPED_OLD_FORMAT"}
            if classification in benign:
                if verbose:
                    slot_issues.append(f"  {marker} {repo_name}: {classification}")
                continue

            fixable = classification == "UNSTAMPED" or (
                classification.startswith("UNMERGED") and not info.get("is_stamped")
            )

            if fix_mode and fixable:
                disposition = fix_unstamped(repo_path, branch)
                fix_results.append({
                    "slot_num": slot_num, "repo": repo_name,
                    "classification": classification, "disposition": disposition,
                })
                if disposition == "STAMPED":
                    slot_issues.append(
                        f"  {marker} {repo_name}: {classification} → STAMPED"
                    )
                    continue
                else:
                    slot_issues.append(
                        f"  {marker} {repo_name}: {classification} → {disposition}"
                    )
                    all_ok = False
                    continue

            all_ok = False

            if classification == "UNSTAMPED":
                slot_issues.append(f"  {marker} {repo_name}: MERGED but UNSTAMPED")
            elif classification.startswith("LANDING_FAILED"):
                sha = info.get("landing_sha", "?")
                slot_issues.append(
                    f"  {marker} {repo_name}: LANDING SHA {sha} NOT ON MAIN"
                )
            elif classification.startswith("UNMERGED"):
                count = info.get("real_unmerged_count", info.get("unmerged_count", "?"))
                slot_issues.append(
                    f"  {marker} {repo_name}: {count} commits NOT on main (no stamp)"
                )
                for line in (info.get("unmerged_commits", "").splitlines()):
                    slot_issues.append(f"      {line}")

        if not all_ok:
            label = "multi-repo" if is_multi else "single-repo"
            repo_list = ", ".join(repos)
            problems.append({
                "slot_num": slot_num,
                "branch": branch,
                "status": status,
                "is_multi": is_multi,
                "details": slot_issues,
            })
            print(
                f"PROBLEM — Slot {slot_num} [{status}] "
                f"branch={branch} ({label}: {repo_list})"
            )
            for p in slot_issues:
                print(p)
            print()
        elif verbose:
            print(f"OK — Slot {slot_num} [{status}] branch={branch}")
            for p in slot_issues:
                print(p)
            print()

    print(f"=== Audit Summary ===")
    print(f"Total slots scanned: {total}")
    print(f"Multi-repo slots: {multi_repo_count}")
    print(f"Slots with problems: {len(problems)}")

    multi_problems = [p for p in problems if p["is_multi"]]
    single_problems = [p for p in problems if not p["is_multi"]]

    if multi_problems:
        print(f"\nMULTI-REPO problems ({len(multi_problems)}) — HIGH PRIORITY:")
        for p in multi_problems:
            print(f"  Slot {p['slot_num']} [{p['status']}] — {p['branch']}")

    if single_problems:
        print(f"\nSingle-repo problems ({len(single_problems)}):")
        for p in single_problems:
            print(f"  Slot {p['slot_num']} [{p['status']}] — {p['branch']}")

    if not problems:
        print("\nAll slots properly merged and stamped.")

    if fix_results:
        stamped = [r for r in fix_results if r["disposition"] == "STAMPED"]
        skipped = [r for r in fix_results if r["disposition"] != "STAMPED"]
        print(f"\n=== Fix Summary ===")
        print(f"STAMPED: {len(stamped)}")
        if stamped:
            for r in stamped:
                print(f"  Slot {r['slot_num']} {r['repo']}: {r['classification']} → STAMPED")
        if skipped:
            print(f"SKIPPED: {len(skipped)}")
            for r in skipped:
                print(f"  Slot {r['slot_num']} {r['repo']}: {r['disposition']}")

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
