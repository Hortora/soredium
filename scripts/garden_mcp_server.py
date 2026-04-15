#!/usr/bin/env python3
"""
garden_mcp_server.py — Hortora Knowledge Garden MCP Server.

Exposes three tools via FastMCP:
  garden_search  — 3-tier retrieval: find entries by query + technology filter
  garden_capture — Submit a new entry as a git branch (ready to PR)
  garden_status  — Garden health: entry count, drift, last sweep

Usage (stdio transport):
  python3 garden_mcp_server.py

Configure in Claude Desktop / Cursor / Copilot:
  {
    "mcpServers": {
      "hortora-garden": {
        "command": "python3",
        "args": ["/path/to/soredium/scripts/garden_mcp_server.py"],
        "env": {"HORTORA_GARDEN": "/path/to/your/garden"}
      }
    }
  }
"""

import os
import sys
from pathlib import Path

# Ensure sibling scripts are importable
sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.fastmcp import FastMCP
from mcp_garden_search import search_garden
from mcp_garden_status import get_status
from mcp_garden_capture import capture_entry

_DEFAULT_GARDEN = Path(
    os.environ.get('HORTORA_GARDEN', str(Path.home() / '.hortora' / 'garden'))
).expanduser().resolve()

mcp = FastMCP("Hortora Garden")


@mcp.tool()
def garden_search(
    query: str,
    technology: str = None,
    domain: str = None,
    garden_path: str = None,
) -> list:
    """Search the knowledge garden for entries matching a query.

    Uses 3-tier retrieval:
    1. Technology/domain filter via GARDEN.md index
    2. Keyword match in filtered entries
    3. Full-text grep across domain if no index matches

    Args:
        query: Keywords describing the problem or symptom
        technology: Filter by technology heading (e.g. "Java", "Python")
        domain: Filter by domain directory name (e.g. "java", "tools")
        garden_path: Override default garden path ($HORTORA_GARDEN)

    Returns:
        List of matching entries with id, title, domain, score, body fields
    """
    garden = Path(garden_path).expanduser().resolve() if garden_path else _DEFAULT_GARDEN
    return search_garden(garden, query, technology=technology, domain=domain)


@mcp.tool()
def garden_status(garden_path: str = None) -> dict:
    """Get garden health and metadata.

    Args:
        garden_path: Override default garden path ($HORTORA_GARDEN)

    Returns:
        Dict with entry_count, drift, threshold, dedupe_recommended,
        last_sweep, last_staleness_review, role, name, garden_path
    """
    garden = Path(garden_path).expanduser().resolve() if garden_path else _DEFAULT_GARDEN
    return get_status(garden)


@mcp.tool()
def garden_capture(
    title: str,
    type: str,
    domain: str,
    stack: str,
    tags: list,
    score: int,
    body: str,
    garden_path: str = None,
) -> dict:
    """Submit a new knowledge entry to the garden.

    Creates a git branch with the entry ready for PR review.
    Score must be >= 8. Type must be gotcha, technique, or undocumented.

    Args:
        title: Short imperative title describing the non-obvious thing
        type: Entry type — gotcha | technique | undocumented
        domain: Domain directory (e.g. java, python, tools)
        stack: Technology and version (e.g. "Quarkus 3.9.x, Java 21")
        tags: List of tag strings
        score: Self-assessed score 8-15
        body: Entry body markdown with symptom, root cause, fix, why non-obvious
        garden_path: Override default garden path ($HORTORA_GARDEN)

    Returns:
        Dict with status (ok/error), ge_id, branch, message
    """
    garden = Path(garden_path).expanduser().resolve() if garden_path else _DEFAULT_GARDEN
    return capture_entry(garden, title=title, type=type, domain=domain,
                         stack=stack, tags=tags, score=score, body=body)


if __name__ == '__main__':
    mcp.run()
