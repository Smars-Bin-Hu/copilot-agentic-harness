# Test guide: <task name>

Written for: <user name>. Change under test: <one line>, branch `<branch>` of `<repository>`, written back by task `<development task>` ([REQ.md](.workspace/sandbox/tasks/<development task>/REQ.md), [CHANGES.diff](.workspace/sandbox/tasks/<development task>/CHANGES.diff)).

Order: DEV, then IST, then QAT. Start the next only when the one before passed. Send the results back in VS Code; the list "Send back" of each section says what.

## <DEV>

**Known about this environment**: <from environment.md; UNKNOWN where it says nothing>

### Before you start

- <what must be deployed, loaded or switched on; exact name or command>

### Steps

1. <one action, in words>

   ```
   <the exact command, job or query: copied whole from here>
   ```

   - Expect: <a number, a row count, a state, a file>
2. ...

### Pass when

- [ ] <criterion with a number or an observable fact>
- [ ] ...

### Fail or unclear

- <what a wrong result looks like, and what to capture before you touch anything>

### Clean up

- <how to put the environment back, or "nothing to clean up">

### Send back

- <output of step N, copied as text, and a screenshot of it: paste it into the chat>
- <the numbers asked for above>
- <anything unexpected, even if it looks harmless>

## <IST>

(same sections)

## <QAT>

(same sections)
