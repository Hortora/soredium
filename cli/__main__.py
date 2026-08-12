"""CLI entry point: python -m cli <command> [args...]

Executes lifecycle commands and emits results as JSON Lines to stdout.
Each line is a JSON object with a "type" field identifying the event class.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict

COMMANDS = {
    "brief", "continue", "start", "next", "end", "pause", "resume",
    "quick-fix", "what-next", "status", "abort",
}


def emit(event) -> None:
    d = asdict(event)
    d["type"] = type(event).__name__
    print(json.dumps(d), flush=True)


def _parse_args(cmd: str, args: list[str]) -> dict:
    kwargs: dict = {}
    if cmd == "start":
        kwargs["issues"] = [int(a.lstrip("#")) for a in args if a.lstrip("#").isdigit()]
    elif cmd == "quick-fix":
        filtered = [a for a in args if a != "--yes"]
        kwargs["message"] = " ".join(filtered)
    elif cmd == "resume" and args:
        kwargs["branch"] = args[0]
    return kwargs


def _interactive_decide(prompt: str) -> bool:
    print(prompt, file=sys.stderr, end=" [y/N] ")
    return input().strip().lower() in ("y", "yes")


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: soredium <command> [args...]", file=sys.stderr)
        print(f"Commands: {', '.join(sorted(COMMANDS))}", file=sys.stderr)
        return 2

    if sys.argv[1] in ("-h", "--help"):
        print("Usage: soredium <command> [args...]")
        print(f"Commands: {', '.join(sorted(COMMANDS))}")
        return 0

    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        return 2

    import importlib
    cmd_name = cmd.replace("-", "_")
    try:
        mod = importlib.import_module(f"commands.{cmd_name}")
    except ImportError:
        print(f"Command module not found: commands.{cmd_name}", file=sys.stderr)
        return 2

    yes_mode = "--yes" in sys.argv or not sys.stdin.isatty()
    decide_fn = None if yes_mode else _interactive_decide

    try:
        kwargs = _parse_args(cmd, sys.argv[2:])
        sig = mod.execute.__code__.co_varnames[:mod.execute.__code__.co_argcount]
        if "decide_fn" in sig:
            kwargs["decide_fn"] = decide_fn
        result = mod.execute(**kwargs)

        if isinstance(result, list):
            for event in result:
                emit(event)
        else:
            emit(result)
        return 0
    except Exception as e:
        from commands.events import CommandFailed
        emit(CommandFailed(cmd, None, "exception", str(e), False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
