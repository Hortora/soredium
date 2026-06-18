#!/usr/bin/env python3
"""Shared utilities for workspace-init scripts."""


def parse_args(args: list[str]) -> dict[str, str]:
    """Parse key=value arguments from CLI args."""
    result: dict[str, str] = {}
    for arg in args:
        if "=" in arg:
            k, _, v = arg.partition("=")
            result[k.strip()] = v.strip()
    return result
