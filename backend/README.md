# PlainDB Backend

The **PlainDB Backend** is a containerized REST API service that provides SQL generation, verification, and execution capabilities. It can be deployed independently and accessed by clients like the DBeaver plugin or other applications.

The current DBeaver plugin integration is **backend-only**: the plugin acts as a thin interface and sends request execution through backend endpoints (`/run`, rollback APIs).

## Architecture Overview

```
PlainDB Backend
├── REST API Layer (FastAPI)
│   └── /run accepts the English explanation, AI provider/key, and database credentials
├── Architecture Pipeline
│   ├── Schema introspection
│   ├── AI SQL generation
│   ├── AI SQL verification
│   ├── AI verification-query planning
│   ├── Transactional execution
│   └── Result verification and retry classification
└── Database Adapters
  ├── SQLite Adapter
  ├── PostgreSQL Adapter
  └── MySQL Adapter
```

## Quick Start

### Local Development

**Prerequisites:**
- Python 3.10+
- pip or conda

**Installation:**

```bash
# Navigate to backend directory
cd backend

# Install in development mode
pip install -e ".[dev]"

# Install dependencies
pip install -r requirements.txt

# If you plan to use PostgreSQL or MySQL, the backend installs their drivers too.
# PostgreSQL: psycopg2-binary
# MySQL: PyMySQL
```

**Run the Server:**

```bash
# Start the API server locally
python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

**API Documentation:**
- OpenAPI/Swagger: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### Docker Deployment

**Build and Run:**

```bash
# Build the image
docker build -t plaindb-backend:latest .

# Run container
docker run -p 8000:8000 -v plaindb_data:/data plaindb-backend:latest
```

**Using Docker Compose:**

```bash
# Start the stack
docker-compose up -d

# View logs
docker-compose logs -f plaindb-backend

# Stop the stack
docker-compose down
```

## Testing

**Run All Tests:**

```bash
# Install test dependencies
pip install -e ".[dev]"

# Run tests
pytest -v

# With coverage
pytest --cov=plain_db --cov=api tests/
```

**Run Specific Test Categories:**

```bash
# Pipeline tests only
pytest tests/test_pipeline.py -v

# API tests only
pytest tests/test_api.py -v

# Architecture pipeline tests
pytest tests/test_architecture.py -v

# Adapter routing tests
pytest tests/test_adapter_factory.py -v

# Safety regression tests
pytest tests/test_safety_regressions.py -v

# Real-pipeline API integration tests
pytest tests/test_api_integration.py -v

# LLM provider failure-mode tests
pytest tests/test_llm.py -v
```

**Optional Real DB Smoke Tests (PostgreSQL/MySQL):**

```bash
# Provide DSNs only when you want to run live adapter smoke tests
export PLAINDB_TEST_POSTGRES_DSN='postgresql://user:pass@localhost:5432/your_db'
export PLAINDB_TEST_MYSQL_DSN='mysql://user:pass@localhost:3306/your_db'

pytest tests/test_adapter_smoke.py -v
```

**Run Tests in Docker:**

```bash
# Build test image
docker build -f Dockerfile.test -t plaindb-test:latest .

# Run tests
docker run plaindb-test:latest
```

## REST API Reference

### Health Check

```bash
GET /health
```

Returns service status:
```json
{
  "status": "ok",
  "default_provider": "gemini",
  "default_database": ":memory:",
  "default_model": null
}
```

### Root Endpoint

```bash
GET /
```

Returns a short contract reminder for clients.

### Run Request

```bash
POST /run
```

Generate SQL from English, verify it with schema-aware AI prompts, execute it in a transaction, and verify the result.

Supported dialects: `sqlite`, `postgres`, `postgresql`, `pg`, `mysql`, and `mariadb`.

**Request:**
```json
{
  "intent_text": "Show all users older than 25",
  "api_key": "YOUR_AI_KEY",
  "provider": "gemini",
  "model_name": "gemini-2.5-flash",
  "dry_run": true,
  "max_retries": 1,
  "database_target": {
    "dialect": "postgresql",
    "database": "plaindb",
    "username": null,
    "password": null,
    "host": "localhost",
    "port": 5432,
    "schema": null,
    "connection_string": null,
    "options": {}
  }
}
```

**Response:**
```json
{
  "accepted": true,
  "committed": false,
  "rollback_id": null,
  "sql": "SELECT * FROM users WHERE age > 25",
  "generated_sql": "SELECT * FROM users WHERE age > 25",
  "verification_queries": ["SELECT COUNT(*) AS c FROM users WHERE age > 25"],
  "execution": {
    "success": true,
    "rowcount": 42,
    "lastrowid": null,
    "rows": [],
    "error": null
  },
  "stages": [
    {
      "stage": "generation",
      "passed": true,
      "reason": "AI generated SQL from the English explanation.",
      "details": {"attempt": 1, "sql": "SELECT * FROM users WHERE age > 25"}
    },
    {
      "stage": "sql_verification",
      "passed": true,
      "reason": "SQL verification passed.",
      "details": {"attempt": 1}
    },
    {
      "stage": "verification",
      "passed": true,
      "reason": "Verification passed.",
      "details": {"attempt": 1}
    }
  ],
  "attempts": 1
}
```

When a mutating sqlite statement is committed, the response can include a non-null `rollback_id`.

### Rollback Snapshots

```bash
GET /rollback/snapshots
```

Lists stored rollback snapshots for the running backend process.

### Apply Rollback

```bash
POST /rollback/{rollback_id}
```

Restores the sqlite database file from the snapshot identified by `rollback_id`.
Rollback checkpoints are supported for:
- sqlite file databases (copy/restore the DB file)
- PostgreSQL (logical dump via `pg_dump`, restore via `psql`)
- MySQL (logical dump via `mysqldump`, restore via `mysql`)

Notes:
- sqlite `:memory:` targets cannot be snapshotted.
- PostgreSQL/MySQL checkpointing requires the corresponding client tools to be installed in the backend runtime.

## Configuration

### Environment Variables

```bash
# Default request settings
PLAINDB_DEFAULT_DATABASE=:memory:
PLAINDB_DEFAULT_AI_PROVIDER=gemini
PLAINDB_DEFAULT_MODEL=gemini-2.5-flash
```

### Using Python Package

The backend can also be imported and used directly in Python:

```python
from plain_db import BackendRequest, DatabaseTarget, PlainDBArchitecturePipeline

