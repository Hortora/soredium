# Soredium Protocols

Standing rules and principles for the soredium skill collection and garden tooling.

## Validation

| File | Summary | Applies to |
|------|---------|------------|
| [validate-schema-vs-validate-pr.md](validate-schema-vs-validate-pr.md) | GE frontmatter validation belongs in validate_pr.py, not validate_schema.py | soredium scripts; validation issues and PRs |

## Taxonomy

| File | Summary | Applies to |
|------|---------|------------|
| [taxonomy-values-reflect-content-character.md](taxonomy-values-reflect-content-character.md) | Subtype values must match content character, not naming convention tidiness | Any taxonomy value additions or renames |
| [taxonomy-rename-idempotent-script.md](taxonomy-rename-idempotent-script.md) | Taxonomy renames require a permanent idempotent cleanup script in scripts/ | Any frontmatter taxonomy value changes across repos |

## write-content Skill

| File | Summary | Applies to |
|------|---------|------------|
| [write-content-three-layer-taxonomy.md](write-content-three-layer-taxonomy.md) | form files carry what/why only; mode files carry how; voice files carry register and anti-slop | write-content/forms/, modes/, voice/ |

## Skill Script Externalisation

| File | Summary | Applies to |
|------|---------|------------|
| [externalised-scripts-require-tests.md](externalised-scripts-require-tests.md) | Scripts and their pytest tests must be committed together — no script merges without tests | Any .py script added to a skill directory |
