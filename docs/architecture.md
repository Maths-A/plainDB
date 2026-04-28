# PlainDB Architecture

PlainDB separates concerns into swappable modules:

- SQL generation layer (external): AI produces SQL from user prompt.
- Semantic verifier: independent verifier confirms SQL matches prompt intent.
- Safety verifier: policy engine blocks harmful SQL.
- Execution adapter: runs SQL in a transaction using database-specific driver.
- Effect verifier: checks state changes before commit.
- Post-commit verifier: checks final persisted state.

## Why This Is Safer Than Direct AI Execution

AI SQL generation can be:
- semantically wrong,
- syntactically valid but dangerous,
- operationally successful but behaviorally incorrect.

PlainDB introduces gated verification before commit and after commit.

## Request Lifecycle

1. User prompt -> SQL candidate (from generator AI).
2. Semantic verifier approves/rejects intent alignment.
3. Safety verifier approves/rejects harmful patterns.
4. SQL executes inside transaction.
5. Effect verifier compares transaction state against intent.
6. If approved, commit; otherwise rollback.
7. Post-commit verifier confirms final state.

## Universal Database Strategy

`DatabaseAdapter` defines a stable contract:
- `begin()` for transaction context,
- `execute()` for statement execution,
- `query()` for validation queries,
- `snapshot()` for lightweight table state checks.

Each DB system only needs one adapter implementation.

## Production Notes

- Use parameterized SQL only.
- Add role-based SQL policy per environment.
- Add structured audit logs for every stage decision.
- Replace heuristic semantic verifier with a dedicated LLM evaluator plus confidence threshold.
- Add domain-specific post-commit assertions (business rules).
