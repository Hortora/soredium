## D1: Naming collision detection scope

**Choice:** Scan all top-level git directories in family_root
**Alternatives:**
- Check slot repos + family dirs — redundant since family dirs already covers slot repos
- Check only current slot repos — current broken behavior
**Rationale:** Covers repos not in any slot; simplest and most comprehensive
**Trade-offs:** Scans disk on every create_slot/add_repo call (negligible — family_root has <20 dirs)
**Exploration:** quick
**Status:** captured

## D2: Post-creation validation scope and failure mode

**Choice:** Full consistency check — wksp symlinks, DB-vs-disk repo match, .slot metadata — with hard fail (exit 1)
**Alternatives:**
- Symlink-only check — misses DB/disk drift introduced during creation
- Warn only — allows silently broken slots to persist
- Hard fail + cleanup — removes partial state, but loses successful clones
**Rationale:** The DB is a source of truth alongside disk; checking both catches more failure modes. Issue says "fail fast"; partial state is debuggable; cleanup destroys work already done.
**Trade-offs:** Requires DB connection during validation (already available in create_slot); caller must handle or investigate partial slot on failure
**Exploration:** quick
**Status:** captured

## D3: Broken symlink surfacing in list_slots

**Choice:** Add `wksp_ok` boolean to list_slots output; print WKSP=ok/broken in CLI
**Alternatives:**
- Separate health subcommand — more work, less discoverable
- No surfacing — defeats acceptance criterion 5
**Rationale:** list_slots already iterates repos; checking symlinks is O(1) per repo
**Trade-offs:** Slightly more output per slot line
**Exploration:** quick
**Status:** captured

## D4: add_repo workspace wiring parity

**Choice:** Add configure_slot_remotes call to add_repo for workspace clone parity with create_slot
**Alternatives:**
- Leave add_repo as-is — workspace clone in add_repo lacks GitHub remotes
**Rationale:** Defense-in-depth; add_repo's workspace clone should match create_slot's
**Trade-offs:** None — strictly additive
**Exploration:** quick
**Status:** captured
