# Handler: check_protocols

Protocols directory exists. Read any protocols applicable to the described work and surface violations before proceeding.

Common signals:
- Maven coordinate changes → `maven-coordinate-standard.md`, `artifact-rename-propagation.md`
- Flyway migrations → `flyway-migration-rules.md`, `flyway-version-range-allocation.md`
- SPI changes → `ledger-spi-propagation.md`, `spi-blocking-reactive-parity.md`
- Module structure → `module-tier-structure.md`, `maven-submodule-folder-naming.md`
- Script externalisation → `externalised-scripts-require-tests.md`

After reviewing, call the orchestrator with:
```
step_done=check_protocols
```
