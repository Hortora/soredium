#!/usr/bin/env python3
"""Adversarial Design Review — CLI orchestration script.

Orchestrates adversarial design review between independent Claude sessions
with a Python-based PM for issue tracking and spec diff verification.
"""

from __future__ import annotations

import os
os.environ["PYTHONUNBUFFERED"] = "1"

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Final

# Bootstrap: the skill directory is hyphenated (design-review)
# which isn't a valid Python package name. Register it as adversarial_design_review.
_SKILL_DIR = Path(__file__).parent
if "adversarial_design_review" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "adversarial_design_review",
        _SKILL_DIR / "__init__.py",
        submodule_search_locations=[str(_SKILL_DIR)],
    )
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules["adversarial_design_review"] = _mod
        _spec.loader.exec_module(_mod)

from adversarial_design_review.parser import (
    extract_assumptions,
    extract_confirmations,
    extract_issue_responses,
    extract_new_issues,
    extract_settled_decisions,
    extract_signal,
)
from adversarial_design_review.prompts import (
    build_implementor_prompt,
    build_reviewer_prompt,
    build_sweep_prompt,
)
from adversarial_design_review.setup import build_claude_command, setup_review
from adversarial_design_review.tracker import Tracker, IssueStatus, EvidenceResult, verify_evidence_against_diff

SESSION_TIMEOUT: Final = 600
SESSION_HARD_TIMEOUT: Final = 1800


class ReviewAborted(Exception):
    """Raised when the user deliberately aborts the review."""


class ReviewPaused(Exception):
    """Raised when the review pauses for human intervention (non-interactive timeout)."""


MAX_MISSING_FILE_RETRIES: Final = 2

_LOG_FILE: Path | None = None
_REVIEW_WS: Path | None = None
_REVIEW_NAME: str = ""
_SPEC_PATH: str = ""
_TIMEOUT_COUNT: int = 0
_ERROR_COUNT: int = 0


def _log(msg: str) -> None:
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if _LOG_FILE is not None:
        with open(_LOG_FILE, "a") as f:
            f.write(line + "\n")


def _write_jsonl(ws: Path, role: str, round_num: int, events: list[dict]) -> None:
    jsonl_path = ws / "responses" / f"{role}-{round_num}.jsonl"
    tmp_path = jsonl_path.with_suffix(".jsonl.tmp")
    with open(tmp_path, "w") as f:
        f.write(json.dumps({"event": "schema_version", "version": 1}) + "\n")
        for event in events:
            f.write(json.dumps(event) + "\n")
    os.rename(tmp_path, jsonl_path)


def _build_reviewer_events(
    round_num: int,
    issues: list,
    signal: tuple[str, str | None],
    assumptions: list[str],
    confirmations: list,
    source_file: str,
) -> list[dict]:
    events: list[dict] = []
    for conf in confirmations:
        events.append({
            "event": "confirmation",
            "round": round_num,
            "id": conf.issue_id,
            "verdict": conf.verdict,
            "reason": conf.reason,
        })
    for issue in issues:
        events.append({
            "event": "issue_raised",
            "round": round_num,
            "id": issue.issue_id,
            "title": issue.title,
            "body": issue.body,
            "location": issue.location,
            "priority": issue.priority,
            "depends": issue.depends,
            "scope": None,
        })
    for text in assumptions:
        events.append({
            "event": "assumption",
            "round": round_num,
            "text": text,
            "source": source_file,
        })
    events.append({
        "event": "round_signal",
        "round": round_num,
        "role": "reviewer",
        "signal": signal[0],
        "description": signal[1],
    })
    return events


def _build_implementor_events(
    round_num: int,
    responses: list,
    signal: tuple[str, str | None],
    assumptions: list[str],
    settled: list,
) -> list[dict]:
    events: list[dict] = []
    for resp in responses:
        event_type = {
            "FIXED": "issue_fixed",
            "REJECTED": "issue_rejected",
            "ESCALATED": "issue_escalated",
        }.get(resp.status, "issue_fixed")
        ev: dict = {
            "event": event_type,
            "round": round_num,
            "id": resp.issue_id,
            "rationale": resp.rationale or resp.body,
        }
        if resp.status == "FIXED":
            ev["sectionRef"] = resp.section_ref
            ev["evidence"] = [
                {"location": e.location, "commit": e.commit, "lines": e.lines}
                for e in resp.evidence
            ]
        events.append(ev)
    for sd in settled:
        events.append({
            "event": "settled_decision",
            "round": round_num,
            "text": sd.text,
            "fromIssue": sd.from_issue,
        })
    for text in assumptions:
        events.append({
            "event": "assumption",
            "round": round_num,
            "text": text,
            "source": f"implementor-{round_num}.md",
        })
    events.append({
        "event": "round_signal",
        "round": round_num,
        "role": "implementor",
        "signal": signal[0],
        "description": signal[1],
    })
    return events


def _verify_evidence(evidence: list, spec_path: str | None) -> EvidenceResult:
    if not evidence:
        return EvidenceResult(verified=False, note="no evidence provided")
    if not spec_path:
        return EvidenceResult(verified=False, note="no spec path")
    e = evidence[0]
    diff = _get_commit_diff(e.commit, spec_path)
    if diff is None:
        return EvidenceResult(verified=False, note=f"commit {e.commit} not found")
    try:
        spec_content = Path(spec_path).read_text()
    except OSError:
        return EvidenceResult(verified=False, note="spec file not readable")
    return verify_evidence_against_diff(evidence, diff, spec_content)


def _get_commit_diff(commit: str, spec_path_str: str) -> str | None:
    sp = Path(spec_path_str)
    result = subprocess.run(
        ["git", "diff", f"{commit}~1", commit, "--", sp.name],
        cwd=sp.parent, capture_output=True, text=True,
    )
    if result.returncode != 0:
        result2 = subprocess.run(
            ["git", "show", f"{commit}:{sp.name}"],
            cwd=sp.parent, capture_output=True, text=True,
        )
        if result2.returncode == 0:
            lines = result2.stdout.splitlines()
            return f"@@ -0,0 +1,{len(lines)} @@\n" + "\n".join(f"+{line}" for line in lines)
        return None
    return result.stdout


