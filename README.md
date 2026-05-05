# PlainDB

**PlainDB** is a database-agnostic safety pipeline for executing AI-generated SQL with multiple verification layers. It consists of a **backend service** (REST API) and a **DBeaver plugin** (UI) that work together to generate, validate, and execute SQL safely.

## Architecture

### Two-Tier Design

**Backend Service** (`backend/`)
- Core SQL verification pipeline
- REST API for remote access
- Containerized deployment (Docker)
- Python package usable in standalone code
- Supports SQLite, PostgreSQL, and other databases

**DBeaver Plugin** (`dbeaver-plugin/`)
- User interface for SQL generation
- Communicates with backend via REST API
- Provides AI integration (OpenAI, Gemini)
- Can also call PlainDB backend locally or remotely

### Verification Pipeline

Both services implement a **five-stage verification flow**. At a high level these steps are:

1. Intent
  PlainDB reads your request and figures out what you want. It expects a clear English sentence, such as "show all rows from people."

2. Safety
  The tool checks whether the request is safe and usable before generating SQL. This is where it can reject unclear, unsupported, or non-English input.

3. Target
  You choose the database connection that PlainDB should use. That tells the tool which schema to work against and where to execute the query.

4. API
  PlainDB sends the request to the configured AI backend or model. The AI writes SQL for the chosen database type.

5. SQL (verification & execution)
  - Semantic Verification: Ensures user intent matches generated SQL.
  - Safety Verification: Detects harmful or policy-violating SQL.
  - Transaction Execution: Runs SQL inside a transaction.
  - In-Transaction Effect: Validates changes match user intent while still in the transaction.
  - Post-Commit Verification: Confirms final database state after commit.

If something fails other than a simple SQL-generation problem, PlainDB will try to explain the error in beginner-friendly language and may attempt guided regeneration where appropriate.

## Project Structure

```
plainDB/
├── backend/                    # Standalone REST API service
│   ├── plain_db/              # Core Python package
│   ├── api/                   # FastAPI REST endpoints
│   ├── tests/                 # Unit and integration tests
│   ├── Dockerfile             # Container image
│   ├── docker-compose.yml     # Local development stack
│   ├── setup.py               # Package installation
│   └── README.md             # Backend documentation
│
├── dbeaver-plugin/            # DBeaver Eclipse plugin
│   ├── src/                   # Java source code
│   ├── plugin.xml             # Plugin manifest
│   ├── pom.xml               # Maven build config
│   └── README.md             # Plugin documentation
│
├── docs/                      # Architecture & design docs
├── examples/                  # Demo scripts
└── README.md                 # This file
```

## Quick Start

### Option 1: Backend Only (Python API)

**Start backend service locally:**

```bash
cd backend

# Install
pip install -e ".[dev]"

# Run server
python -m uvicorn api.main:app --reload

# Visit http://localhost:8000/docs for API documentation
```

**Use in Python code:**

```python
from plain_db import PlainDBPipeline, SQLCandidate, UserIntent
from plain_db.adapters import SQLiteAdapter

adapter = SQLiteAdapter("my_app.db")
pipeline = PlainDBPipeline(adapter)

intent = UserIntent(text="Show users older than 25", expected_action="SELECT")
candidate = SQLCandidate(sql="SELECT * FROM users WHERE age > 25")

result = pipeline.run(intent, candidate)
print(result.accepted, result.committed)
```

### Option 2: Backend + DBeaver Plugin

**1. Start backend:**

```bash
cd backend
docker-compose up
# or: python -m uvicorn api.main:app
```

**2. Install DBeaver plugin:**

```bash
cd dbeaver-plugin
bash ../scripts/install-to-dbeaver.sh
# Restart DBeaver
```

**3. Use in DBeaver:**
- Open SQL editor
- Run "PlainDB → Verify database request" command
- Select "PlainDB (Backend)" as provider
- Configure backend URL (e.g., `http://localhost:8000`)
- Enter natural language request
- See generated and verified SQL

### Option 3: DBeaver Plugin with AI

**Configure AI provider (OpenAI or Gemini):**

1. Install DBeaver plugin as above
2. In dialog: Select "OpenAI" or "Gemini (Google)"
3. Enter your API key
4. Generate and execute SQL

## Backend Testing

**Run all tests:**

```bash
cd backend
pytest -v
```

