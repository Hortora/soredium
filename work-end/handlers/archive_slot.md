# archive_slot handler

Slot work has landed. Offer to mark the slot for archiving.

**Do NOT archive immediately.** Other sessions may have open files in
this slot. Instead, write a `.archive-requested` marker. The actual
move to attic happens on next session start or reconcile sweep, after
confirming no active sessions.

## Steps

1. Tell the user: "Slot SLOT_NUM work has landed. Mark for archiving?"
2. On **YES**: write the marker file, then complete the step.

   ```bash
   echo "requested_by=$(whoami)" > <SLOT_PATH>/.archive-requested
   echo "requested_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> <SLOT_PATH>/.archive-requested
   ```

3. On **NO** or **skip**: complete the step without writing the marker.

The slot stays in place until a future session (or reconcile sweep)
detects the marker and performs the actual move after verifying no
active PIDs.
