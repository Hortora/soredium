---
layout: post
title: "The twenty-step skill that couldn't close a slot"
date: 2026-08-05
type: phase-update
entry_type: note
subtype: diary
projects: [soredium]
---

## The bug was in the shape, not the logic

work-end had a multi-repo slot close bug. It processed the primary repo — rebased, pushed, stamped — then moved on. Non-primary repos were left hanging: content merged (usually in a separate session), but never stamped. An audit of 73 slots found 27 with this problem. All stamp-related, no data loss.

The root cause wasn't a missing line of code. It was architectural: the SKILL.md described per-repo operations using `<slot>/<repo>` syntax, but the LLM only executed the primary repo. There was no mechanical loop, and no gate that checked whether all repos had been processed. The LLM made a judgment call — "I did the repo" — and it was wrong for every non-primary repo in every multi-repo slot.

## Why twenty steps is too many

The old work-end had ~20 steps across 1,400 lines. Promotion, verification, and cleanup were scattered — artifact promotion in step 8a, stamp in step 8j, verification as a manual checklist in step 9. The LLM frequently skipped steps, complained about length, and made judgment calls that should have been mechanical. The inventory/plan/approval cycle (steps 4-7) was ceremony the scripts didn't need — `close_artifacts.py` already knew what to promote and where.

The real problem: the SKILL.md interleaved LLM decisions with mechanical git operations at the per-step level. A step would run a script, then ask the LLM to decide something, then run another script. Every interleave point was a chance for the LLM to skip, reorder, or "optimize" the sequence.

## Five steps, three scripts

The restructure collapses everything into Context → Sweep → Execute → Verify → Close. Three new Python scripts absorb the mechanical work:

**`work_end_context.py`** gathers all preconditions and routing in a single JSON output. The SKILL.md no longer runs six separate commands to figure out where it is.

**`work_end_execute.py`** is the core multi-repo fix. Three subcommands — `promote`, `rebase`, `land` — that the SKILL.md calls in sequence with an LLM squash analysis loop between rebase and land. The script loops through all repos mechanically. The LLM makes exactly one decision per repo (how to squash), writes it to a `.squash-plan-<repo>.json` file, and the script reads it back in Phase C. No interleaving.

**`verify_slot_close.py`** is the defense-in-depth gate. Checks every repo: merged, stamped, landing SHA valid, main pushed. The primary fix is Execute's mechanical loop; Verify catches bugs in Execute itself.

The SKILL.md went from 1,399 lines to 314. What remains: the 5-step structure, what the LLM does in the sweep (creative judgment), and how to handle failures (re-run the failing step).

## The stamp ordering trap

The most dangerous constraint: stamps must be written after squash. Squash rewrites commit SHAs — a stamp written before squash references SHAs that become unreachable after the rebase. The old ordering was correct but implicit. The new Execute sequence makes it structural: squash runs in Phase B, stamp runs in Phase C, and there's no way to reach stamp without completing squash. `land_branch.py stamp` also gained idempotency — if the branch tip is already a `chore: branch closed` commit, it skips stamp creation and only retries the push if needed.

## What this opens up

The three-phase Execute structure — Rebase (script) → Squash analysis (LLM) → Land (script) — is a pattern worth reusing. Any skill that interleaves LLM decisions with mechanical git operations could benefit from the same split: scripts handle the per-repo loop, the LLM makes decisions that get serialized to files, and another script reads those files and executes mechanically. The interleave boundary is a JSON file, not a function call — which means crash recovery comes for free. The script reads its progress file and skips completed repos; the LLM skips repos that already have plan files. Neither needs to know about the other's recovery mechanism.
