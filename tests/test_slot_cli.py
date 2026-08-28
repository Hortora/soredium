"""Tests for work-slot/slot_cli.py"""

import sys
from pathlib import Path

import pytest

skill_dir = Path(__file__).parent.parent / "work-slot"
sys.path.insert(0, str(skill_dir))

import slot_cli


class TestCLI:
    def test_parse_args_create(self):
        sys.argv = ["slot_manager.py", "create-slot", "/path/to/family",
                     "repos=engine,iot", "branch=issue-42"]
        args = slot_cli.parse_args()
        assert args["subcommand"] == "create-slot"
        assert args["target"] == "/path/to/family"
        assert args["repos"] == "engine,iot"

    def test_parse_args_list(self):
        sys.argv = ["slot_manager.py", "list-slots", "/path/to/family"]
        args = slot_cli.parse_args()
        assert args["subcommand"] == "list-slots"
        assert args["target"] == "/path/to/family"

    def test_missing_repos_error(self, capsys):
        sys.argv = ["slot_manager.py", "create-slot", "/path"]
        with pytest.raises(SystemExit):
            slot_cli.main()
        captured = capsys.readouterr()
        assert "ERROR=missing_repos" in captured.out

    def test_missing_slot_number_error(self, capsys):
        sys.argv = ["slot_manager.py", "remove-slot", "/path"]
        with pytest.raises(SystemExit):
            slot_cli.main()
        captured = capsys.readouterr()
        assert "ERROR=missing_slot_number" in captured.out

