# soredium

The engine for Hortora gardens — validators, CI scripts, GitHub Actions workflows, and Claude skills.

> A soredium is a lichen's dispersal unit: a self-contained bundle that carries everything needed to establish a new colony wherever it lands.

---

## What's in here

### Claude Skills

| Skill | Purpose |
|-------|---------|
| `forage` | Session-time capture, search, and retrieval. CAPTURE opens a GitHub issue, writes the entry, validates locally, and opens a PR — or integrates directly in local mode. SEARCH uses `git cat-file --batch` for efficient on-demand entry retrieval. |
| `harvest` | Dedicated maintenance sessions. MERGE integrates submissions, deduplicates, calls `integrate_entry.py`. DEDUPE sweeps the full garden for near-duplicates. |

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/validate_pr.py` | Validates a single garden entry. Checks required fields, score threshold (≥ 8), prompt injection patterns, Jaccard duplicate scan (≥ 0.4 = warning), vocabulary compliance. Outputs JSON. Exits 1 on CRITICAL failures. Called by GitHub Actions on PR open and by forage locally before pushing. |
| `scripts/integrate_entry.py` | Updates all garden indexes after a merge: `_summaries/`, domain `INDEX.md`, `labels/`, `_index/global.md`. Runs structural check, commits. Called by GitHub Actions on merge and by forage/harvest in local mode. |
| `scripts/validate_garden.py` | Full garden validation — structural checks (`--structural`), entry format, index consistency. |
| `scripts/garden-setup.sh` | One-time sparse blobless clone setup. Index files materialised; entry bodies fetched on demand via `git cat-file`. |
| `scripts/claude-skill` | Skill installer — `install`, `sync-local`, `uninstall`. |

### GitHub Actions (live in `Hortora/garden`)

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `validate-on-pr.yml` | PR opened/updated touching `*/GE-*.md` | Checks out soredium, runs `validate_pr.py`, posts comment, applies label (`rejected` / `needs-review` / `auto-approve-eligible`) |
| `integrate-on-merge.yml` | PR merged with `garden-submission` label | Checks out soredium, runs `integrate_entry.py`, pushes index updates, closes linked GitHub issue |

---

## How submissions work

**GitHub mode** (default when garden has a GitHub remote):

```
forage CAPTURE
  → gh issue create          # conflict-free GE-ID
  → write GE-XXXX.md
  → validate_pr.py           # fast local check before push
  → gh pr create
    → validate-on-pr CI      # format, score, Jaccard, injection
    → human review
    → merge
    → integrate-on-merge CI  # indexes updated, issue closed
```

**Local mode** (no GitHub remote):

```
forage CAPTURE
  → write GE-XXXX.md
  → validate_pr.py           # same validation as CI
  → integrate_entry.py       # same index maintenance as CI
  → git commit
```

Same scripts, different callers. CI and local mode produce identical results.

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
