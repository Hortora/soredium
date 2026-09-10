"""JSON Lines CLI wrapper for soredium commands.

Bridges Python command modules to Java subprocess callers.
Each command event is serialised as a JSON Lines record to stdout.

Usage: python3 -m cli <command> [json-kwargs]
"""
import json
import sys
from dataclasses import asdict, fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "work-slot"))

from commands import events


def _serialise_event(event) -> str:
    type_name = type(event).__name__
    data = {}
    for field in fields(event):
        val = getattr(event, field.name)
        if hasattr(val, "__dataclass_fields__"):
            val = asdict(val)
        elif isinstance(val, list) and val and hasattr(val[0], "__dataclass_fields__"):
            val = [asdict(v) for v in val]
        data[field.name] = val
    return json.dumps({"type": type_name, "data": data})


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"type": "CommandFailed", "data": {
            "command": "", "step": None,
            "error": "Usage: python3 -m cli <command> [json-kwargs]",
            "detail": "", "recoverable": False
        }}))
        sys.exit(1)

    command = sys.argv[1]
    kwargs = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

    try:
        import importlib
        mod = importlib.import_module(f"commands.{command}")
        result = mod.execute(**kwargs)

        exit_code = 0
        if isinstance(result, list):
            for event in result:
                print(_serialise_event(event), flush=True)
                if isinstance(event, events.CommandFailed) and not event.recoverable:
                    exit_code = 1
        else:
            print(_serialise_event(result), flush=True)

        sys.exit(exit_code)
    except ModuleNotFoundError:
        print(json.dumps({"type": "CommandFailed", "data": {
            "command": command, "step": None,
            "error": f"Unknown command: {command}",
            "detail": "", "recoverable": False
        }}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"type": "CommandFailed", "data": {
            "command": command, "step": None,
            "error": str(e), "detail": "", "recoverable": False
        }}))
        sys.exit(1)


if __name__ == "__main__":
    main()
