"""
Shared base classes for tests requiring temporary directories.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class TempDirTestCase(unittest.TestCase):
    """Base class for tests that need a single temporary directory."""

    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.test_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()


class DualTempDirTestCase(unittest.TestCase):
    """Base class for tests that need a repo dir + a skills dir."""

    def setUp(self):
        self.repo_tmp = TemporaryDirectory()
        self.skills_tmp = TemporaryDirectory()
        self.repo = Path(self.repo_tmp.name)
        self.skills = Path(self.skills_tmp.name)

    def tearDown(self):
        self.repo_tmp.cleanup()
        self.skills_tmp.cleanup()
