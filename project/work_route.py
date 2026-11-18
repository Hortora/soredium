"""Decide what `work continue` (or `work next`) runs, from the queue alone.

To the user there is one command: carry on. Whether that means continuing the
active item, picking up the item a branch belongs to, starting the next one or
closing what is finished is state the queue already holds, so it is decided
here and never by the caller. The one thing the queue cannot know is that the
active item is finished; `next` is how a session says so.

Pure: reads its arguments, touches nothing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from queue_io import Queue, QueueItem

ROUTED = ("continue", "next")


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


def _number(ref: str) -> str:
    return ref.rpartition("#")[2]


def _branch_issue(branch: str) -> str:
    m = re.match(r"issue-(\d+)(?:-|$)", branch)
    return m.group(1) if m else ""


def _open(queue: Queue) -> list[QueueItem]:
    return [i for i in queue.items
            if not i.completed and not i.active and not i.done_branch]


def route(command: str, queue: Optional[Queue], branch: str, base_branch: str) -> Route:
    if command not in ROUTED or queue is None:
        return Route(run=command, reason="direct" if command not in ROUTED else "no_queue")

    done = queue.done_items()
    offer = bool(done)
    active = queue.active_item()
    if active is not None:
        if command == "next":
            return Route(run="next", reason="mark_done", issue=active.ref,
                         title=active.title, offer=True)
        return Route(run="continue", reason="active_work", issue=active.ref,
                     title=active.title, offer=offer)

    open_items = _open(queue)
    on_base = not branch or branch == base_branch
    on_finished_branch = any(i.done_branch == branch for i in done)

    if not on_base and not on_finished_branch:
        number = _branch_issue(branch)
        matches = [i for i in open_items if number and _number(i.ref) == number]
        if len(matches) == 1:
            item = matches[0]
            return Route(run="continue", reason="branch_item_activated",
                         activate=item.ref, issue=item.ref, title=item.title, offer=offer)
        if not matches:
            return Route(stop="decision", reason="branch_matches_no_open_item",
                         detail=f"on {branch}, which belongs to no open queue item",
                         offer=offer)
        return Route(stop="decision", reason="branch_matches_several_items",
                     detail=f"on {branch}; open items "
                            f"{', '.join(i.ref for i in matches)} all carry that number",
                     offer=offer)

    if open_items:
        item = open_items[0]
        return Route(run="start", reason="next_open_item", activate=item.ref,
                     issue=item.ref, title=item.title, offer=offer)
    if done:
        return Route(stop="end", reason="done_items_await_close",
                     detail=f"{len(done)} finished item(s) are waiting to be closed",
                     offer=True)
    return Route(stop="nothing", reason="queue_empty",
                 detail="the queue has no open item")
