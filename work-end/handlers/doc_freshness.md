# doc_freshness_gate

Documentation freshness check — detect candidate-stale sections via
structural anchors.

## Step 1 — Generate diff file list

```bash
git -C $PROJECT diff --name-only $BASE_BRANCH...HEAD > /tmp/doc-freshness-diff.txt
```

If the diff file is empty (docs-only branch or no code changes), skip:
report `step_done=doc_freshness_gate produced=0`.

## Step 2 — Run detection

```bash
python3 ~/.claude/skills/doc-freshness/doc_freshness_check.py \
    --diff /tmp/doc-freshness-diff.txt \
    --docs $PROJECT/docs
```

Read the JSON output.

## Step 3 — Interpret results

If `total_candidates` is 0: report `step_done=doc_freshness_gate produced=0`.

If candidates found:
1. Print each candidate with its doc path, anchor, and changed file
2. For each candidate, read the documentation section and the changed code
3. Determine if the section needs updating (adversarial check)
4. If updates needed: update the section inline, commit, then report done
5. If section is current despite anchor change: add `verified-current: <date> | commit:<hash>` annotation to the YAML frontmatter

**Advisory mode (pre-activation):** Report findings but do not block.
Print: `Doc freshness gate (advisory): N candidate-stale sections found`
then report `step_done=doc_freshness_gate produced=N`.

The hard gate activates after the validation corpus (from first-wave
audit of 5 foundation repos) confirms precision >= 80% and recall >= 60%.
Until then, this step is advisory-only.
