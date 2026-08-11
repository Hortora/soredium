"""Tests for scripts/enrichment.py library API — WhatNextItem dataclass."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from enrichment import WhatNextItem


def test_what_next_item_dataclass():
    item = WhatNextItem(42, "Fix scoring", 0.85, "quick-win", "ready",
                        "quick-win, ready")
    assert item.issue_number == 42
    assert item.strategic_role == "quick-win"
    assert item.score == 0.85


def test_what_next_item_none_fields():
    item = WhatNextItem(55, "Add caching", 0.0, None, None, None)
    assert item.strategic_role is None
    assert item.reason is None


def test_format_reason():
    from enrichment import _format_reason
    assert _format_reason({"strategic_role": "quick-win", "readiness": "ready", "decay": "stable"}) == "quick-win, ready, stable"
    assert _format_reason({"strategic_role": "load-bearing"}) == "load-bearing"
    assert _format_reason({}) is None