def main() -> int:
    global _LOG_FILE, _REVIEW_WS, _REVIEW_NAME, _SPEC_PATH, _TIMEOUT_COUNT, _ERROR_COUNT
    args = parse_args()

    if not args.workspace:
        if args.mode == "final-review":
            if not (args.title and args.source_dirs):
                print("ERROR: --title and --source-dirs required for final-review", flush=True)
                return 1
        elif not (args.spec and args.title and args.source_dirs):
            print("ERROR: --spec, --title, and --source-dirs required", flush=True)
            return 1

    # Depth resolution for final-review mode
    resolved_depth: str | None = None
    if args.mode == "final-review":
        if args.depth:
            resolved_depth = args.depth
        # On resume, depth loaded later from .depth file
        # On fresh start, default to standard if no --depth
        if not args.workspace and not resolved_depth:
            resolved_depth = "standard"
    else:
        if args.depth:
            print(f"WARNING: --depth is only supported for final-review mode, ignored for {args.mode}", flush=True)

    start_round = 1

    if args.workspace:
        ws = Path(args.workspace)
        if not ws.is_dir():
            print(f"Review not found: {ws}", flush=True)
            return 1
        mode_file = ws / ".mode"
        if mode_file.exists():
            saved_mode = mode_file.read_text().strip()
            if saved_mode in REVIEW_MODES:
                args.mode = saved_mode
        if not args.title:
            name = ws.name
            args.title = name.rsplit("-", 2)[0]
        if not args.source_dirs:
            source_dirs_file = ws / ".source-dirs"
            if source_dirs_file.exists():
                args.source_dirs = [
                    line for line in source_dirs_file.read_text().splitlines() if line.strip()
                ]
            else:
                args.source_dirs = []
        if not args.source_dirs:
            _LOG_FILE = ws / "progress.log"
            _log("WARNING: No source directories — agents will have no project context.")
            _log("  Provide --source-dirs or create .source-dirs in the workspace.")
        if not args.arch_files:
            arch_files_file = ws / ".arch-files"
            if arch_files_file.exists():
                args.arch_files = [
                    line for line in arch_files_file.read_text().splitlines() if line.strip()
                ]
        if not args.diff_base:
            diff_base_file = ws / ".diff-base"
            if diff_base_file.exists():
                args.diff_base = diff_base_file.read_text().strip() or None
        # Load depth from workspace for final-review resume
        if args.mode == "final-review" and not args.depth:
            resolved_depth = _load_depth(ws)
        _LOG_FILE = ws / "progress.log"
        last_round, reviewer_only = _detect_last_round(ws, depth=resolved_depth)
        if reviewer_only:
            start_round = last_round
            _log(f"Resuming review: {ws}")
            _log(f"Round {last_round} has reviewer but no implementor — resuming at implementor step")
        else:
            start_round = last_round + 1
            _log(f"Resuming review: {ws}")
            _log(f"Last completed round: {last_round}, resuming from round {start_round}")
    else:
        adr_root = Path.home() / "adr"
        existing = sorted(adr_root.glob(f"*/{args.title}-*")) if adr_root.exists() else []
        existing = [d for d in existing if d.is_dir()]
        if existing:
            latest = existing[-1]
            last_round, _ = _detect_last_round(latest)
            if last_round > 0:
                print(
                    f"WARNING: Existing review found at {latest} "
                    f"with {last_round} round(s) completed.\n"
                    f"Use --workspace {latest} to resume instead of starting fresh.",
                    flush=True,
                )
                if _is_interactive():
                    action = input("Continue with NEW review? [y/n] ").strip().lower()
                else:
                    _log("  Non-interactive mode — proceeding with new review (unique timestamp).")
                    action = "y"
                if action != "y":
                    print(f"Aborted. Resume with: --workspace {latest}", flush=True)
                    return 0

        # Apply depth preset overrides for final-review on fresh start
        if args.mode == "final-review" and resolved_depth:
            if resolved_depth in DEPTH_PRESETS:
                preset = DEPTH_PRESETS[resolved_depth]
                args.max_rounds = preset["max_rounds"]
                args.min_rounds = preset["min_rounds"]
                args.budget_per_session = preset["budget_per_session"]

        ws = setup_review(
            spec_path=Path(args.spec) if args.spec else Path(),
            title=args.title,
            source_dirs=args.source_dirs,
            issue=args.issue,
            mode=args.mode,
            arch_files=args.arch_files,
            diff_base=args.diff_base,
            depth=resolved_depth,
        )
        _LOG_FILE = ws / "progress.log"
        _log(f"Review ({args.mode}): {ws}")

    _REVIEW_WS = ws
    _REVIEW_NAME = f"{ws.parent.name}/{ws.name}"
    _log(f"Mode: {args.mode}")
    _log(f"Progress log: {ws}/progress.log (tail -f to watch)")

    spec_path_file = ws / ".spec-path"
    if spec_path_file.exists():
        spec_path = spec_path_file.read_text().strip()
    elif args.spec:
        spec_path = str(Path(args.spec).resolve())
    else:
        spec_path = ""

    # For final-review, spec_path is not used (operates on branch diff)
    if args.mode == "final-review":
        spec_path = ""

    _SPEC_PATH = spec_path
    if spec_path:
        _log(f"Spec: {spec_path}")

    tracker = Tracker(project_name=args.title)
    model = args.model
    budget = args.budget_per_session
    effort = "high"
    skip_reviewer_this_round = reviewer_only if args.workspace else False

    if start_round > 1:
        rebuild_through = start_round if skip_reviewer_this_round else start_round - 1
        _log(f"Rebuilding tracker from {rebuild_through} prior round(s)...")
        _rebuild_tracker(ws, tracker, rebuild_through)
        focus = tracker.get_focus_items()
        _log(f"Tracker rebuilt: {len(tracker.issues())} issues, {len(focus)} open")

        # Health check: detect rounds with missing implementor responses
        for rn in range(1, start_round):
            reviewer_file = ws / "responses" / f"reviewer-{rn}.md"
            impl_file = ws / "responses" / f"implementor-{rn}.md"
            if reviewer_file.exists() and not impl_file.exists():
                _log(f"  WARNING: round {rn} reviewer ran but implementor never responded")

        # Catch-up: if there are unaddressed items, run the implementor
        # before starting the next reviewer round
        if focus:
            _log(f"  {len(focus)} unaddressed items from prior rounds — running implementor catch-up")
            catchup_prompt = build_implementor_prompt(
                round_num=start_round - 1, focus_items=focus,
                source_dirs=args.source_dirs, workspace_root=str(ws),
                spec_path=spec_path, mode=args.mode,
                depth=resolved_depth,
            )
            catchup_prompt += "\n\nThis is a catch-up run. Previous rounds left these items unaddressed. Address all of them."
            catchup_file = f"responses/implementor-{start_round - 1}.md"
            existing_impl = ws / catchup_file
            if not existing_impl.exists():
                _log(f"  Implementor catch-up (fresh)...")
                catchup_result = _invoke_claude(
                    ws, "implementor", catchup_prompt, args.source_dirs,
                    model, budget, effort,
                    expected_file=catchup_file,
                    focus_count=len(focus),
                )
                if catchup_result:
                    _log(f"  Catch-up done (${catchup_result.get('cost', 0.0):.2f})")
                    if existing_impl.exists():
                        impl_content = existing_impl.read_text()
                        for resp in extract_issue_responses(impl_content):
                            if not tracker.has_issue(resp.issue_id):
                                continue
                            try:
                                if resp.status == "FIXED":
                                    tracker.mark_addressed(resp.issue_id, section_ref=resp.section_ref or "",
                                                           commit_hash="", rationale=resp.body[:200])
                                elif resp.status == "REJECTED":
                                    tracker.mark_rejected(resp.issue_id, rationale=resp.rationale[:200])
                                elif resp.status == "ESCALATED":
                                    tracker.mark_deferred(resp.issue_id, note="DECISION_NEEDED")
                            except ValueError:
                                pass
                        tracker.write(ws / "tracker.md")
                        _git_commit(ws, ["tracker.md", catchup_file],
                                     f"catch-up: implementor addressed {len(focus)} items")
                        if args.mode in ("final-review", "code-review"):
                            for sd in args.source_dirs:
                                subprocess.run(["git", "add", "-A"], cwd=sd, capture_output=True)
                                subprocess.run(["git", "commit", "-m",
                                    f"review: code fixes — {args.mode} catchup",
                                    "--allow-empty"], cwd=sd, capture_output=True)
                        else:
                            if spec_path:
                                spec_dir = Path(spec_path).parent
                                spec_name = Path(spec_path).name
                                subprocess.run(["git", "add", spec_name], cwd=spec_dir, capture_output=True)
                                subprocess.run(["git", "commit", "-m", "docs: spec revised — catchup",
                                                "--allow-empty"], cwd=spec_dir, capture_output=True)
                    focus = tracker.get_focus_items()
                    _log(f"  After catch-up: {len(focus)} items still open")

    reviewer_session_id: str | None = None
    implementor_session_id: str | None = None
    cumulative_cost = 0.0
    session_window = args.session_window
    convergence_override_ids: list[str] | None = None

    for round_num in range(start_round, args.max_rounds + 1):
        _log(f"\n{'='*60}")
        _log(f"  ROUND {round_num}")
        _log(f"{'='*60}")

        is_window_end = round_num % session_window == 0

        if round_num > 1 and (round_num - 1) % session_window == 0:
            _log(f"  Session window reset — both agents start fresh this round")
            reviewer_session_id = None
            implementor_session_id = None

        effort = "xhigh" if round_num >= 4 else "high"

        # --- Step 1 & 2: Reviewer + extract + signal checks ---
        if skip_reviewer_this_round:
            _log(f"  Skipping reviewer — already ran for round {round_num}, proceeding to implementor")
            skip_reviewer_this_round = False
        else:
            handover_path: str | None = None
            if reviewer_session_id is None and round_num > 1:
                latest_handover = _find_latest_handover(ws, "reviewer")
                if latest_handover:
                    handover_path = str(latest_handover.relative_to(ws))

            focus = tracker.get_focus_items()
            reviewer_prompt = build_reviewer_prompt(
                round_num=round_num,
                focus_items=focus,
                handover_path=handover_path,
                convergence_override_ids=convergence_override_ids,
                source_dirs=args.source_dirs,
                workspace_root=str(ws),
                spec_path=spec_path,
                mode=args.mode,
                depth=resolved_depth,
                maturity_stage=args.stage,
            )
            convergence_override_ids = None

            if is_window_end:
                reviewer_prompt += "\n\n" + build_sweep_prompt("reviewer", round_num, workspace_root=str(ws))

            use_reviewer_sid = reviewer_session_id if not args.fresh_sessions else None
            reviewer_file = ws / "responses" / f"reviewer-{round_num}.md"
            missing_retries = 0
            while True:
                _log(f"  Reviewer {'(continued — cached context)' if use_reviewer_sid else '(fresh session)'}... (this may take 1-2 minutes)")
                result = _invoke_claude(
                    ws, "reviewer", reviewer_prompt, args.source_dirs,
                    model, budget, effort,
                    session_id=use_reviewer_sid,
                    expected_file=f"responses/reviewer-{round_num}.md",
                )
                if result is None:
                    return 1

                cumulative_cost += result.get("cost", 0.0)
                new_sid = result.get("session_id")
                if reviewer_session_id is None and new_sid:
                    reviewer_session_id = new_sid
                elif reviewer_session_id and not new_sid and result.get("timed_out"):
                    _log(f"  WARNING: reviewer session ID lost to timeout — next round will be fresh")
                    reviewer_session_id = None
                _log(f"  Reviewer done (${result.get('cost', 0.0):.2f})")

                if reviewer_file.exists():
                    break
                missing_retries += 1
                _log(f"  WARNING: reviewer-{round_num}.md not created (attempt {missing_retries}/{MAX_MISSING_FILE_RETRIES})")
                if missing_retries >= MAX_MISSING_FILE_RETRIES:
                    raise ReviewPaused(f"Reviewer failed to produce output after {MAX_MISSING_FILE_RETRIES} attempts — resume with --workspace to retry")
                action = _prompt_hil("Response file missing. [r]etry / [a]bort? ", default="r")
                if action == "a":
                    return 1

            reviewer_content = reviewer_file.read_text()
            signal = extract_signal(reviewer_content)
            if signal.is_default:
                _log(f"  WARNING: No signal found in reviewer-{round_num}.md, defaulting to CONTINUE")

            existing_ids = tracker.issue_ids()
            new_issues = extract_new_issues(reviewer_content, round_num, existing_ids)
            for issue in new_issues:
                tracker.add_issue(issue.issue_id, issue.title, round_raised=round_num,
                                  location=issue.location or "",
                                  priority=issue.priority,
                                  depends=issue.depends)
            if new_issues:
                _log(f"  {len(new_issues)} new issue(s) raised")
                _inject_issue_ids(reviewer_file, new_issues)

            confirmations = extract_confirmations(reviewer_content)
            for conf in confirmations:
                if not tracker.has_issue(conf.issue_id):
                    continue
                try:
                    if conf.verdict == "resolved":
                        tracker.mark_verified(conf.issue_id)
                    elif conf.verdict == "accepted":
                        tracker.mark_accepted(conf.issue_id)
                    else:
                        tracker.mark_contested(conf.issue_id, reason=conf.reason)
                except ValueError:
                    pass

            for assumption in extract_assumptions(reviewer_content):
                tracker.add_assumption(assumption, round_surfaced=round_num, source=f"reviewer-{round_num}.md")

            reviewer_events = _build_reviewer_events(
                round_num, new_issues,
                (signal.signal_type, signal.description),
                extract_assumptions(reviewer_content),
                confirmations,
                f"reviewer-{round_num}.md",
            )
            _write_jsonl(ws, "reviewer", round_num, reviewer_events)

            tracker.write(ws / "tracker.md")
            _git_commit(ws, ["tracker.md", f"responses/reviewer-{round_num}.md",
                              f"responses/reviewer-{round_num}.jsonl"],
                         f"tracker: round {round_num} reviewer issues")
            _check_unstaged(ws)

            # Light depth skip — reviewer-only mode
            if resolved_depth == "light":
                _log("  Light depth — skipping implementor (reviewer-only mode)")
                _log(f"\n  Review complete after {round_num} round(s)")
                _print_summary(tracker, round_num, cumulative_cost, spec_path)
                return 0

            if signal.signal_type == "APPROVED":
                if round_num < args.min_rounds:
                    _log(f"  APPROVED in round {round_num} but min-rounds is {args.min_rounds} — overriding to CONTINUE")
                    _log(f"  Reviewer: look deeper. You are not expected to approve before round {args.min_rounds}.")
                elif not tracker.all_resolved():
                    unresolved = tracker.get_focus_items()
                    _log(f"  APPROVED overridden — {len(unresolved)} item(s) not in terminal state:")
                    for iid in unresolved:
                        issue = tracker.get_issue(iid)
                        _log(f"    {iid}: {issue.summary} [{issue.status.value}]")
                    convergence_override_ids = unresolved
                else:
                    convergence = tracker.check_premature_convergence(round_num)
                    if not convergence.should_override:
                        _log(f"\n  APPROVED by reviewer in round {round_num}")
                        continue_with = _check_unresolved_before_done(tracker, round_num, cumulative_cost, spec_path)
                        if not continue_with:
                            _print_summary(tracker, round_num, cumulative_cost, spec_path)
                            return 0
                        _log(f"  Continuing with {len(continue_with)} item(s): {', '.join(continue_with)}")
                    else:
                        _log(f"  Premature convergence detected — overriding APPROVED")
                        convergence_override_ids = convergence.unconfirmed_ids

            if signal.signal_type == "DECISION_NEEDED":
                _handle_decision_needed(ws, tracker, round_num, signal.description or "", role="reviewer")
                tracker.write(ws / "tracker.md")
                _git_commit(ws, ["tracker.md", f"decisions/decision-{round_num}-reviewer.md"],
                             f"tracker: round {round_num} human decision")

        # --- Step 3: Implementor ---
        focus = tracker.get_focus_items()
        implementor_prompt = build_implementor_prompt(
            round_num=round_num, focus_items=focus, source_dirs=args.source_dirs,
            workspace_root=str(ws), spec_path=spec_path, mode=args.mode,
            depth=resolved_depth,
        )

        if is_window_end:
            implementor_prompt += "\n\n" + build_sweep_prompt("implementor", round_num, workspace_root=str(ws))

        use_impl_sid = implementor_session_id if not args.fresh_sessions else None
        implementor_file = ws / "responses" / f"implementor-{round_num}.md"
        missing_retries = 0
        while True:
            _log(f"  Implementor {'(continued — cached context)' if use_impl_sid else '(fresh session)'}... (this may take 1-2 minutes)")
            result = _invoke_claude(
                ws, "implementor", implementor_prompt, args.source_dirs,
                model, budget, effort,
                session_id=use_impl_sid,
                expected_file=f"responses/implementor-{round_num}.md",
                focus_count=len(focus),
            )
            if result is None:
                return 1

            cumulative_cost += result.get("cost", 0.0)
            new_sid = result.get("session_id")
            if implementor_session_id is None and new_sid:
                implementor_session_id = new_sid
            elif implementor_session_id and not new_sid and result.get("timed_out"):
                _log(f"  WARNING: implementor session ID lost to timeout — next round will be fresh")
                implementor_session_id = None
            _log(f"  Implementor done (${result.get('cost', 0.0):.2f})")

            # Timeout with partial output — find what's missing and retry
            if implementor_file.exists() and result.get("timed_out"):
                partial_content = implementor_file.read_text()
                partial_responses = extract_issue_responses(partial_content)
                addressed_ids = {r.issue_id for r in partial_responses}
                missing = [f for f in focus if f not in addressed_ids]
                if missing:
                    # Pre-apply partial responses so they survive if retry overwrites
                    for resp in partial_responses:
                        if not tracker.has_issue(resp.issue_id):
                            continue
                        try:
                            if resp.status == "FIXED":
                                tracker.mark_addressed(resp.issue_id, section_ref=resp.section_ref or "",
                                                       commit_hash="", rationale=resp.body[:200])
                            elif resp.status == "REJECTED":
                                tracker.mark_rejected(resp.issue_id, rationale=resp.rationale[:200])
                            elif resp.status == "ESCALATED":
                                tracker.mark_deferred(resp.issue_id, note="DECISION_NEEDED")
                        except ValueError:
                            pass
                    _log(f"  {len(missing)} items unaddressed after timeout: {', '.join(missing)} — retrying")
                    retry_prompt = build_implementor_prompt(
                        round_num=round_num, focus_items=missing,
                        source_dirs=args.source_dirs, workspace_root=str(ws),
                        spec_path=spec_path, mode=args.mode,
                        depth=resolved_depth,
                    )
                    retry_prompt += f"\n\nYour previous response is at responses/implementor-{round_num}.md — read it. Address only the items listed above that are not yet covered. Do not duplicate items already addressed."
                    retry_result = _invoke_claude(
                        ws, "implementor", retry_prompt, args.source_dirs,
                        model, budget, effort,
                        expected_file=f"responses/implementor-{round_num}.md",
                        focus_count=len(missing),
                    )
                    if retry_result:
                        cumulative_cost += retry_result.get("cost", 0.0)

            if implementor_file.exists():
                break
            missing_retries += 1
            _log(f"  WARNING: implementor-{round_num}.md not created (attempt {missing_retries}/{MAX_MISSING_FILE_RETRIES})")
            if missing_retries >= MAX_MISSING_FILE_RETRIES:
                raise ReviewPaused(f"Implementor failed to produce output after {MAX_MISSING_FILE_RETRIES} attempts — resume with --workspace to retry")
            action = _prompt_hil("Response file missing. [r]etry / [a]bort? ", default="r")
            if action == "a":
                return 1

        # Build and write implementor JSONL
        if implementor_file.exists():
            _impl_content = implementor_file.read_text()
            _impl_sig = extract_signal(_impl_content)
            _impl_responses = extract_issue_responses(_impl_content)
            impl_events = _build_implementor_events(
                round_num, _impl_responses,
                (_impl_sig.signal_type, _impl_sig.description),
                extract_assumptions(_impl_content),
                extract_settled_decisions(_impl_content),
            )
            _write_jsonl(ws, "implementor", round_num, impl_events)

        # Commit implementor response to review folder
        _git_commit(ws, [f"responses/implementor-{round_num}.md",
                          f"responses/implementor-{round_num}.jsonl"],
                     f"round {round_num}: implementor response")
        # Mode-conditional commit: code changes for final-review/code-review, spec for others
        if args.mode in ("final-review", "code-review"):
            for sd in args.source_dirs:
                subprocess.run(["git", "add", "-A"], cwd=sd, capture_output=True)
                subprocess.run(["git", "commit", "-m",
                    f"review: code fixes — {args.mode} round {round_num}",
                    "--allow-empty"], cwd=sd, capture_output=True)
        else:
            if spec_path:
                spec_dir = Path(spec_path).parent
                spec_name = Path(spec_path).name
                subprocess.run(["git", "add", spec_name], cwd=spec_dir, capture_output=True)
                subprocess.run(["git", "commit", "-m", f"docs: spec revised — review round {round_num}",
                                "--allow-empty"], cwd=spec_dir, capture_output=True)
        _check_unstaged(ws)

        # --- Step 4: Script verify ---
        if implementor_file.exists():
            impl_content = implementor_file.read_text()

            impl_signal = extract_signal(impl_content)
            responses = extract_issue_responses(impl_content)

            # Mode-conditional verification
            if args.mode in ("final-review", "code-review"):
                diff = _get_source_diff(args.source_dirs)
                vr = verify_code_changed(diff)
            else:
                if spec_path:
                    diff = _get_git_diff(spec_path)
                else:
                    diff = ""

            for resp in responses:
                if not tracker.has_issue(resp.issue_id):
                    continue
                try:
                    if resp.status == "FIXED":
                        if args.mode in ("final-review", "code-review"):
                            # For code modes, just track that code changed
                            tracker.mark_addressed(
                                resp.issue_id,
                                section_ref=resp.section_ref or "",
                                commit_hash="",
                                rationale=resp.body[:200] if resp.body else "",
                            )
                        else:
                            # For spec modes, verify evidence
                            tracker.mark_addressed(
                                resp.issue_id,
                                section_ref=resp.section_ref or "",
                                commit_hash=_get_head_hash(spec_path) if spec_path else "",
                                rationale=resp.body[:200] if resp.body else "",
                            )
                            if spec_path:
                                ev_result = _verify_evidence(resp.evidence, spec_path)
                                if not ev_result.verified:
                                    issue = tracker.get_issue(resp.issue_id)
                                    issue.notes = ev_result.note
                                    _log(f"  WARNING: {resp.issue_id} {ev_result.note}")
                    elif resp.status == "REJECTED":
                        tracker.mark_rejected(resp.issue_id, rationale=resp.rationale[:200])
                    elif resp.status == "ESCALATED":
                        tracker.mark_deferred(resp.issue_id, note="DECISION_NEEDED")
                except ValueError:
                    pass  # already in target state — skip

            for assumption in extract_assumptions(impl_content):
                tracker.add_assumption(assumption, round_surfaced=round_num, source=f"implementor-{round_num}.md")

            for decision in extract_settled_decisions(impl_content):
                tracker.add_settled_decision(
                    decision.text, from_issue=decision.from_issue, rationale="",
                )

            if impl_signal.signal_type == "DECISION_NEEDED":
                _handle_decision_needed(ws, tracker, round_num, impl_signal.description or "", role="implementor")

        tracker.current_round = round_num
        tracker.record_round(round_num)
        tracker.write(ws / "tracker.md")
        _git_commit(ws, ["tracker.md"], f"tracker: round {round_num} verification")
        _check_unstaged(ws)

        # --- Termination checks ---
        all_resolved = tracker.all_resolved()

        if all_resolved:
            _log(f"\n  All issues resolved in round {round_num}")
            continue_with = _check_unresolved_before_done(tracker, round_num, cumulative_cost, spec_path)
            if not continue_with:
                _print_summary(tracker, round_num, cumulative_cost, spec_path)
                return 0

        cost_per_round = cumulative_cost / round_num if round_num > 0 else 0
        _log(f"  Round {round_num} complete — ~${cost_per_round:.2f}/round, ${cumulative_cost:.2f} cumulative")

        if is_window_end:
            _log(f"  Session window complete — resetting sessions next round")

    # Max rounds reached — checkpoint
    _log(f"\n{'='*60}")
    _log(f"  CHECKPOINT — Round {args.max_rounds}")
    _log(f"{'='*60}")
    _print_summary(tracker, args.max_rounds, cumulative_cost, spec_path)
    _log(f"\nOptions:")
    _log(f"  [c] Continue for N more rounds")
    _log(f"  [d] Defer remaining and finish")
    _log(f"  [a] Abort")

    if _is_interactive():
        choice = input("> ").strip().lower()
    else:
        _log("  Non-interactive mode — deferring remaining items and finishing.")
        choice = "d"
    if choice == "d":
        deferred_ids = tracker.get_focus_items()
        for iid in deferred_ids:
            try:
                tracker.mark_deferred(iid, note="deferred at checkpoint")
            except ValueError:
                issue = tracker.get_issue(iid)
                issue.status = IssueStatus.DEFERRED
                issue.notes = "deferred at checkpoint (forced)"
        checkpoint_file = ws / "responses" / f"checkpoint-{args.max_rounds}.md"
        checkpoint_lines = [f"### {iid}: ESCALATED" for iid in deferred_ids]
        checkpoint_lines.append("\n---\nSIGNAL: CONTINUE\n")
        checkpoint_file.write_text("\n".join(checkpoint_lines))
        tracker.write(ws / "tracker.md")
        _git_commit(ws, ["tracker.md", f"responses/checkpoint-{args.max_rounds}.md"],
                     "tracker: checkpoint — remaining items deferred")
        _print_summary(tracker, args.max_rounds, cumulative_cost, spec_path)
    elif choice.startswith("c"):
        _log(f"Re-run with --workspace {ws} --max-rounds N to continue.")
    elif choice == "a":
        raise ReviewAborted("User aborted at checkpoint")

    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _invoke_claude(
    ws: Path,
    role: str,
    prompt: str,
    source_dirs: list[str],
    model: str,
    budget: float,
    effort: str,
    session_id: str | None = None,
    expected_file: str | None = None,
    focus_count: int = 0,
) -> dict | None:
    global _TIMEOUT_COUNT, _ERROR_COUNT
    cmd = build_claude_command(
        role_dir=ws / "agents" / role,
        context_md=ws / "context.md",
        source_dirs=source_dirs,
        adr_root=ws,
        model=model,
        budget=budget,
        effort=effort,
        prompt=prompt,
        session_id=session_id,
    )

    import time
    invoke_retries = 0

    while True:
        proc = subprocess.Popen(
            cmd, cwd=ws,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, text=True,
        )

        start_time = time.time()
        file_seen = False
        file_size = 0
        check_interval = 30

        soft_timeout_logged = False
        hil_marker = ws / ".hil-timeout"

        while proc.poll() is None:
            elapsed = int(time.time() - start_time)

            if elapsed > 0 and elapsed % check_interval == 0:
                if expected_file:
                    ef = ws / expected_file
                    if ef.exists():
                        new_size = ef.stat().st_size
                        if not file_seen:
                            _log(f"    [{elapsed}s] output file appeared ({new_size} bytes)")
                            file_seen = True
                        elif new_size > file_size:
                            _log(f"    [{elapsed}s] output file growing ({new_size} bytes)")
                        file_size = new_size
                    elif elapsed >= 120 and not file_seen:
                        _log(f"    [{elapsed}s] no output file yet — agent may be reading/exploring")

                # Check agent narration status file
                status_file = ws / "agents" / role / ".status"
                if status_file.exists():
                    try:
                        agent_status = status_file.read_text().strip()
                        if agent_status:
                            _log(f"    [{elapsed}s] {role}: {agent_status}")
                            status_file.write_text("")
                    except OSError:
                        pass

                # Soft timeout: log status, write HIL marker, keep running
                if elapsed >= SESSION_TIMEOUT and not soft_timeout_logged:
                    soft_timeout_logged = True
                    _TIMEOUT_COUNT += 1
                    if file_seen:
                        _log(f"  [{elapsed}s] SOFT TIMEOUT — output file exists ({file_size} bytes), agent still running")
                        _log(f"  Agent will continue until {SESSION_HARD_TIMEOUT}s or HIL response")
                    else:
                        _log(f"  [{elapsed}s] SOFT TIMEOUT — no output yet, agent still exploring")
                        _log(f"  Agent will continue until {SESSION_HARD_TIMEOUT}s or HIL response")
                    hil_marker.write_text(f"timeout:{elapsed}\nfile_seen:{file_seen}\nfile_size:{file_size}\n")

                # Check for HIL response: parent writes "kill" or "extend" to marker
                if soft_timeout_logged and hil_marker.exists():
                    response = hil_marker.read_text().strip()
                    if response == "kill":
                        _log(f"  [{elapsed}s] HIL: kill requested")
                        hil_marker.unlink(missing_ok=True)
                        proc.kill()
                        proc.wait()
                        break
                    elif response == "extend":
                        _log(f"  [{elapsed}s] HIL: extending timeout by {SESSION_TIMEOUT}s")
                        start_time = time.time() - SESSION_TIMEOUT + SESSION_TIMEOUT
                        soft_timeout_logged = False
                        hil_marker.unlink(missing_ok=True)

                # Hard timeout: kill unconditionally
                if elapsed >= SESSION_HARD_TIMEOUT:
                    _log(f"  [{elapsed}s] HARD TIMEOUT — killing agent")
                    proc.kill()
                    proc.wait()
                    hil_marker.unlink(missing_ok=True)
                    break

            time.sleep(1)

        hil_marker.unlink(missing_ok=True)

        # Drain pipes after kill to capture any error output
        if proc.returncode is not None and proc.returncode < 0:
            try:
                stderr_after_kill = proc.stderr.read()[:500] if proc.stderr else ""
                if stderr_after_kill:
                    _log(f"  stderr after timeout: {stderr_after_kill[:200]}")
                    if "permission" in stderr_after_kill.lower() or "trust" in stderr_after_kill.lower():
                        _log(f"  LIKELY CAUSE: permission prompt blocked the agent")
                        _log(f"  Check ~/.claude/settings.json permissions.allow")
            except Exception:
                pass

        # If process was killed by timeout, handle the result
        if proc.returncode is not None and proc.returncode < 0:
            if file_seen and expected_file:
                ef = ws / expected_file
                if ef.exists():
                    content = ef.read_text()
                    import re
                    addressed = len(re.findall(r"###\s+R\d+-\d+:\s+(?:FIXED|REJECTED|ESCALATED)", content, re.IGNORECASE))
                    findings = len(re.findall(r"^###\s+", content, re.MULTILINE))
                    if "implementor" in expected_file and addressed > 0:
                        if focus_count > 0:
                            pct = int(addressed / focus_count * 100)
                            _log(f"  Progress: {addressed}/{focus_count} issues addressed ({pct}%)")
                        else:
                            _log(f"  Progress: {addressed} issues addressed in partial response")
                    elif "reviewer" in expected_file and findings > 0:
                        _log(f"  Progress: {findings} findings written in partial response")
                action = _prompt_hil(
                    "Agent timed out. [c]ontinue with output / [r]etry / [a]bort? " if file_seen
                    else f"No output (attempt {invoke_retries + 1}). [r]etry / [a]bort / [s]kip? ",
                    default="c" if file_seen else "r",
                )
                if action == "r":
                    invoke_retries += 1
                    if invoke_retries >= MAX_MISSING_FILE_RETRIES:
                        raise ReviewPaused(f"Agent timed out {invoke_retries} times — resume with --workspace to retry")
                    continue
                if action == "a":
                    return None
                if file_seen:
                    return {"cost": 0.0, "timed_out": True}
                return {"cost": 0.0, "timed_out": True}
            continue

        stdout = proc.stdout.read()
        stderr = proc.stderr.read()
        result_code = proc.returncode

        if result_code != 0:
            _ERROR_COUNT += 1
            stderr_text = stderr[:500] if stderr else ""
            if "permission" in stderr_text.lower() or "trust" in stderr_text.lower():
                _log(f"  PERMISSION ERROR: claude -p needs permission approval.")
                _log(f"  Add to ~/.claude/settings.json permissions.allow:")
                _log(f'    "Bash(python3 */.claude/skills/design-review/review.py *)"')
                _log(f"  Or run with: ! python3 ... (foreground with visible prompts)")
            _log(f"  Session failed (exit {result_code}): {stderr_text[:200]}")
            action = _prompt_hil("[r]etry / [a]bort / [s]kip? ")
            if action == "r":
                continue
            if action == "a":
                return None
            return {"cost": 0.0}

        break

    cost = 0.0
    sid: str | None = None
    try:
        data = json.loads(stdout)
        cost = data.get("total_cost_usd", 0.0) or 0.0
        sid = data.get("session_id")
    except (json.JSONDecodeError, TypeError):
        pass

    out = {"cost": cost}
    if sid:
        out["session_id"] = sid
    return out


