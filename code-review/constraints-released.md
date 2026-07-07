# Released Project Constraints

Load this file only when `MATURITY_STAGE=released`. Pre-release projects
skip this entirely — bold changes are expected and welcome.

---

## Backward Compatibility

Flag as WARNING any change that breaks existing consumers without a
documented migration path:

- **Public API signatures** — changing parameter types, return types, or
  removing methods
- **Configuration keys** — renaming or removing config keys breaks
  existing deployments
- **Database schemas** — column renames, type changes, or deletions
  require migration scripts
- **CLI flags** — removing or renaming flags breaks scripts and CI
  pipelines
- **Serialization formats** — changes to JSON/protobuf shapes break
  consumers
- **Event/message contracts** — changing event payloads breaks
  subscribers

## Migration Strategy (required for breaking changes)

When a breaking change is justified:
1. Document the migration path in the commit body or linked issue
2. Deprecate before removing — mark old API deprecated, ship both,
   remove in a subsequent release
3. Version bump follows semver: breaking change = major version bump

## Deprecation Rules

- Mark deprecated items with language-appropriate annotations
  (`@Deprecated`, `@deprecated`, `# type: ignore` with comment)
- Include a message stating what to use instead
- Never remove a deprecated item in the same release it was deprecated
