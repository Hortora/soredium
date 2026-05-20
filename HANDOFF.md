# HANDOFF — 2026-05-20

## Last Session

Content taxonomy finalised and academically grounded — five independent frameworks (Newman 1827, Kinneavy 1969, Britton 1970, Diátaxis 2017, this work) all converge on the same four aims of discourse. write-content created as universal content layer; write-blog now consumes it as a prerequisite. 570-post corpus classified (91 labels, catalogue.tsv + navigable index at `~/claude-workspace/corpus/`). Linguistic fingerprint written at `~/claude-workspace/writing-styles/mark-proctor-voice.md`. Hook #66 fixed (canonical source is `hooks/check_project_setup.sh`, not `install-skills/SKILL.md`). `/work` unified lifecycle router added (#94). InfoBrief naming made consistent across all files.

## Immediate Next Step

Close issue-94-work-lifecycle — it has many untracked `commands/` directories that need committing before `work end`. Run `git status` on the branch first to assess scope.

## What's Left

- **#96 diary→log sweep** — ~150 blog posts still have `subtype: diary`; needs batch update to `subtype: log`
- **issue-94 branch** — untracked `commands/` dirs need committing or discarding before `work end`
- **Content articles** — Proposal B (standalone short taxonomy article) and Proposal A (6-part series); A/B trial needs Sparge viewer first
- **Academic paper** — research outstanding: Kinneavy 1971 book (not a paper), JSTOR, Procida diataxis.fr/theory
- **Sparge A/B viewer** — brief given to Sparge; build tool for side-by-side markdown comparison

## What's Next

| # | Description | Scale | Complexity | Notes |
|---|-------------|-------|------------|-------|
| #96 | diary→log sweep across corpus | M | Low | Batch frontmatter update |
| — | Write Proposal B (short taxonomy article) | S | Low | Needs Sparge viewer for A/B first |
| — | Proposal A 6-part series | XL | Med | After Proposal B validated |
| — | Academic paper research | M | High | Kinneavy 1971, JSTOR, Procida |

## References

- Blog: `docs/_posts/2026-05-20-mdp01-taxonomy-fingerprint-corpus.md`
- Corpus: `~/claude-workspace/corpus/catalogue.tsv`, `~/claude-workspace/corpus/index.md`
- Fingerprint: `~/claude-workspace/writing-styles/mark-proctor-voice.md`
- Taxonomy notes: `docs/content-taxonomy-article-notes.md`
- Content skill: `write-content/SKILL.md`
