# Handler: item_finished

Decide whether the active item is finished. The answer decides what happens
next, so it is never skipped and never assumed.

- **Finished**: every acceptance criterion in the issue is met, the review left
  nothing that blocks it, and its tests pass. The item is then marked done on its
  branch; `work end` lands it, `work wrap` leaves it to be landed later.
- **Not finished**: anything else. The item stays active on its branch and the
  next session continues it. Nothing of it is landed.

If it is not clear, ask the user. Do not mark work done to tidy up.

Report with the answer:
```
step_done=item_finished outcome=completed finished=yes
step_done=item_finished outcome=completed finished=no
```
