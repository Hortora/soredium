# Handler: stack_pick

Multiple paused branches on the stack. Show a picker.

1. Read the pause stack file at `$WORKSPACE/.pause-stack`
2. Display:
   ```
   You have N paused branch(es):
     1. <branch>  #<issue>  paused <duration> ago
     2. <branch>  #<issue>  paused <duration> ago
   Resume one, or start something new? (1 / 2 / ... / new)
   ```
3. If stack depth > 3, prefix with: `Warning: Stack has N paused branches — consider closing some.`
4. When user picks, call the orchestrator with:
   ```
   step_done=stack_pick selected_branch=<branch>
   ```
5. If user picks "new", skip remaining resume steps:
   ```
   skip_step=stack_pick
   ```
   Then route to work-start.