def _inject_issue_ids(reviewer_file: Path, issues: list) -> None:
    content = reviewer_file.read_text()
    for issue in issues:
        if issue.title.startswith(issue.issue_id):
            continue
        old_heading = f"### {issue.title}"
        new_heading = f"### {issue.issue_id}: {issue.title}"
        content = content.replace(old_heading, new_heading, 1)
        old_h2 = f"## {issue.title}"
        if old_h2 in content and new_heading not in content:
            content = content.replace(old_h2, f"## {issue.issue_id}: {issue.title}", 1)
    reviewer_file.write_text(content)


def _detect_last_round(ws: Path, depth: str | None = None) -> tuple[int, bool]:
    """Returns (last_round, reviewer_only).

    reviewer_only=True means the last round has a reviewer file but
    no implementor file — the implementor still needs to run.

    For depth="light", reviewer-only rounds are considered complete (reviewer_only=False).
    """
    responses = ws / "responses"
    if not responses.is_dir():
        return 0, False
    reviewer_rounds: set[int] = set()
    implementor_rounds: set[int] = set()
    for f in responses.iterdir():
        if f.suffix != ".md":
            continue
        try:
            n = int(f.stem.split("-")[1])
            if f.name.startswith("implementor-"):
                implementor_rounds.add(n)
            elif f.name.startswith("reviewer-"):
                reviewer_rounds.add(n)
        except (IndexError, ValueError):
            pass
    if not reviewer_rounds:
        return 0, False
    max_reviewer = max(reviewer_rounds)
    if max_reviewer in implementor_rounds:
        return max_reviewer, False
    if depth == "light":
        return max_reviewer, False  # complete — light is reviewer-only
    return max_reviewer, True  # partial — implementor needed


