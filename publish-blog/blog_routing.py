#!/usr/bin/env python3
"""
Blog routing engine: load routing config, resolve destinations per entry.

Implements the routing logic from publish-blog/SKILL.md Steps 1-3 and
"Rule semantics".  Read-only — no network, no file mutations.

Ambiguities resolved (matching the 2026-11-19 audit):
  - Workspace `defaults` section REPLACES global defaults (not extends).
    The SKILL.md says destinations and rules extend; it is silent on defaults.
  - `subtype` in a match rule is an exact-match field, same as `entry_type`.
    The SKILL.md Rule Semantics table omits it, but the cc-praxis workspace
    routing uses it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


def _match_project(rule_project: str, entry_projects: list[str]) -> bool:
    """Org-qualified project matching per SKILL.md backward-compat rule.

    When a rule uses ``org/repo``, it matches entry projects containing:
      - the qualified name itself (``casehubio/engine``)
      - any legacy ``<prefix>-<repo>`` form (``casehub-engine``)
      - the bare repo name (``engine``)

    The legacy format uses an org *prefix* that may be shorter than the org
    name (e.g. ``casehub`` for org ``casehubio``), so the check is: does
    the entry project end with ``-<repo>``?
    """
    rp = rule_project.lower()
    for ep in entry_projects:
        epl = ep.lower()
        if epl == rp:
            return True
        if "/" in rule_project:
            _, repo = rp.split("/", 1)
            if epl == repo or epl.endswith(f"-{repo}"):
                return True
        if "/" in ep:
            _, repo = epl.split("/", 1)
            if rp == repo or rp.endswith(f"-{repo}"):
                return True
    return False


SOURCE_KEY = "_source"     # owner/repo the entry's project is published as, set by plan()
_REMOTE_SLUG = re.compile(r"[:/]([^/:\s]+/[^/\s]+?)(?:\.git)?/?$")


def _git_out(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else ""


def source_identity(root: Path) -> str:
    """owner/repo of the project the entries under `root` belong to; "" when unknown.

    `root` is a workspace (its proj link names the project) or the project
    itself. The name is read from the project's git remote, following a
    clone's `local` remote to its canonical repo once, and preferring
    `upstream` over `origin` (the fork convention). It never comes from an
    entry's frontmatter: that line is typed by hand, is often missing, and a
    bare `engine` does not say whose engine it is.
    """
    project = root
    link = root / "proj"
    if link.is_symlink() or link.is_dir():
        try:
            project = link.resolve()
        except OSError:
            project = root
    for _ in range(2):
        remotes = _git_out(project, "remote").split()
        if "local" in remotes and not ({"upstream", "origin"} & set(remotes)):
            canonical = _git_out(project, "remote", "get-url", "local")
            if canonical and Path(canonical).is_dir():
                project = Path(canonical)
                continue
        break
    for name in ("upstream", "origin"):
        url = _git_out(project, "remote", "get-url", name)
        found = _REMOTE_SLUG.search(url) if url else None
        if found and not Path(url).exists():
            return found.group(1)
    return ""


def _identity_matches(rule_project: str, identity: str) -> bool:
    """A rule's project against one qualified owner/repo name.

    `org/repo` matches that repo; `org/*` matches every repo of the org; a
    bare `repo` matches that repo name under any org.
    """
    rule, name = rule_project.lower(), identity.lower()
    if rule.endswith("/*"):
        return name.startswith(rule[:-1])
    if "/" in rule:
        return name == rule
    return name.split("/", 1)[-1] == rule


def _project_matches(rule_project: str, fm: dict[str, Any]) -> bool:
    """Does the entry belong to the rule's project?

    When the entry's source repo is known, it and any fully qualified names in
    the frontmatter are the entry's projects, and nothing else: a bare or
    legacy frontmatter name cannot claim another organisation's rule. Only
    when the source is unknown does the older frontmatter matching apply.
    """
    entry_projects = fm.get("projects") or []
    source = fm.get(SOURCE_KEY, "")
    if not source:
        return _match_project(rule_project, entry_projects)
    identities = [source] + [p for p in entry_projects if isinstance(p, str) and "/" in p]
    return any(_identity_matches(rule_project, i) for i in identities)


def _names_project(rule: dict[str, Any]) -> bool:
    match = rule.get("match", {})
    return "project" in match or "projects" in match


def _rule_matches(rule: dict[str, Any], fm: dict[str, Any]) -> bool:
    """True when every field in `rule["match"]` is satisfied by `fm`."""
    m = rule.get("match", {})
    if "entry_type" in m and m["entry_type"] != fm.get("entry_type", ""):
        return False
    if "subtype" in m and m["subtype"] != fm.get("subtype", ""):
        return False
    if "tags" in m:
        entry_tags = fm.get("tags") or []
        if not any(t in entry_tags for t in m["tags"]):
            return False
    if "projects" in m:
        if not any(_project_matches(rp, fm) for rp in m["projects"]):
            return False
    if "project" in m:
        if not _project_matches(m["project"], fm):
            return False
    return True


class RoutingConfig:
    """Merged routing configuration (global + optional workspace override)."""

    def __init__(
        self,
        destinations: dict[str, dict[str, Any]],
        rules: list[dict[str, Any]],
        defaults: list[str],
    ):
        self.destinations = destinations
        self.rules = rules
        self.defaults = defaults
        # Rules before this index came from the global file; the rest from a
        # workspace override. A config built directly is all global.
        self.global_rule_count = len(rules)

    def resolve_destinations(self, fm: dict[str, Any]) -> set[str]:
        """Return destination names for an entry with frontmatter `fm`.

        A rule that names a project is the config's statement about that
        project, and a rule without one is a fallback by kind of entry. So:

          1. Global rules naming a project that match: the most specific ones
             (most match fields) decide; ties are unioned. An empty list means
             "publish nowhere" and is respected.
          2. Only when no global project rule matched: global rules without a
             project, most specific first, in the same way.
          3. Only when no global rule matched at all: the defaults.
          4. Workspace rules always add to the result: they are that
             workspace's own additions.

        Unioning every matching rule (the earlier behaviour) let a fallback such
        as `entry_type: note -> [personal-notes, casehub-notes]` add an
        organisation's site to an entry whose project rule named only a
        personal one (#569).
        """
        def decide(rules: list[dict[str, Any]]) -> tuple[bool, set[str]]:
            matching = [r for r in rules if _rule_matches(r, fm)]
            if not matching:
                return False, set()
            most = max(len(r.get("match", {})) for r in matching)
            chosen: set[str] = set()
            for r in matching:
                if len(r.get("match", {})) == most:
                    chosen.update(r.get("destinations", []))
            return True, chosen

        global_rules = self.rules[:self.global_rule_count]
        workspace_rules = self.rules[self.global_rule_count:]
        project_rules = [r for r in global_rules if _names_project(r)]
        fallback_rules = [r for r in global_rules if not _names_project(r)]

        matched, result = decide(project_rules)
        if not matched:
            matched, result = decide(fallback_rules)
        _, added = decide(workspace_rules)
        if not matched and not added:
            result = set(self.defaults)
        return result | added

    def dest_path(self, dest_name: str) -> Path:
        """Resolved filesystem path for a destination."""
        d = self.destinations.get(dest_name, {})
        p = Path(d.get("path", "")).expanduser()
        sub = d.get("subdir", "")
        return p / sub if sub else p


def load_routing(
    global_path: Path | None = None,
    workspace_path: Path | None = None,
) -> RoutingConfig:
    """Load and merge routing configs.

    When `workspace_path` is given and contains an `extends:` field, the
    global config is loaded first and the workspace config extends it:
      - destinations: merged (workspace wins on collision)
      - rules: appended
      - defaults: replaced by workspace defaults when present
    """
    if global_path is None:
        global_path = Path("~/.claude/blog-routing.yaml").expanduser()

    if not global_path.is_file():
        return RoutingConfig({}, [], [])

    gc = yaml.safe_load(global_path.read_text()) or {}
    destinations = dict(gc.get("destinations", {}))
    rules = list(gc.get("rules", []))
    defaults = list(gc.get("defaults", {}).get("destinations", []))

    if workspace_path and workspace_path.is_file():
        wc = yaml.safe_load(workspace_path.read_text()) or {}
        destinations.update(wc.get("destinations", {}))
        rules.extend(wc.get("rules", []))
        if "defaults" in wc:
            defaults = list(wc["defaults"].get("destinations", defaults))

    config = RoutingConfig(destinations, rules, defaults)
    config.global_rule_count = len(gc.get("rules", []))
    return config


def parse_frontmatter(path: Path) -> dict[str, Any] | None:
    """Extract YAML frontmatter from a markdown file, or None."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None


def _find_blog_dir(root: Path) -> Path | None:
    """Heuristic: blog/ at root, or docs/blog/ in a project."""
    for candidate in [root / "blog", root / "docs" / "blog"]:
        if candidate.is_dir():
            return candidate
    return None


def plan(
    workspace_or_project: Path,
    routing_path: Path | None = None,
    check_present_fn=None,
    workspace_routing: Path | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    """Resolve every entry's routing and check presence at destinations.

    Returns (entries, missing_pairs, entries_with_missing) where:
      - entries: list of dicts with keys file, source, dest, path, present
      - missing_pairs: subset of entries where present is "no" or "stale"
      - entries_with_missing: deduplicated list of entries that have at
        least one such destination

    present is "yes" when the destination holds the same bytes, "stale" when it
    holds a different version of the entry (the entry was revised after it was
    published), and "no" when it is absent.

    `workspace_routing` names the workspace's override file when the entries
    are read from somewhere other than the workspace itself, such as a
    project's base branch.
    """
    root = workspace_or_project.resolve()
    blog_dir = _find_blog_dir(root)
    if blog_dir is None:
        print(f"WARN=no_blog_dir: {root}", file=sys.stderr)
        return [], [], []

    ws_routing = workspace_routing if workspace_routing is not None else root / "blog-routing.yaml"
    config = load_routing(
        global_path=routing_path if routing_path and routing_path.name != "blog-routing.yaml"
        else None,
        workspace_path=ws_routing if ws_routing.is_file() else None,
    )
    if routing_path and routing_path.name == "blog-routing.yaml":
        config = load_routing(global_path=routing_path, workspace_path=ws_routing if ws_routing.is_file() else None)

    if check_present_fn is None:
        from blog_publish import check_present_fn as _cpf
        check_present_fn = _cpf

    source = source_identity(root)
    if not source:
        print(f"WARN=source_unknown: {root} has no project remote; "
              f"entries are matched by their frontmatter only", file=sys.stderr)

    entries: list[dict[str, str]] = []
    missing_pairs: list[dict[str, str]] = []
    missing_entries: set[str] = set()

    for md in sorted(blog_dir.glob("*.md")):
        if md.name == "INDEX.md":
            continue
        fm, _ = typed_frontmatter(md)

        if source:
            fm = {**fm, SOURCE_KEY: source}
        dests = config.resolve_destinations(fm)
        for dest_name in sorted(dests):
            dest_dir = config.dest_path(dest_name)
            present = check_present_fn(str(md), str(dest_dir))
            state = "yes" if present else "no"
            published = dest_dir / md.name
            if present and published.is_file() and published.read_bytes() != md.read_bytes():
                state = "stale"
            rec = {
                "file": md.name,
                "source": str(md),
                "dest": dest_name,
                "path": str(dest_dir),
                "present": state,
            }
            entries.append(rec)
            if state != "yes":
                missing_pairs.append(rec)
                missing_entries.add(md.name)

    entries_with_missing = [{"file": f} for f in sorted(missing_entries)]
    return entries, missing_pairs, entries_with_missing


KNOWN_ENTRY_TYPES = ("note", "article")
DEFAULT_ENTRY_TYPE = "note"


def typed_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    """An entry's frontmatter with a usable entry_type, and why it was defaulted.

    An entry with no frontmatter, no entry_type, or an entry_type that is not a
    known type (`diary` is a subtype) is a note (#572). Where it goes is decided
    by the repo it lives in, so nothing else needs guessing. The second value
    is "" when the entry already had a known type.
    """
    fm = parse_frontmatter(path)
    if fm is None:
        return {"entry_type": DEFAULT_ENTRY_TYPE}, "no_frontmatter"
    kind = str(fm.get("entry_type") or "").strip().lower()
    if not kind:
        return {**fm, "entry_type": DEFAULT_ENTRY_TYPE}, "no_entry_type"
    if kind not in KNOWN_ENTRY_TYPES:
        return {**fm, "entry_type": DEFAULT_ENTRY_TYPE}, f"unknown_entry_type:{kind}"
    return fm, ""


def defaulted(workspace_or_project: Path) -> list[dict[str, str]]:
    """Entries routed as notes because their metadata did not say what they are.

    They are published like any other note. They are named so the metadata can
    be completed, not because anything is withheld.
    """
    blog_dir = _find_blog_dir(workspace_or_project.resolve())
    if blog_dir is None:
        return []
    found: list[dict[str, str]] = []
    for md in sorted(blog_dir.glob("*.md")):
        if md.name == "INDEX.md":
            continue
        _, reason = typed_frontmatter(md)
        if reason:
            found.append({"file": md.name, "reason": reason})
    return found


def plan_cli(workspace_or_project: str, routing: str | None = None) -> None:
    """CLI wrapper: prints structured output."""
    root = Path(workspace_or_project).expanduser().resolve()
    routing_path = Path(routing).expanduser() if routing else None
    entries, missing_pairs, entries_with_missing = plan(root, routing_path)
    print(f"SOURCE={source_identity(root) or 'unknown'}")

    for e in entries:
        print(f"ENTRY={e['file']} DEST={e['dest']} PATH={e['path']} PRESENT={e['present']}")

    missing_str = " ".join(f"{m['file']}:{m['dest']}" for m in missing_pairs)
    print(f"MISSING={missing_str}" if missing_str else "MISSING=")

    em_str = " ".join(e["file"] for e in entries_with_missing)
    print(f"ENTRIES_MISSING={em_str}" if em_str else "ENTRIES_MISSING=")

    assumed = defaulted(root)
    for entry in assumed:
        print(f"DEFAULTED={entry['file']} AS={DEFAULT_ENTRY_TYPE} REASON={entry['reason']}")
    print(f"DEFAULTED_COUNT={len(assumed)}")
