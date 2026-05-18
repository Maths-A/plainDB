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
- Uses backend-driven AI execution (API key is forwarded to backend)
- Supports backend rollback IDs and rollback actions from the UI

### Verification Pipeline

The backend currently runs a **six-stage architecture pipeline**:

1. Schema introspection
  Loads database schema metadata used by downstream generation and verification steps.

2. AI SQL generation
  Generates SQL from the English request and target database context.

3. AI SQL verification
  Performs model-assisted semantic/safety checks on generated SQL.

4. AI verification-query planning
  Produces deterministic verification queries used to evaluate execution effects.

5. Transactional execution
  Executes SQL inside a transaction boundary with adapter-specific behavior.

6. Result verification and retry classification
  Verifies observed effects and classifies failures to decide accept/reject/retry.

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

### Option 3: DBeaver Plugin Account Setup

1. Install DBeaver plugin as above
2. In dialog Account tab:
  - Backend URL: `http://localhost:8000` (or your deployed backend)
  - LLM model: `gemini-2.5-flash`
  - API key/token: entered once and stored locally in plugin preferences
3. Run requests from SQL Assistant tab

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
- **Backend URL**: For local/remote backend (e.g., `http://your-server:8000`)
- **LLM Model**: Model passed to backend (default `gemini-2.5-flash`)
- **API Key**: Forwarded to backend for provider authentication
- **Database Type**: Target database system

## Rollback Model

### How rollback snapshots are created

For mutating SQL, backend creates a pre-change snapshot and returns a `rollback_id` in `/run` response. The plugin stores that ID with the corresponding "Before request" snapshot entry.

### What rollback restores

- **Backend rollback** (`POST /rollback/{rollback_id}`): restores actual database state.
- **Local rollback snapshot**: restores plugin UI state only (prompt/output/history context), not database state.

The rollback selector is backend-first by default, and entries are tagged (`[backend]` / `[local]`) so the scope is clear.

### Where rollback data is stored

Backend stores snapshot files under a temp rollback directory (for example `<tmp>/plaindb-rollbacks`) and persists snapshot metadata in `snapshot-index.json` so rollback IDs survive backend restarts when snapshot files still exist.

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

Currently implemented backend adapters:
- SQLite
- PostgreSQL (`postgres`, `postgresql`, `pg`)
- MySQL/MariaDB (`mysql`, `mariadb`)

To add more engines, implement `DatabaseAdapter` in `plain_db/interfaces.py` for each target DB (for example SQL Server via `pyodbc`, Oracle via `oracledb`).

No core pipeline logic changes are required when swapping adapters.

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
- Backend is the source of truth for commit and rollback
- Plugin clearly separates backend rollback from local UI snapshots
- PlainDB backend owns semantic verification, safety checks, and retry logic

See [dbeaver-plugin/README.md](dbeaver-plugin/README.md) and [update-site/README.md](update-site/README.md) for detailed instructions.