def _auto_detect_depth(diff_stat_summary: str, new_file_count: int = 0) -> str:
    """Detect review depth from diff stat summary line.

    Args:
        diff_stat_summary: The summary line from git diff --stat (e.g.,
            "6 files changed, 120 insertions(+), 30 deletions(-)").
        new_file_count: Number of new files in the diff. Each counts double
            toward the line threshold.
    """
    import re
    files_m = re.search(r"(\d+) files? changed", diff_stat_summary)
    ins_m = re.search(r"(\d+) insertions?", diff_stat_summary)
    del_m = re.search(r"(\d+) deletions?", diff_stat_summary)

    file_count = int(files_m.group(1)) if files_m else 0
    insertions = int(ins_m.group(1)) if ins_m else 0
    deletions = int(del_m.group(1)) if del_m else 0
    total_lines = insertions + deletions + (new_file_count * 20)

    if file_count > 10 or total_lines > 300:
        return "deep"
    if file_count > 3 or total_lines > 50:
        return "standard"
    return "light"


def _load_depth(ws: Path) -> str | None:
    """Load persisted depth from workspace, or None if absent."""
    depth_file = ws / ".depth"
    if depth_file.exists():
        value = depth_file.read_text().strip()
        if value in DEPTH_PRESETS:
            return value
    return None


