"""Content area — scrollable output from the last command."""
from __future__ import annotations

from textual.widgets import RichLog

from commands.events import (
    BriefReady, StepProgress, CommandFailed, StatusReady,
    WhatNextReady, WorkEnded, PlanAdvanced, ContinueReady,
)


class ContentArea(RichLog):
    DEFAULT_CSS = """
    ContentArea {
        padding: 1;
    }
    """

    def format_brief(self, brief: BriefReady) -> list[str]:
        lines = []
        if brief.issue:
            lines.append(f"Issue: #{brief.issue}")
        else:
            lines.append("No active issue")
        lines.append(f"Branch: {brief.branch}")
        lines.append(f"State: {brief.state}")
        if brief.queue_position:
            lines.append(f"Queue: {brief.queue_position}")
        if brief.is_epic and brief.epic_batch:
            lines.append(f"Epic batch: {brief.epic_batch}")
        lines.append("")
        for h in brief.health:
            icon = "✓" if h.status == "ok" else "⚠" if h.status == "warn" else "✗"
            detail = f" — {h.detail}" if h.detail else ""
            lines.append(f"  {icon} {h.check}{detail}")
        return lines

    def format_step_progress(self, step: StepProgress) -> str:
        detail = f" — {step.detail}" if step.detail else ""
        return f"  ✓ {step.step}{detail}"

    def format_error(self, failed: CommandFailed) -> list[str]:
        lines = [f"  ✗ {failed.command} failed"]
        if failed.step:
            lines.append(f"    Step: {failed.step}")
        lines.append(f"    Error: {failed.detail}")
        if failed.recoverable:
            lines.append("    (retry available)")
        return lines

    def format_status(self, status: StatusReady) -> list[str]:
        lines = [
            f"Branch: {status.branch}",
            f"State: {status.state}",
            f"On main: {'yes' if status.on_main else 'no'}",
            f"In slot: {'yes' if status.in_slot else 'no'}",
        ]
        if status.has_plan and status.plan_position:
            lines.append(f"Queue: {status.plan_position}")
        if status.stack_depth > 0:
            lines.append(f"Paused branches: {status.stack_depth}")
        if status.owner_repo:
            lines.append(f"Repo: {status.owner_repo}")
        lines.append(f"Base: {status.base_branch}")
        return lines

    def format_what_next(self, wn: WhatNextReady) -> list[str]:
        if not wn.recommendations:
            return ["No recommendations available."]
        lines = ["Recommended next:", ""]
        for i, rec in enumerate(wn.recommendations, 1):
            parts = [f"  {i}. #{rec.issue} — {rec.title}"]
            tags = []
            if rec.strategic_role:
                tags.append(rec.strategic_role)
            if rec.readiness:
                tags.append(rec.readiness)
            if tags:
                parts.append(f"     ({', '.join(tags)})")
            if rec.reason:
                parts.append(f"     {rec.reason}")
            lines.extend(parts)
        return lines

    def format_work_ended(self, ended: WorkEnded) -> list[str]:
        issues = ", ".join(f"#{i}" for i in ended.issues_closed)
        return [
            f"Branch {ended.branch} closed.",
            f"Issues closed: {issues}" if issues else "No issues closed.",
        ]

    def format_plan_advanced(self, advanced: PlanAdvanced) -> list[str]:
        lines = [f"Completed: #{advanced.completed_issue}"]
        if advanced.next_issue:
            lines.append(f"Next: #{advanced.next_issue} — {advanced.next_title or ''}")
        lines.append(f"Position: {advanced.position}")
        if advanced.queue_complete:
            lines.append("Queue complete.")
        return lines

    def format_continue(self, cont: ContinueReady) -> list[str]:
        lines = []
        if cont.issue:
            lines.append(f"Issue: #{cont.issue}")
        lines.append(f"Branch: {cont.branch}")
        lines.append(f"State: {cont.state}")
        if cont.handoff_summary:
            lines.append("")
            lines.append("Last session:")
            for line in cont.handoff_summary.splitlines()[:10]:
                lines.append(f"  {line}")
        if cont.done_detected:
            lines.append("")
            if cont.suggest_next:
                lines.append("Current issue complete — run 'next' to advance.")
            elif cont.suggest_end:
                lines.append("All issues complete — run 'end' to close.")
        return lines

    def show_event(self, event) -> None:
        if isinstance(event, BriefReady):
            for line in self.format_brief(event):
                self.write(line)
        elif isinstance(event, StepProgress):
            self.write(self.format_step_progress(event))
        elif isinstance(event, CommandFailed):
            for line in self.format_error(event):
                self.write(line)
        elif isinstance(event, StatusReady):
            for line in self.format_status(event):
                self.write(line)
        elif isinstance(event, WhatNextReady):
            for line in self.format_what_next(event):
                self.write(line)
        elif isinstance(event, WorkEnded):
            for line in self.format_work_ended(event):
                self.write(line)
        elif isinstance(event, PlanAdvanced):
            for line in self.format_plan_advanced(event):
                self.write(line)
        elif isinstance(event, ContinueReady):
            for line in self.format_continue(event):
                self.write(line)