**Run in Docker:**

```bash
cd backend
docker build -f Dockerfile.test -t plaindb-test .
docker run plaindb-test
```

For detailed testing guide, see [backend/README.md](backend/README.md#testing).

## Running Examples

**Local pipeline demo:**

```bash
python3 examples/sqlite_demo.py
```

This demonstrates:
- Database adapter creation
- SQL verification pipeline
- Error-guided SQL regeneration
- Transaction commit/rollback

## Configuration

### Backend Environment Variables

```bash
PLAINDB_HOST=0.0.0.0           # Server host
PLAINDB_PORT=8000               # Server port
PLAINDB_DB_PATH=plaindb.sqlite  # Database file path
```

### DBeaver Plugin Configuration

Configure in DBeaver dialog:
- **Provider**: Local PlainDB, OpenAI, or Gemini
- **Backend URL**: For remote backend (e.g., `http://your-server:8000`)
- **API Key**: For OpenAI/Gemini (optional)
- **Database Type**: Target database system

## Documentation

- [Backend README](backend/README.md) - API, configuration, deployment
- [Plugin README](dbeaver-plugin/README.md) - Installation, usage, features
- [Architecture Doc](docs/architecture.md) - System design & concepts

## Development

### Adding Custom Verification Logic

Extend the base classes:

```python
from plain_db.interfaces import SemanticVerifier

class CustomVerifier(SemanticVerifier):
    def verify(self, intent, candidate):
        # Your logic
        return VerificationStageResult(stage="custom", passed=True, ...)

# Use in pipeline
pipeline = PlainDBPipeline(adapter, semantic_verifier=CustomVerifier())
```

### Adding Database Support

Implement the adapter interface:

```python
from plain_db.interfaces import DatabaseAdapter

class PostgreSQLAdapter(DatabaseAdapter):
    def __init__(self, connection_string):
        # Initialize connection
        pass
    # Implement execute(), query(), snapshot(), begin()
```

## Deployment

### Docker Deployment

```bash
cd backend
docker build -t plaindb-backend:latest .
docker run -p 8000:8000 -v plaindb_data:/data plaindb-backend:latest
```

### Kubernetes

Backend can be deployed as a Kubernetes service:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: plaindb-backend
spec:
  containers:
  - name: plaindb
    image: plaindb-backend:latest
    ports:
    - containerPort: 8000
    env:
    - name: PLAINDB_DB_PATH
      value: /data/plaindb.sqlite
    volumeMounts:
    - name: data
      mountPath: /data
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: plaindb-pvc
```

## Retry with Error-Guided SQL Regeneration

In backend pipeline, use `PipelineConfig.max_retries` and pass `regenerate_sql` callback:

```python
def regenerate_sql(intent, prev_candidate, error_context, attempt):
    # Use LLM to regenerate SQL from error
    # error_context example: "execution: no such column: scor"
    return SQLCandidate(sql=new_sql)

result = pipeline.run(intent, candidate, config, regenerate_sql)
```

The callback returns a new SQL candidate for the next attempt.

## Extending to Any Database

Implement `DatabaseAdapter` in `plain_db/interfaces.py` for each DB engine:
- PostgreSQL (`psycopg`)
- MySQL (`mysqlclient` or `pymysql`)
- SQL Server (`pyodbc`)
- Oracle (`oracledb`)

No pipeline logic changes are required when swapping adapters.

## DBeaver Plugin Integration

The `dbeaver-plugin/` folder contains a working Eclipse/DBeaver plugin scaffold.

### Quick Install

**Option 1: Direct Install (for development)**
```bash
bash scripts/run-local-dbeaver.sh
```
Builds, installs, and launches DBeaver with the plugin loaded.

**Option 2: Software Installer (for users)**
```bash
bash scripts/build-update-site.sh
```
Creates a local p2 update site, then in DBeaver:
1. **Help → Install New Software...**
2. **Add:** `file:///path/to/plainDB/update-site`
3. Select **PlainDB**, click **Finish**, restart

### Design Rules

- User-facing text must be English only
- SQL must stay hidden from the UI
- Plugin shows approval, rollback, retry, and final status only
- PlainDB owns semantic verification, safety checks, and retry logic

See [dbeaver-plugin/README.md](dbeaver-plugin/README.md) and [update-site/README.md](update-site/README.md) for detailed instructions.
