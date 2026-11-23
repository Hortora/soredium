"""Decide what `work continue` (or `work next`) runs, from the queue alone.

To the user there is one command: carry on. `work`, `work start` without an
issue, `work continue` and `work next` are spellings of it. Whether that means continuing the active item, picking up the item
a branch belongs to, starting the next one or closing what is finished is state
the queue already holds, so it is decided here and never by the caller.

The one thing the queue cannot know is that the active item is finished. A
session that has finished it says so with `done`; nothing else marks an item
done, so typing `next` on unfinished work loses nothing.

Pure: reads its arguments, touches nothing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from queue_io import Queue, QueueItem

ROUTED = ("start", "continue", "next", "done")


@dataclass(frozen=True)
class Route:
    run: str = ""        # pipeline to run; "" when nothing runs
    reason: str = ""
    activate: str = ""   # open item to make active before running
    issue: str = ""      # the item the route concerns
    title: str = ""
    stop: str = ""       # "", "end", "nothing" or "decision"
    detail: str = ""
    offer: bool = False  # finished items are waiting: weigh wrapping up
    next_item: str = ""
    next_title: str = ""
    next_scale: str = ""
    next_complexity: str = ""
    done_waiting: int = 0


def _number(ref: str) -> str:
    return ref.rpartition("#")[2]


def _branch_issue(branch: str) -> str:
    m = re.match(r"issue-(\d+)(?:-|$)", branch)
    return m.group(1) if m else ""


def _open(queue: Queue) -> list[QueueItem]:
    return [i for i in queue.items
            if not i.completed and not i.active and not i.done_branch]


def _enrich_offer(r: Route, queue: Queue) -> Route:
    if not r.offer:
        return r
    open_items = _open(queue)
    nxt = open_items[0] if open_items else None
    return Route(
        run=r.run, reason=r.reason, activate=r.activate, issue=r.issue,
        title=r.title, stop=r.stop, detail=r.detail, offer=r.offer,
        next_item=nxt.ref if nxt else "",
        next_title=nxt.title if nxt else "",
        next_scale=(getattr(nxt, "scale", "") or "unknown") if nxt else "",
        next_complexity=(getattr(nxt, "complexity", "") or "unknown") if nxt else "",
        done_waiting=len(queue.done_items()),
    )


def route(command: str, queue: Optional[Queue], branch: str, base_branch: str,
          stack_depth: int = 0) -> Route:
    if command not in ROUTED or queue is None:
        return Route(run=command, reason="direct" if command not in ROUTED else "no_queue")

    done = queue.done_items()
    n_done = len(done)
    active = queue.active_item()
    on_base = not branch or branch == base_branch
    on_finished_branch = any(i.done_branch == branch for i in done)

    result: Route

    if active is not None:
        if command == "done":
            result = Route(run="done", reason="mark_done", issue=active.ref,
                           title=active.title, offer=True, done_waiting=n_done)
        elif command in ("start", "next"):
            result = Route(stop="decision", reason="current_item_not_released",
                           issue=active.ref, title=active.title, done_waiting=n_done,
                           detail=f"{active.ref} is active; release it before moving on")
        elif on_base or on_finished_branch:
            if not queue.state.branch:
                result = Route(run="start", reason="active_item_not_started",
                               issue=active.ref, title=active.title, done_waiting=n_done)
            else:
                result = Route(stop="decision", reason="active_branch_not_checked_out",
                               issue=active.ref, done_waiting=n_done,
                               detail=f"{active.ref} is active on {queue.state.branch}, "
                                      f"which is not the branch checked out")
        else:
            result = Route(run="continue", reason="active_work", issue=active.ref,
                           title=active.title, done_waiting=n_done)
    else:
        open_items = _open(queue)

        if not on_base and not on_finished_branch:
            number = _branch_issue(branch)
            matches = [i for i in open_items if number and _number(i.ref) == number]
            if len(matches) == 1:
                item = matches[0]
                result = Route(run="continue", reason="branch_item_activated",
                               activate=item.ref, issue=item.ref, title=item.title,
                               done_waiting=n_done)
            elif not matches:
                result = Route(stop="decision", reason="branch_matches_no_open_item",
                               detail=f"on {branch}, which belongs to no open queue item",
                               done_waiting=n_done)
            else:
                result = Route(stop="decision", reason="branch_matches_several_items",
                               detail=f"on {branch}; open items "
                                      f"{', '.join(i.ref for i in matches)} all carry that number",
                               done_waiting=n_done)
        elif on_base and stack_depth > 0:
            result = Route(run="resume", reason="paused_work", done_waiting=n_done,
                           detail=f"{stack_depth} paused branch(es) on the stack")
        elif open_items:
            item = open_items[0]
            result = Route(run="start", reason="next_open_item", activate=item.ref,
                           issue=item.ref, title=item.title, done_waiting=n_done)
        elif done:
            result = Route(stop="nothing", reason="done_items_informational",
                           detail=f"{len(done)} finished item(s) waiting; run work end when ready",
                           done_waiting=n_done)
        else:
            result = Route(stop="nothing", reason="queue_empty",
                           detail="the queue has no open item; find work or name an issue")

    return _enrich_offer(result, queue)
