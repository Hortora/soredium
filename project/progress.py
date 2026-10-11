"""Typed progress tracking for lifecycle orchestrators.

Replaces raw dict[str, str] with safe accessors that never crash on
non-numeric values. Backward-compatible serialization to .work-progress.
"""
from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

PROGRESS_FILE = ".work-progress"
PROGRESS_TMP = ".work-progress.tmp"
LEGACY_FILE = ".close-progress"

DONE_VALUES = frozenset({"done", "skipped", "skipped_error"})

_ATTEMPT_SUFFIX = "_attempt"
_PRODUCED_SUFFIX = "_produced"
_MECHANICAL_ATTEMPT_SUFFIX = "_mechanical_attempt"
_LANDED_SHA_PREFIX = "_landed_sha:"


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    SKIPPED_ERROR = "skipped_error"

    def is_complete(self) -> bool:
        return self in (StepStatus.DONE, StepStatus.SKIPPED, StepStatus.SKIPPED_ERROR)


class Progress:
    __slots__ = ("_data",)

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def status(self, step: str) -> StepStatus:
        raw = self._data.get(step, "")
        if raw == "done":
            return StepStatus.DONE
        if raw == "skipped":
            return StepStatus.SKIPPED
        if raw == "skipped_error":
            return StepStatus.SKIPPED_ERROR
        if raw == "running":
            return StepStatus.RUNNING
        return StepStatus.PENDING

    def is_done(self, step: str) -> bool:
        return self._data.get(step, "") in DONE_VALUES

    def mark_done(self, step: str, produced: int = 0) -> None:
        self._data[step] = "done"
        if produced:
            self._data[f"{step}{_PRODUCED_SUFFIX}"] = str(produced)

    def mark_skipped(self, step: str) -> None:
        self._data[step] = "skipped"

    def mark_skipped_error(self, step: str) -> None:
        self._data[step] = "skipped_error"

    def mark_running(self, step: str) -> None:
        self._data[step] = "running"

    def get_attempt(self, step: str) -> int:
        for suffix in (_ATTEMPT_SUFFIX, _MECHANICAL_ATTEMPT_SUFFIX):
            raw = self._data.get(f"{step}{suffix}", "")
            if raw:
                try:
                    return int(raw)
                except (ValueError, TypeError):
                    return 0
        return 0

    def increment_attempt(self, step: str) -> int:
        key = f"{step}{_ATTEMPT_SUFFIX}"
        current = self.get_attempt(step)
        new_val = current + 1
        self._data[key] = str(new_val)
        return new_val

    def reset_attempt(self, step: str) -> None:
        for suffix in (_ATTEMPT_SUFFIX, _MECHANICAL_ATTEMPT_SUFFIX):
            key = f"{step}{suffix}"
            if key in self._data:
                self._data[key] = "0"

    def get_produced(self, step: str) -> int:
        raw = self._data.get(f"{step}{_PRODUCED_SUFFIX}", "")
        try:
            return int(raw) if raw else 0
        except (ValueError, TypeError):
            return 0

    def set_landed_sha(self, repo: str, sha: str) -> None:
        self._data[f"{_LANDED_SHA_PREFIX}{repo}"] = sha

    def get_landed_sha(self, repo: str) -> str:
        return self._data.get(f"{_LANDED_SHA_PREFIX}{repo}", "")

    @property
    def landed_shas(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for k, v in self._data.items():
            if k.startswith(_LANDED_SHA_PREFIX):
                repo = k[len(_LANDED_SHA_PREFIX):]
                result[repo] = v
        return result

    def get(self, key: str, default: str = "") -> str:
        return self._data.get(key, default)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __getitem__(self, key: str) -> str:
        return self._data[key]

    def __setitem__(self, key: str, value: str) -> None:
        self._data[key] = value

    def __iter__(self):
        return iter(self._data)

    def keys(self):
        return self._data.keys()

    def items(self):
        return self._data.items()

    def is_per_repo_done(self, step: str) -> bool:
        prefix = f"{step}:"
        repo_keys = [k for k in self._data
                     if k.startswith(prefix)
                     and not k.endswith(_ATTEMPT_SUFFIX)
                     and not k.endswith(_PRODUCED_SUFFIX)]
        if not repo_keys:
            return False
        return all(self._data[k] in DONE_VALUES for k in repo_keys)

    def as_dict(self) -> dict[str, str]:
        return dict(self._data)

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> Progress:
        p = cls()
        p._data = dict(data)
        return p

    def save(self, workspace: Path) -> None:
        path = workspace / PROGRESS_FILE
        tmp = workspace / PROGRESS_TMP
        lines = [f"{k}={v}" for k, v in self._data.items()]
        tmp.write_text("\n".join(lines) + "\n")
        os.replace(tmp, path)

    @classmethod
    def load(cls, workspace: Path) -> Progress:
        for name in (PROGRESS_FILE, LEGACY_FILE):
            path = workspace / name
            if path.exists():
                data: dict[str, str] = {}
                for line in path.read_text().splitlines():
                    if "=" in line:
                        k, _, v = line.partition("=")
                        data[k.strip()] = v.strip()
                return cls.from_dict(data)
        return cls()
