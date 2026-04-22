# soredium

The engine for Hortora gardens — validators, CI scripts, GitHub Actions workflows, and Claude skills.

> A soredium is a lichen's dispersal unit: a self-contained bundle that carries everything needed to establish a new colony wherever it lands.

---

## What's in here

### Claude Skills

| Skill | Purpose |
|-------|---------|
| `forage` | Session-time capture, search, and retrieval. CAPTURE writes the entry, validates locally, commits, and pushes directly to main. SWEEP scans a session for all three entry types (gotchas, techniques, undocumented) and delivers as a single batch commit. SEARCH uses `git grep` for fast on-demand retrieval. REVISE enriches an existing entry in place. |
| `harvest` | Dedicated maintenance sessions. DEDUPE sweeps the full garden for near-duplicates. REVIEW surfaces stale entries overdue for a freshness check. |

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/validate_pr.py` | Validates a single garden entry. Checks required fields, score threshold (≥ 8), prompt injection patterns, Jaccard duplicate scan (≥ 0.4 = warning), vocabulary compliance. Exits 1 on CRITICAL failures. Called by forage before committing. |
| `scripts/validate_garden.py` | Full garden validation — structural checks, entry format, index consistency (GARDEN.md vs actual files). Recognises both legacy `**ID:**` body format and current YAML `id:` frontmatter. |
| `scripts/dedupe_scanner.py` | Scans all entry pairs for semantic similarity. Outputs ranked unchecked pairs. Records classifications (distinct / related / duplicate-discarded) in `CHECKED.md`. |
| `scripts/garden-agent-install.sh` | Installs the autonomous garden agent into a local garden clone. Idempotent — safe to re-run. See [Garden Agent](#garden-agent) below. |
| `scripts/garden-setup.sh` | One-time sparse blobless clone setup. Index files materialised; entry bodies fetched on demand via `git cat-file`. |
| `scripts/integrate_entry.py` | Updates garden indexes after entry changes: domain `INDEX.md`, `labels/`, `_index/global.md`. |
| `scripts/claude-skill` | Skill installer — `install`, `sync-local`, `uninstall`. |

---

## How submissions work

```
forage CAPTURE / SWEEP
  → write GE-YYYYMMDD-xxxxxx.md
  → validate_pr.py           # format, score, Jaccard, injection check
  → git commit + git pull --rebase origin main + git push origin main
  → post-commit hook fires garden agent (async)
    → git pull               # pull any other concurrent entries
    → dedupe_scanner.py      # sweep top-50 unchecked pairs
    → classify + commit      # "dedupe: sweep N pairs — ..."
```

**Local mode** (no GitHub remote): same flow, push step skipped.

The garden agent runs autonomously in the background — no manual intervention needed after the initial `git push`.

---

## Garden Agent

The garden agent runs autonomously on every `git push` to the garden. It pulls new entries and runs a full dedup sweep without prompting.

### Install

After cloning the garden, run the installer from inside the garden directory:

```bash
cd ~/.hortora/garden   # or wherever your garden clone lives
bash ~/claude/hortora/soredium/scripts/garden-agent-install.sh
```

The installer is idempotent — safe to re-run and safe across machines. It installs:

| File | Purpose |
|------|---------|
| `garden-agent.sh` | Entry point. Acquires a lockfile, rotates logs, invokes Claude. |
| `run-scanner.sh` | Thin wrapper around `dedupe_scanner.py` — avoids shell expansion issues in agent commands. |
| `.claude/settings.json` | Allows git read/write and scanner commands without prompting. |
| `CLAUDE.md` | Agent instructions: pull → dedup sweep → commit. |
| `.git/hooks/post-commit` | Fires the agent after any non-dedupe commit. |

### Manual trigger

```bash
cd ~/.hortora/garden && ./garden-agent.sh
```

Useful for clearing a backlog or verifying the agent runs cleanly after config changes. Output goes to `garden-agent.log` (gitignored).

---

## Install skills

```bash
# In any Claude Code session
/install-skills https://github.com/Hortora/soredium

# Or sync from a local clone
python3 scripts/claude-skill sync-local
```

## Set up a garden clone

```bash
bash scripts/garden-setup.sh
# Clones Hortora/garden with sparse blobless checkout
# Index files materialised; entry bodies fetched on demand
```

## Run tests

```bash
python3 -m pytest tests/ -v
# 139 tests
```

---

## Repos

- [Hortora/garden](https://github.com/Hortora/garden) — root canonical garden
- [Hortora/spec](https://github.com/Hortora/spec) — open protocol specification
- [hortora.github.io](https://hortora.github.io) — project site
