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
    def test_installs_garden_agent_sh(self):
        with make_garden() as garden:
            result = run_installer(garden)
            agent_sh = Path(garden) / 'garden-agent.sh'
            self.assertTrue(agent_sh.exists(), f"garden-agent.sh not created. stderr: {result.stderr}")
            self.assertTrue(agent_sh.stat().st_mode & 0o111, "garden-agent.sh not executable")
            content = agent_sh.read_text()
            self.assertIn('claude --print', content)
            self.assertIn('HORTORA_GARDEN', content)
            self.assertIn('garden-agent.log', content)


if __name__ == '__main__':
    unittest.main()