pipeline = PlainDBArchitecturePipeline()
result = pipeline.run(
  BackendRequest(
    english_explanation="Show all users older than 25",
    ai_provider="gemini",
    api_key="YOUR_AI_KEY",
    ai_model="gemini-2.5-flash",
    database=DatabaseTarget(dialect="sqlite", database=":memory:"),
    dry_run=True,
  )
)

print(result.generated_sql)
```

## Verification Pipeline

The pipeline performs the following verification stages:

1. **Schema introspection** - Reads table, column, foreign key, and row-count metadata.
2. **SQL generation** - Uses AI to produce SQL from the English explanation.
3. **SQL verification** - Uses AI to check whether the SQL matches the request.
4. **Verification query planning** - Uses schema context to generate SELECT checks.
5. **Transactional execution** - Runs SQL in a transaction and rolls back on failure.
6. **Result verification** - Re-checks the database state and retries only when the SQL itself was wrong.

All stages are logged in the response for audit and debugging.

## Development

### Project Structure

```
backend/
├── plain_db/                    # Core package
│   ├── __init__.py
│   ├── models.py               # Domain models
│   ├── interfaces.py           # Abstract interfaces
│   ├── architecture.py         # Main architecture pipeline
│   ├── llm.py                  # AI provider client
│   ├── schema.py               # Schema model types
│   ├── pipeline.py             # Legacy verification pipeline
│   ├── safety.py               # Safety verifiers
│   ├── default_verifiers.py    # Default implementations
│   └── adapters/
│       ├── __init__.py
│       ├── factory.py          # Dialect-based adapter selector
│       ├── dbapi_adapter.py    # Shared DB-API adapter base
│       ├── sqlite_adapter.py
│       ├── postgresql_adapter.py
│       └── mysql_adapter.py
├── api/                        # REST API
│   ├── __init__.py
│   └── main.py                 # FastAPI app
├── tests/                      # Test suite
│   ├── test_pipeline.py
│   ├── test_api.py
│   └── test_adapter_factory.py
├── setup.py                    # Package configuration
├── requirements.txt            # Dependencies
├── Dockerfile                  # Production image
├── Dockerfile.test            # Test image
├── docker-compose.yml         # Compose stack
└── README.md                  # This file
```

### Adding Custom Verifiers

Extend the base classes to add custom verification logic:

```python
from plain_db.interfaces import SemanticVerifier, SafetyVerifier

class CustomSemanticVerifier(SemanticVerifier):
    def verify(self, intent, candidate):
        # Your verification logic
        pass

# Use in pipeline
pipeline = PlainDBPipeline(
    adapter=adapter,
    semantic_verifier=CustomSemanticVerifier()
)
```

### Database Adapters

Implement the `DatabaseAdapter` interface to support additional databases:

```python
from plain_db.interfaces import DatabaseAdapter

class PostgreSQLAdapter(DatabaseAdapter):
    def __init__(self, connection_string):
        # Initialize connection
        pass
    
    def begin(self):
        # Start transaction
        pass
    
    def execute(self, tx, sql, params):
        # Execute SQL
        pass
    
    # Implement other abstract methods
```

## Integration with DBeaver Plugin

The DBeaver plugin communicates with this backend via the REST API:

1. User configures backend URL (e.g., `http://localhost:8000`) in DBeaver.
2. Plugin sends execution requests to `/run`.
3. Backend performs generation, verification, execution, and commit/rollback decisions.
4. For sqlite file snapshots, backend may return `rollback_id`.
5. Plugin can apply rollback through `POST /rollback/{rollback_id}`.
6. Plugin displays backend results and audit information to user.

See [../dbeaver-plugin/README.md](../dbeaver-plugin/README.md) for integration details.

## Troubleshooting

### API won't start

```bash
# Check if port 8000 is in use
lsof -i :8000

# Use different port
PLAINDB_PORT=8001 python -m uvicorn api.main:app
```

### Database connection errors

```bash
# SQLite: check database file permissions
ls -la /path/to/database.db

# PostgreSQL/MySQL: verify host, port, credentials, and DB name
# You can also pass a full connection_string in database_target
```

### Tests failing

```bash
# Run with verbose output
pytest -vv

# Run specific test
pytest tests/test_pipeline.py::TestSemanticVerifier::test_select_intent_matches_semantic -vv
```

## Performance Considerations

- **In-memory database** (`:memory:`) is fastest for testing but doesn't persist
- **SQLite file database** is good for single-user development
- **Connection pooling** can be added for production deployments
- **Async execution** already implemented via FastAPI/Uvicorn

## Security Notes

- All SQL is **vetted before execution** through multiple verification stages
- **Forbidden operations** (DROP, TRUNCATE, etc.) are blocked by default
- **Only DML commands** (SELECT, INSERT, UPDATE, DELETE) allowed by default
- **Transaction boundaries** ensure rollback on errors
- Extend `SafetyVerifier` for additional security policies
