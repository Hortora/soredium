#!/usr/bin/env python3
"""Tests for garden-agent-install.sh."""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

INSTALLER = Path(__file__).parent.parent / 'scripts' / 'garden-agent-install.sh'


def make_garden() -> TemporaryDirectory:
    """Create a temp directory with a bare git repo (simulates a garden)."""
    tmp = TemporaryDirectory()
    env = {**os.environ, 'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@test.com',
           'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 'test@test.com'}
    subprocess.run(['git', 'init', tmp.name], check=True, capture_output=True)
    (Path(tmp.name) / 'GARDEN.md').write_text('# Garden\n')
    subprocess.run(['git', '-C', tmp.name, 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', tmp.name, 'commit', '-m', 'init'], check=True, capture_output=True, env=env)
    return tmp


def run_installer(garden_path: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['bash', str(INSTALLER)],
        capture_output=True, text=True,
        cwd=garden_path
    )


class TestGardenAgentInstall(unittest.TestCase):
    pass


if __name__ == '__main__':
    unittest.main()