def _rebuild_tracker(ws: Path, tracker: Tracker, through_round: int) -> None:
    for rn in range(1, through_round + 1):
        reviewer_file = ws / "responses" / f"reviewer-{rn}.md"
        if reviewer_file.exists():
            content = reviewer_file.read_text()
            existing_ids = tracker.issue_ids()
            new_issues = extract_new_issues(content, rn, existing_ids)
            for issue in new_issues:
                tracker.add_issue(issue.issue_id, issue.title, round_raised=rn)

            for conf in extract_confirmations(content):
                if not tracker.has_issue(conf.issue_id):
                    continue
                try:
                    if conf.verdict == "resolved":
                        tracker.mark_verified(conf.issue_id)
                    elif conf.verdict == "accepted":
                        tracker.mark_accepted(conf.issue_id)
                    else:
                        tracker.mark_contested(conf.issue_id, reason=conf.reason)
                except ValueError:
                    pass

            for assumption in extract_assumptions(content):
                tracker.add_assumption(assumption, round_surfaced=rn, source=f"reviewer-{rn}.md")

        implementor_file = ws / "responses" / f"implementor-{rn}.md"
        if implementor_file.exists():
            content = implementor_file.read_text()
            for resp in extract_issue_responses(content):
                if not tracker.has_issue(resp.issue_id):
                    continue
                try:
                    if resp.status == "FIXED":
                        tracker.mark_addressed(resp.issue_id, section_ref=resp.section_ref or "",
                                               commit_hash="", rationale=resp.body[:200])
                    elif resp.status == "REJECTED":
                        tracker.mark_rejected(resp.issue_id, rationale=resp.rationale[:200])
                    elif resp.status == "ESCALATED":
                        tracker.mark_deferred(resp.issue_id, note="DECISION_NEEDED")
                except ValueError:
                    pass

            for assumption in extract_assumptions(content):
                tracker.add_assumption(assumption, round_surfaced=rn, source=f"implementor-{rn}.md")
            for decision in extract_settled_decisions(content):
                tracker.add_settled_decision(decision.text, from_issue=decision.from_issue, rationale="")

        # Checkpoint deferrals (written at max-rounds checkpoint)
        checkpoint_file = ws / "responses" / f"checkpoint-{rn}.md"
        if checkpoint_file.exists():
            content = checkpoint_file.read_text()
            for resp in extract_issue_responses(content):
                if not tracker.has_issue(resp.issue_id):
                    continue
                try:
                    if resp.status == "ESCALATED":
                        tracker.mark_deferred(resp.issue_id, note="deferred at checkpoint")
                except ValueError:
                    issue = tracker.get_issue(resp.issue_id)
                    issue.status = IssueStatus.DEFERRED
                    issue.notes = "deferred at checkpoint (forced)"

        tracker.current_round = rn
        tracker.record_round(rn)


