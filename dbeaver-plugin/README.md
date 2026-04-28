# PlainDB DBeaver Plugin

This module is the DBeaver integration layer for PlainDB.

## What it does

- Captures a user's database operation request inside DBeaver.
- Sends the request to PlainDB for semantic verification, safety checks, and retry control.
- Executes SQL only after PlainDB approves it.
- Rolls back and retries when PlainDB returns an error context.
- Shows only human-readable status messages in English.
- Never exposes raw SQL in the user interface.

## User-facing rules

- All prompts, labels, errors, and status messages must be English only.
- SQL text must remain hidden from the user experience.
- The user should see intent, approval status, and high-level outcomes only.

## Recommended architecture

1. DBeaver plugin UI captures an English-only task request.
2. Plugin sends the request to a PlainDB service.
3. PlainDB returns either approval or a corrected SQL candidate internally.
4. Plugin runs the approved operation without displaying SQL.
5. Plugin shows only success, failure, rollback, and retry summaries.

## Local development

This repository does not yet include the full DBeaver SDK target platform.
The Java sources here are a starter scaffold that should be moved into a real
Eclipse/DBeaver plugin project and linked against the DBeaver API bundles.

## Next implementation step

Connect the handler to the exact DBeaver SQL execution interception point used
by your target DBeaver edition, then wire the PlainDB HTTP client into it.
