# PlainDB Architecture

PlainDB is a backend-first SQL safety system. The DBeaver plugin is a thin client that sends requests to the backend, while the backend owns generation, verification, execution, and rollback.

## System Overview

```
DBeaver (UI)
  -> PlainDB Plugin (Java)
    -> HTTP/REST
      -> PlainDB Backend API (FastAPI)
        -> PlainDB Architecture Pipeline (Python)
          -> Database Adapters (SQLite, PostgreSQL, MySQL/MariaDB)
            -> Target Database
```

## Current Architecture (Source of Truth)

### DBeaver Plugin

Location: dbeaver-plugin

Responsibilities:
- Collect request text and target connection context.
- Send backend requests to /run or /run/stream.
- Store rollback snapshots in UI history.
- Apply backend rollback via /rollback/{rollback_id} when available.
- Distinguish backend snapshots from local UI-only snapshots.

Notes:
- Plugin account settings (API key, backend URL, model) are persisted locally.
- The plugin is backend-only for execution control.

### Backend API

Location: backend/api/main.py

Primary endpoints:
- GET /health
- POST /run
- POST /run/stream (NDJSON progress + final payload)
- GET /rollback/snapshots
- POST /rollback/{rollback_id}

### Backend Pipeline

Location: backend/plain_db/architecture.py

The backend uses a six-stage architecture flow:
1. Schema introspection
2. AI SQL generation
3. AI SQL verification
4. AI verification-query planning
5. Transactional execution
6. Result verification and retry classification

Deterministic verification behavior:
- Verification queries are generated, then executed against the live transaction context.
- For read-only SELECT, pass/fail is resolved deterministically from query execution results (LLM result verification is skipped).

### Adapter Layer

Location: backend/plain_db/adapters

Currently implemented adapters:
- SQLiteAdapter
- PostgreSQLAdapter
- MySQLAdapter

Dialect routing:
- sqlite
- postgres/postgresql/pg
- mysql/mariadb

## Request Lifecycle

### 1. Client Request

Plugin sends a request payload to backend:
- intent_text
- provider and api_key
- model_name
- database_target (dialect/database/credentials/host/port/schema/connection string)

### 2. Backend Processing

For /run and /run/stream:
1. Convert payload to internal BackendRequest.
2. Prepare rollback checkpoint for supported mutating targets.
3. Execute architecture pipeline.
4. If committed and SQL is mutating, finalize rollback snapshot and attach rollback_id.
5. Return response payload (or stream progress + final event).

### 3. Rollback

When POST /rollback/{rollback_id} is called:
1. Backend looks up snapshot metadata.
2. Applies restore by dialect:
- sqlite: file copy restore
- postgresql: psql restore from pg_dump snapshot
- mysql: mysql client restore from mysqldump snapshot

## Rollback Storage Model

Location: backend/plain_db/rollback.py

What is stored:
- Snapshot artifact file per checkpoint
  - sqlite: .sqlite copy
  - postgresql: .postgres.sql dump
  - mysql: .mysql.sql dump
- Snapshot metadata index: snapshot-index.json

Persistence behavior:
- Rollback IDs are persisted and reloaded from snapshot-index.json.
- On startup, backend loads valid entries whose snapshot files still exist.

Storage path:
- tempdir/plaindb-rollbacks by default.

## Safety and Consistency Guarantees

- SQL is verified before commit.
- Transaction execution and verification are coupled.
- No-op UPDATE/DELETE with rowcount 0 is rejected.
- Rollback IDs are created only for committed mutating SQL.
- Mutating SQL detection tolerates leading comments/semicolons.

## Current Limitations

- Local plugin snapshots without backend rollback_id can only restore UI state.
- Backend rollback depends on snapshot artifact availability in storage.
- Snapshot size can be large for large databases (logical dumps for PostgreSQL/MySQL, full file copy for SQLite).

## Verification and Testing Status

Recent validated behavior:
- End-to-end rollback pass for PostgreSQL and MySQL.
- /run and /run/stream rollback paths both validated.
- DBeaver rollback selector defaults to backend-capable snapshots.

## References

- Root project overview: ../README.md
- Backend details: ../backend/README.md
- Plugin details: ../dbeaver-plugin/README.md