def _git_commit(ws: Path, files: list[str], message: str) -> None:
    adr_root = _find_adr_root(ws)
    for f in files:
        path = ws / f
        if path.exists():
            rel = path.relative_to(adr_root)
            subprocess.run(["git", "add", str(rel)], cwd=adr_root, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message, "--allow-empty"],
        cwd=adr_root, capture_output=True,
    )


def _find_adr_root(ws: Path) -> Path:
    p = ws
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    return ws


def _check_unstaged(ws: Path) -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ws, capture_output=True, text=True,
    )
    dirty = [line for line in result.stdout.splitlines() if line.strip()]
    if dirty:
        _log(f"  WARNING: {len(dirty)} unexpected change(s) after commit:")
        for line in dirty[:5]:
            _log(f"    {line}")


def _get_git_diff(spec_path_str: str) -> str:
    sp = Path(spec_path_str)
    result = subprocess.run(
        ["git", "diff", "HEAD~1", sp.name], cwd=sp.parent, capture_output=True, text=True,
    )
    return result.stdout


def _get_source_diff(source_dirs: list[str]) -> str:
    """Get combined diff across all source directories."""
    diffs: list[str] = []
    for sd in source_dirs:
        result = subprocess.run(
            ["git", "diff", "HEAD~1"], cwd=sd, capture_output=True, text=True,
        )
        if result.stdout.strip():
            diffs.append(result.stdout)
    return "\n".join(diffs)


