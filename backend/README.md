# PlainDB Backend

The **PlainDB Backend** is a containerized REST API service that provides SQL generation, verification, and execution capabilities. It can be deployed independently and accessed by clients like the DBeaver plugin or other applications.

## Architecture Overview

```
PlainDB Backend
├── REST API Layer (FastAPI)
│   └── HTTP endpoints for SQL operations
├── Pipeline Engine
│   ├── Semantic Verification
│   ├── Safety Verification
│   ├── Effect Verification
│   ├── Post-commit Verification
│   └── Database Execution
└── Database Adapters
    └── SQLite Adapter (extensible for other DBs)
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
  "service": "plaindb-backend",
  "database": "/path/to/db"
}
```

### Service Info

```bash
GET /api/v1/info
```

Returns available endpoints and configuration.

### Generate SQL

```bash
POST /api/v1/generate-sql
```

Generate and execute SQL based on natural language intent.

**Request:**
```json
{
  "intent_text": "Show all users older than 25",
  "expected_tables": ["users"],
  "expected_action": "SELECT",
  "dry_run": false,
  "watched_tables": ["users"],
  "model_name": "gemini-2.5-flash"
}
```

**Response:**
```json
{
  "accepted": true,
  "committed": true,
  "sql": "SELECT * FROM users WHERE age > 25",
  "execution": {
    "success": true,
    "rowcount": 42,
    "error": null
  },
  "stages": [
    {
      "stage": "semantic",
      "passed": true,
      "reason": "Intent and SQL are semantically aligned",
      "details": {"action": "SELECT"}
    },
    {
      "stage": "safety",
      "passed": true,
      "reason": "SQL passed rule-based safety checks",
      "details": {"command": "SELECT"}
    },
    {
      "stage": "execution",
      "passed": true,
      "reason": "SQL executed successfully",
      "details": {"rowcount": 42, "attempt": 1}
    }
  ],
  "attempts": 1
}
```

## Configuration

### Environment Variables

```bash
# Server configuration
PLAINDB_HOST=0.0.0.0           # Server host
PLAINDB_PORT=8000               # Server port
PLAINDB_DB_PATH=plaindb.sqlite  # Database file path

# API configuration
PLAINDB_LOG_LEVEL=INFO          # Logging level
```

### Using Python Package

The backend can also be imported and used directly in Python:

```python
from plain_db import PlainDBPipeline, PipelineConfig, SQLCandidate, UserIntent
from plain_db.adapters import SQLiteAdapter

# Initialize adapter
adapter = SQLiteAdapter("path/to/database.db")

# Create pipeline
pipeline = PlainDBPipeline(adapter)

# Create intent and SQL candidate
intent = UserIntent(
    text="Get users older than 25",
    expected_tables=["users"],
    expected_action="SELECT"
)

candidate = SQLCandidate(
    sql="SELECT * FROM users WHERE age > 25",
    model_name="gemini-2.5-flash"
)

# Run pipeline
result = pipeline.run(intent, candidate)

# Check results
if result.accepted:
    print(f"SQL accepted and committed in {result.attempts} attempt(s)")
    if result.execution:
        print(f"Rows affected: {result.execution.rowcount}")
```

## Verification Pipeline

The pipeline performs the following verification stages:

1. **Semantic Verification** - Ensures SQL matches user intent (action type, tables)
2. **Safety Verification** - Blocks forbidden operations (DROP, TRUNCATE, etc.)
3. **Execution** - Runs SQL in a transaction
4. **Effect Verification** - Validates that changes match intent
5. **Post-Commit Verification** - Confirms final state is correct

All stages are logged in the response for audit and debugging.

## Development

### Project Structure

```
backend/
├── plain_db/                    # Core package
│   ├── __init__.py
│   ├── models.py               # Domain models
│   ├── interfaces.py           # Abstract interfaces
│   ├── pipeline.py             # Verification pipeline
│   ├── safety.py               # Safety verifiers
│   ├── default_verifiers.py    # Default implementations
│   └── adapters/
│       ├── __init__.py
│       └── sqlite_adapter.py   # SQLite implementation
├── api/                        # REST API
│   ├── __init__.py
│   └── main.py                 # FastAPI app
├── tests/                      # Test suite
│   ├── test_pipeline.py
│   └── test_api.py
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

1. User selects "PlainDB (Backend)" as provider in DBeaver
2. Configures backend URL (e.g., `http://localhost:8000`)
3. Plugin sends SQL generation requests to `/api/v1/generate-sql`
4. Backend processes request and returns verification results
5. Plugin displays results to user

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
# Check database file permissions
ls -la /path/to/database.db

# Use absolute path
export PLAINDB_DB_PATH=/absolute/path/to/db.sqlite
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

## License

MIT - See [LICENSE](../../LICENSE) for details

## Contributing

See [../CONTRIBUTING.md](../CONTRIBUTING.md) for guidelines
