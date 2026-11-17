#!/usr/bin/env python3
"""PreToolUse hook for Bash: block `git push` from a slot clone or of a working branch.

Landing Rules (soredium CLAUDE.md): only the canonical repo publishes, and it
publishes its base branch. Work reaches canonical with `work end`; canonical
reaches the remote with `canonical_sync.py publish`.

Blocked:
  - any `git push` in a slot clone (a repo whose parent directory holds a .slot
    file, or that names its canonical repo with a `local` remote)
  - a push of anything but the base branch (main or master) from any repo
  - `git push --all` and `git push --mirror`, which push every branch

Allowed:
  - a push of the base branch from a canonical repo
  - pushes of tags only, deletions, `--dry-run`, and `git push --help`
  - everything that is not a `git push`

Claude Code blocks a tool call only on exit code 2 with the reason on stderr.
Printing "BLOCK" to stdout and exiting 0 blocks nothing. Any failure inside
this hook exits 0: a broken guard must not stop unrelated work.
"""
import json
import os
import re
import shlex
import subprocess
import sys

BASE_BRANCHES = ("main", "master")
PUBLISH = "python3 ~/.claude/skills/project/canonical_sync.py publish <repo>"
_SEPARATORS = {"&&", "||", ";", "|", "&", "(", ")", "{", "}"}
_GIT_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
_PUSH_FLAGS_WITH_VALUE = {"--repo", "-o", "--push-option", "--receive-pack", "--exec",
                          "--force-with-lease", "--recurse-submodules"}


def _git(repo, *args):
    try:
        result = subprocess.run(["git", "-C", repo, *args],
                                capture_output=True, text=True, timeout=5)
    except Exception:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _segments(command):
    """Split a shell command line into simple commands, each a list of words."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars="&|;(){}")
    lexer.whitespace_split = True
    lexer.commenters = ""
    segment = []
    for token in lexer:
        if token in _SEPARATORS or set(token) <= set("&|;"):
            if segment:
                yield segment
            segment = []
        else:
            segment.append(token)
    if segment:
        yield segment


def _find_pushes(command, cwd):
    """Yield (repo directory, push arguments) for every `git push` in the command."""
    directory = cwd
    for words in _segments(command):
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words = words[1:]                       # VAR=value prefixes
        if not words:
            continue
        if words[0] == "cd" and len(words) > 1:
            directory = os.path.join(directory, os.path.expanduser(words[1]))
            continue
        if os.path.basename(words[0]) != "git":
            continue
        repo = directory
        index = 1
        while index < len(words) and words[index].startswith("-"):
            flag = words[index]
            if flag in _GIT_GLOBAL_WITH_VALUE and index + 1 < len(words):
                if flag == "-C":
                    repo = os.path.join(repo, os.path.expanduser(words[index + 1]))
                index += 2
            else:
                index += 1
        if index < len(words) and words[index] == "push":
            yield repo, words[index + 1:]


def _is_slot_clone(repo):
    top = _git(repo, "rev-parse", "--show-toplevel")
    if not top:
        return False
    if os.path.exists(os.path.join(os.path.dirname(top), ".slot")):
        return True
    return bool(_git(repo, "remote", "get-url", "local"))


def _verdict(repo, args):
    """Why this push is refused, or None when it is allowed."""
    flags = set()
    positional = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg.startswith("-") and arg != "-":
            name = arg.split("=", 1)[0]
            flags.add(name)
            if name in _PUSH_FLAGS_WITH_VALUE and "=" not in arg and name not in (
                    "--force-with-lease", "--recurse-submodules"):
                skip = True
            continue
        positional.append(arg)

    if flags & {"--help", "-h", "--dry-run", "-n"}:
        return None
    if flags & {"--delete", "-d"}:
        return None                                  # removes a remote ref; publishes nothing
    if not _git(repo, "rev-parse", "--git-dir"):
        return None                                  # not a repo: git will say so itself

    if _is_slot_clone(repo):
        return ("this is a slot clone, and a slot never pushes. Its commits are already "
                "backed up through the canonical repo by the post-commit hook.")
    if flags & {"--all", "--mirror", "--branches"}:
        return "this would push every branch; only the base branch is ever published."

    refspecs = positional[1:]
    if not refspecs:
        if flags & {"--tags"}:
            return None
        branch = _git(repo, "symbolic-ref", "-q", "--short", "HEAD")
        targets = [branch] if branch else []
    else:
        targets = []
        for spec in refspecs:
            spec = spec.lstrip("+")
            source, _, destination = spec.partition(":")
            if not source and destination:
                continue                              # deletion
            name = destination or source
            if name == "HEAD":
                name = _git(repo, "symbolic-ref", "-q", "--short", "HEAD")
            if name.startswith("refs/tags/") or name == "tag":
                continue
            if _git(repo, "rev-parse", "-q", "--verify", f"refs/tags/{name}") and \
                    not _git(repo, "rev-parse", "-q", "--verify", f"refs/heads/{name}"):
                continue                              # a tag name
            targets.append(name.removeprefix("refs/heads/"))

    for name in targets:
        if name and name not in BASE_BRANCHES:
            return (f"'{name}' is a working branch, and working branches are never pushed. "
                    f"Only the base branch is published.")
    return None


def main():
    try:
        payload = json.load(sys.stdin)
        if payload.get("tool_name", "Bash") != "Bash":
            return 0
        command = (payload.get("tool_input") or {}).get("command", "")
        if "push" not in command or "git" not in command:
            return 0
        cwd = payload.get("cwd") or os.getcwd()
        for repo, args in _find_pushes(command, cwd):
            reason = _verdict(repo, args)
            if reason:
                print(f"BLOCK: git push refused: {reason}\n"
                      f"Land work on disk with `work end`. Publish the canonical repo's base "
                      f"branch, when the user asks, with: {PUBLISH}",
                      file=sys.stderr)
                return 2
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