class _VerifyResult:
    def __init__(self, section_changed: bool) -> None:
        self.section_changed = section_changed


def verify_code_changed(diff: str) -> _VerifyResult:
    """Check whether any code was modified."""
    return _VerifyResult(section_changed=bool(diff.strip()))


def _get_head_hash(spec_path_str: str) -> str:
    sp = Path(spec_path_str)
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=sp.parent, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _find_latest_handover(ws: Path, role: str) -> Path | None:
    handovers = sorted((ws / "handovers").glob(f"{role}-handover-*.md"))
    return handovers[-1] if handovers else None


def _handle_decision_needed(
    ws: Path, tracker: Tracker, round_num: int, description: str,
    issue_id: str = "", role: str = "",
) -> None:
    if not issue_id and description:
        import re
        m = re.search(r"R\d+-\d+", description)
        if m:
            issue_id = m.group(0)
    _log(f"\n  {'─'*50}")
    _log(f"  DECISION NEEDED (round {round_num})")
    if issue_id:
        _log(f"  Issue: {issue_id}")
    _log(f"  {description}")
    _log(f"  Tracker: {ws}/tracker.md")
    _log(f"  {'─'*50}")

    if _is_interactive():
        decision = input("  Enter decision (or 'skip' to defer, 'abort' to end): ").strip()
    else:
        decision = "skip"
        _log("  Non-interactive mode — deferring decision.")
    if decision.lower() == "abort":
        raise ReviewAborted("User aborted at DECISION_NEEDED prompt")

    parts = [f"---", f"round: {round_num}"]
    if issue_id:
        parts.append(f"issue: {issue_id}")
    parts.extend([f"decision: {decision}", "---", ""])

    suffix = f"-{role}" if role else ""
    decision_file = ws / "decisions" / f"decision-{round_num}{suffix}.md"
    decision_file.write_text("\n".join(parts))



def _is_interactive() -> bool:
    import sys
    return sys.stdin.isatty()


def _prompt_hil(message: str, default: str = "s") -> str:
    if not _is_interactive():
        _log(f"  {message} [non-interactive, defaulting to '{default}']")
        return default
    return input(f"  {message}").strip().lower()


def _check_unresolved_before_done(
    tracker: Tracker, round_num: int, cumulative_cost: float,
    spec_path: str = "",
) -> list[str]:
    """HIL gate before accepting review completion with unresolved items.

    Returns issue IDs to continue with, or empty list to accept the review.
    """
    focus = tracker.get_focus_items()
    if not focus:
        return []

    _log(f"\n  {len(focus)} unresolved item(s):")
    items: list[str] = []
    for i, iid in enumerate(focus, 1):
        issue = tracker.get_issue(iid)
        _log(f"    {i}. {iid}: {issue.summary} [{issue.status.value}]")
        items.append(iid)

    _print_summary(tracker, round_num, cumulative_cost, spec_path)
    action = _prompt_hil(
        "[a]ccept review / [f]ix all / or item numbers (e.g. 1,3): ",
        default="a",
    )

    if action == "a":
        return []
    if action == "f":
        return items
    try:
        indices = [int(x.strip()) for x in action.split(",") if x.strip()]
        selected = [items[i - 1] for i in indices if 1 <= i <= len(items)]
        return selected if selected else []
    except (ValueError, IndexError):
        _log(f"  Could not parse '{action}' — accepting review")
        return []


