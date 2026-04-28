# PlainDB

PlainDB is a database-agnostic safety pipeline for executing AI-generated SQL with multiple verification layers.

## Goal

Use AI to generate SQL, but never trust it blindly. PlainDB enforces a five-stage verification flow before and after execution.

## Verification Pipeline

1. Semantic verification: a second verifier checks whether user intent matches generated SQL.
2. Safety verification: detect harmful or policy-violating SQL.
3. Transaction execution verification: run SQL inside a transaction and verify execution success.
4. In-transaction effect verification: validate effects against user intent before commit.
5. Post-commit database verification: verify final database state after commit.

If any stage fails, PlainDB can rollback the transaction and reiterate with a new SQL candidate generated from the failure error context.

## Project Layout

- `plain_db/models.py`: shared data models.
- `plain_db/interfaces.py`: extension interfaces for adapters and verifiers.
- `plain_db/safety.py`: baseline SQL safety policy.
- `plain_db/pipeline.py`: orchestrates full verification pipeline.
- `plain_db/adapters/sqlite_adapter.py`: SQLite reference adapter.
- `examples/sqlite_demo.py`: runnable demonstration.

## Quick Start

```bash
python3 examples/sqlite_demo.py
```

The example:
- creates a small SQLite database,
- simulates an AI-generated SQL statement,
- forces a first execution failure,
- regenerates SQL from the error,
- runs the five verification stages,
- commits only if all checks pass.

## Retry with Error-Guided SQL Regeneration

Use `PipelineConfig.max_retries` and pass `regenerate_sql` to `PlainDBPipeline.run(...)`.

`regenerate_sql` receives:
- `intent`
- previous SQL candidate
- failure context string (for example, `execution: no such column: scor`)
- attempt index

The callback returns a new SQL candidate for the next attempt.

## Extending to Any Database

Implement `DatabaseAdapter` in `plain_db/interfaces.py` for each DB engine:
- PostgreSQL (`psycopg`)
- MySQL (`mysqlclient` or `pymysql`)
- SQL Server (`pyodbc`)
- Oracle (`oracledb`)

No pipeline logic changes are required when swapping adapters.

## DBeaver Plugin Integration

The `dbeaver-plugin/` folder contains a starter Eclipse/DBeaver plugin scaffold.

Design rules for the plugin:
- user-facing text must be English only,
- SQL must stay hidden from the UI,
- the plugin should show approval, rollback, retry, and final status only,
- PlainDB should own semantic verification, safety checks, and retry decisions.

The plugin should send the natural-language request to PlainDB and keep generated SQL internal to the service layer.
