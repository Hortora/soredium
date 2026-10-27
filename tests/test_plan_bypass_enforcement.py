"""Static analysis: detect .plan bypass writers.

Pytest wrapper for scripts/validation/validate_plan_bypass.py.
Runs at commit tier via validate_all.py; also runnable via pytest.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "validation"))

from validate_plan_bypass import main


def test_no_plan_bypass_writers():
    """No Python file outside canonical writers may directly manipulate .plan."""
    result = main()
    assert result == 0, ".plan bypass writers detected (see stdout for details)"