def _print_summary(tracker: Tracker, round_num: int, cost: float, spec_path: str = "") -> None:
    counts = {"VERIFIED": 0, "ACCEPTED": 0, "DEFERRED": 0, "OPEN": 0, "CONTESTED": 0, "ADDRESSED": 0, "REJECTED": 0}
    for issue in tracker.issues():
        counts[issue.status.value] = counts.get(issue.status.value, 0) + 1

    total = len(tracker.issues())
    unresolved = counts['OPEN'] + counts['CONTESTED'] + counts['ADDRESSED'] + counts['REJECTED']
    _log(f"\n  Rounds:  {round_num}")
    _log(f"  Issues:  {total} raised")
    _log(f"           {counts['VERIFIED']} verified")
    _log(f"           {counts['ACCEPTED']} accepted")
    _log(f"           {counts['DEFERRED']} deferred")
    _log(f"           {unresolved} unresolved")
    _log(f"  Cost:    ${cost:.2f}")
    health_parts = []
    if _TIMEOUT_COUNT:
        health_parts.append(f"{_TIMEOUT_COUNT} timeout(s)")
    if _ERROR_COUNT:
        health_parts.append(f"{_ERROR_COUNT} error(s)")
    _log(f"  Health:  {', '.join(health_parts) if health_parts else 'no issues'}")
    if spec_path:
        _log(f"  Spec:    file://{spec_path}")
    else:
        _log(f"  Spec:    {tracker.project_name}")


REVIEW_MODES: Final = ("pre-review", "spec-review", "code-review", "final-review")

MODE_DEFAULTS: Final = {
    "pre-review": {"max_rounds": 3, "min_rounds": 2, "budget_per_session": 3.0},
    "spec-review": {"max_rounds": 10, "min_rounds": 4, "budget_per_session": 5.0},
    "code-review": {"max_rounds": 4, "min_rounds": 2, "budget_per_session": 5.0},
    "final-review": {"max_rounds": 3, "min_rounds": 2, "budget_per_session": 5.0},
}

DEPTH_PRESETS: Final = {
    "light":    {"max_rounds": 1, "min_rounds": 1, "budget_per_session": 1.5},
    "standard": {"max_rounds": 3, "min_rounds": 2, "budget_per_session": 5.0},
    "deep":     {"max_rounds": 5, "min_rounds": 3, "budget_per_session": 8.0},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Adversarial Design Review")
    parser.add_argument("--spec", default=None, help="Path to the design spec (not needed with --workspace)")
    parser.add_argument("--title", default=None, help="Short name for the review (not needed with --workspace)")
    parser.add_argument("--source-dirs", nargs="+", default=None, help="Context directories")
    parser.add_argument("--mode", choices=REVIEW_MODES, default="spec-review",
                        help="Review phase (default: spec-review)")
    parser.add_argument("--max-rounds", type=int, default=None)
    parser.add_argument("--min-rounds", type=int, default=None,
                        help="Minimum rounds before APPROVED is accepted")
    parser.add_argument("--session-window", type=int, default=5)
    parser.add_argument("--model", default="opus")
    parser.add_argument("--budget-per-session", type=float, default=None)
    parser.add_argument("--fresh-sessions", action="store_true")
    parser.add_argument("--workspace", default=None,
                        help="Resume from an existing workspace directory")
    parser.add_argument("--issue", default=None,
                        help="GitHub issue number associated with this spec")
    parser.add_argument("--arch-files", nargs="+", default=None,
                        help="Architectural files for agents to prioritise (overrides auto-detection)")
    parser.add_argument("--diff-base", default=None,
                        help="Git ref to diff against for code-review and final-review modes (branch, SHA, or tag)")
    parser.add_argument("--depth", choices=("light", "standard", "deep"),
                        default=None,
                        help="Review depth for final-review mode (default: auto-detect)")
    parser.add_argument("--stage", choices=("pre-release", "released"),
                        default="pre-release",
                        help="Project maturity stage — released adds backward-compat checks")
    args = parser.parse_args()
    defaults = MODE_DEFAULTS[args.mode]
    if args.max_rounds is None:
        args.max_rounds = defaults["max_rounds"]
    if args.min_rounds is None:
        args.min_rounds = defaults["min_rounds"]
    if args.budget_per_session is None:
        args.budget_per_session = defaults["budget_per_session"]
    return args


def _build_notify_command(message: str, ws: Path | None = None) -> list[str]:
    """Build the notification command. Separated for testability."""
    import shutil
    tn = shutil.which("terminal-notifier")
    if tn:
        cmd = [tn, "-title", "Design Review", "-message", message]
        if ws:
            cmd.extend(["-execute", f"open {ws}"])
        return cmd
    return ["osascript", "-e", f'display notification "{message}" with title "Design Review"']


def _notify(message: str, ws: Path | None = None) -> None:
    try:
        cmd = _build_notify_command(message, ws)
        subprocess.run(cmd, capture_output=True, timeout=5)
    except Exception:
        pass


def _handle_sigterm(signum, frame):
    _log("REVIEW PAUSED: received SIGTERM — parent session likely ended")
    _notify(f"{_REVIEW_NAME or 'unknown'}\nPaused — parent session ended", _REVIEW_WS)
    sys.exit(3)


if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        code = main()
        name = _REVIEW_NAME or "unknown"
        spec = Path(_SPEC_PATH).name if _SPEC_PATH else ""
        label = f"{name}\n{spec}" if spec else name
        if code == 0:
            _log("REVIEW DONE")
            _notify(f"{label}\nReview complete", _REVIEW_WS)
        else:
            _log(f"REVIEW FAILED (exit {code})")
            _notify(f"{label}\nReview failed (exit {code})", _REVIEW_WS)
        sys.exit(code)
    except KeyboardInterrupt:
        _log("REVIEW INTERRUPTED")
        sys.exit(130)
    except ReviewAborted as exc:
        _log(f"REVIEW ABORTED: {exc}")
        spec = Path(_SPEC_PATH).name if _SPEC_PATH else ""
        label = f"{_REVIEW_NAME or 'unknown'}\n{spec}" if spec else (_REVIEW_NAME or "unknown")
        _notify(f"{label}\nReview aborted", _REVIEW_WS)
        sys.exit(2)
    except ReviewPaused as exc:
        _log(f"REVIEW PAUSED: {exc}")
        spec = Path(_SPEC_PATH).name if _SPEC_PATH else ""
        label = f"{_REVIEW_NAME or 'unknown'}\n{spec}" if spec else (_REVIEW_NAME or "unknown")
        _notify(f"{label}\nPaused — needs input", _REVIEW_WS)
        sys.exit(3)
    except Exception as exc:
        _log(f"REVIEW CRASHED: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
