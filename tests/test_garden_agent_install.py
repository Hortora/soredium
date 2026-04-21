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

    def test_installs_settings_json(self):
        import json
        with make_garden() as garden:
            result = run_installer(garden)
            settings = Path(garden) / '.claude' / 'settings.json'
            self.assertTrue(settings.exists(), f"settings.json not created. stderr: {result.stderr}")
            data = json.loads(settings.read_text())
            self.assertEqual(data.get('defaultMode'), 'acceptEdits')
            allowed = data['permissions']['allow']
            self.assertTrue(any('dedupe_scanner.py' in r for r in allowed))
            self.assertTrue(any('git commit' in r for r in allowed))

    def test_installs_claude_md(self):
        with make_garden() as garden:
            result = run_installer(garden)
            claude_md = Path(garden) / 'CLAUDE.md'
            self.assertTrue(claude_md.exists(), f"CLAUDE.md not created. stderr: {result.stderr}")
            content = claude_md.read_text()
            self.assertIn('garden deduplication agent', content)
            self.assertIn('dedupe_scanner.py', content)
            self.assertIn('duplicate-discarded', content)
            self.assertIn('git show HEAD:', content)

    def test_installs_post_commit_hook(self):
        with make_garden() as garden:
            result = run_installer(garden)
            hook = Path(garden) / '.git' / 'hooks' / 'post-commit'
            self.assertTrue(hook.exists(), f"post-commit hook not created. stderr: {result.stderr}")
            self.assertTrue(hook.stat().st_mode & 0o111, "post-commit hook not executable")
            content = hook.read_text()
            self.assertIn('garden-agent.sh', content)
            self.assertIn('GE-', content)

    def test_post_commit_hook_idempotent(self):
        with make_garden() as garden:
            run_installer(garden)
            run_installer(garden)  # second run
            hook = Path(garden) / '.git' / 'hooks' / 'post-commit'
            content = hook.read_text()
            self.assertEqual(content.count('garden-agent.sh'), 1)

    def test_post_commit_hook_appends_to_existing(self):
        with make_garden() as garden:
            hook = Path(garden) / '.git' / 'hooks' / 'post-commit'
            hook.write_text('#!/bin/bash\n# existing hook\necho "existing"\n')
            hook.chmod(0o755)
            run_installer(garden)
            content = hook.read_text()
            self.assertIn('existing', content)
            self.assertIn('garden-agent.sh', content)


if __name__ == '__main__':
    unittest.main()
