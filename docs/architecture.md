# PlainDB Architecture

**PlainDB** is a two-tier system providing safe AI-generated SQL execution through a modular verification pipeline.

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    DBeaver Application                       │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         PlainDB Plugin (Java/Eclipse)               │  │
│  │  • Dialog UI for SQL requests                       │  │
│  │  • Account/provider management                      │  │
│  │  • Request routing (to AI or backend)               │  │
│  └──────────────┬───────────────────────────────────────┘  │
│                 │                                           │
│                 │ HTTP/REST                                │
│                 ▼                                           │
└─────────────────────────────────────────────────────────────┘
                   │
    ┌──────────────┴──────────────────┐
    │                                  │
    ▼                                  ▼
┌─────────────────┐         ┌──────────────────────┐
│  AI Providers   │         │  PlainDB Backend API │
│  • OpenAI       │         │  (FastAPI)           │
│  • Gemini       │         │  • /api/v1/generate- │
│  • Custom       │         │    sql               │
└─────────────────┘         │  • /health           │
                            │  • /info             │
                            └──────────┬───────────┘
                                       │
                            ┌──────────▼──────────┐
                            │ PlainDB Backend     │
                            │ (Python)            │
                            │                     │
                            │ Pipeline Engine:    │
                            │ • Semantic check    │
                            │ • Safety rules      │
                            │ • Effect verify     │
                            │ • Post-commit check │
                            │                     │
                            │ Adapters:           │
                            │ • SQLite            │
                            │ • PostgreSQL        │
                            │ • MySQL (future)    │
                            └──────────┬──────────┘
                                       │
                                       ▼
                            ┌──────────────────┐
                            │  User Database   │
                            │  (SQLite, PG,    │
                            │   MySQL, etc)    │
                            └──────────────────┘
```

## Why This Is Safer Than Direct AI Execution

AI SQL generation can be:
- **Semantically wrong** - SQL is valid but doesn't match user intent
- **Syntactically valid but dangerous** - Valid SQL that drops tables, grants privileges, etc
- **Operationally successful but incorrect** - Changes data in wrong way

**PlainDB introduces gated verification before AND after execution:**

1. **Semantic verification** - Does SQL match what user asked for?
2. **Safety verification** - Would this operation violate policy?
3. **Execution verification** - Did SQL run without errors?
4. **Effect verification** - Did data change in expected direction?
5. **Post-commit verification** - Is final state correct?

Only if all checks pass do changes persist to the database.

## Architecture Components

### Component 1: DBeaver Plugin

**Location:** `dbeaver-plugin/`  
**Language:** Java 21 (Eclipse OSGi)  
**Role:** User interface layer

**Key Classes:**
- `PlainDbMainDialog.java` - Main verification dialog
- `SqlGeneratorClient.java` - HTTP client for backend/AI
- `PlainDbServiceClient.java` - Service integration
- `EnglishOnlyGuard.java` - Input validation

**Responsibilities:**
- Display UI for SQL requests
- Route requests to backend or AI providers
- Format and display verification results
- Manage account configuration (API keys, backend URL)

### Component 2: REST API

**Location:** `backend/api/main.py`  
**Framework:** FastAPI  
**Purpose:** HTTP interface to verification pipeline

**Main Endpoint:**
```
POST /api/v1/generate-sql

Request:
{
  "intent_text": "Show users older than 25",
  "expected_tables": ["users"],
  "expected_action": "SELECT",
  "dry_run": false,
  "watched_tables": ["users"]
}

Response:
{
  "accepted": true,
  "committed": true,
  "sql": "SELECT * FROM users WHERE age > 25",
  "stages": [
    {"stage": "semantic", "passed": true, ...},
    {"stage": "safety", "passed": true, ...},
    {"stage": "execution", "passed": true, ...},
    {"stage": "effect", "passed": true, ...},
    {"stage": "post_commit", "passed": true, ...}
  ],
  "attempts": 1,
  "execution": {"success": true, "rowcount": 42}
}
```

### Component 3: Pipeline Engine

**Location:** `backend/plain_db/pipeline.py`  
**Purpose:** Five-stage verification of AI-generated SQL

**Verification Flow:**

```
INPUT: UserIntent + SQLCandidate
  │
  ├─→ STAGE 1: SEMANTIC VERIFICATION
  │     └─ Does action (SELECT/INSERT/UPDATE/DELETE) match intent?
  │     └─ Are expected tables present in SQL?
  │     └─ Decision: PASS/FAIL
  │
  ├─→ STAGE 2: SAFETY VERIFICATION
  │     └─ Is operation forbidden? (DROP, TRUNCATE, GRANT, REVOKE)
  │     └─ Are there multiple statements? (not allowed)
  │     └─ Decision: PASS/FAIL
  │
  ├─→ STAGE 3: EXECUTION
  │     └─ Run SQL in transaction
  │     └─ Capture row count, errors
  │     └─ Decision: SUCCESS/FAILURE
  │
  ├─→ STAGE 4: EFFECT VERIFICATION
  │     └─ Compare row count changes to direction
  │     └─ INSERT → row count increases
  │     └─ DELETE → row count decreases
  │     └─ Decision: EXPECTED/UNEXPECTED
  │
  └─→ STAGE 5: POST-COMMIT VERIFICATION
        └─ Confirm final database state after commit
        └─ Tables still readable and consistent
        └─ Decision: VERIFIED/INCONSISTENT
  
OUTPUT: PipelineResult {
  accepted: bool,
  committed: bool,
  stages: List[VerificationStageResult],
  execution: Optional[ExecutionResult],
  attempts: int
}
```

### Component 4: Database Adapters

**Location:** `backend/plain_db/adapters/`  
**Role:** Abstraction layer for different databases

**Adapter Interface:**
```python
class DatabaseAdapter:
    def begin(self) -> TransactionHandle        # Start transaction
    def execute(sql, params) -> ExecutionResult # Run INSERT/UPDATE/DELETE
    def query(sql, params) -> List[Dict]        # Fetch SELECT results
    def snapshot(tables) -> Dict[str, int]      # Capture row counts
```

**Implementations:**
- `SQLiteAdapter` - SQLite (built-in)
- `PostgreSQLAdapter` - PostgreSQL (example template)

## Request Lifecycle

### 1. User Submits Request in DBeaver

```
User Input: "Show users older than 25"
    │
    ├─ EnglishOnlyGuard validates
    │   └─ YES: Continue
    │   └─ NO: Show error, block
    │
    ├─ Build HTTP request:
    │   POST /api/v1/generate-sql
    │   {
    │     "intent_text": "Show users older than 25",
    │     "expected_tables": ["users"],
    │     "expected_action": "SELECT"
    │   }
    │
    └─ Send to backend (or AI provider)
```

### 2. Backend Processes Request

```
HTTP Request Received
    │
    ├─ Parse JSON
    │
    ├─ Create domain models:
    │   intent = UserIntent("Show users older than 25", ["users"], "SELECT")
    │   candidate = SQLCandidate("SELECT * FROM users WHERE age > 25")
    │
    ├─ Initialize pipeline with:
    │   • DatabaseAdapter (SQLite, PostgreSQL, etc)
    │   • SemanticVerifier (heuristic or LLM)
    │   • SafetyVerifier (rule-based)
    │   • EffectVerifier (row count changes)
    │   • PostCommitVerifier (consistency checks)
    │
    ├─ Run verification pipeline
    │   ├─ Semantic: action=SELECT, expected_tables=['users'] ✓
    │   ├─ Safety: no forbidden patterns ✓
    │   ├─ Execution: run in txn, success, 42 rows ✓
    │   ├─ Effect: rows didn't change (SELECT) ✓
    │   └─ Post-commit: table readable ✓
    │
    └─ Return JSON response with all stages + result
```

### 3. DBeaver Displays Results

```
Response Received
    │
    ├─ Parse JSON
    │
    ├─ Format for display:
    │   ✓ Semantic verification passed
    │   ✓ Safety verification passed
    │   ✓ Execution successful (42 rows)
    │   ✓ Effect verification passed
    │   ✓ Post-commit verification passed
    │
    └─ Show generated SQL and result
```

## Data Models

### UserIntent
```python
UserIntent(
  text: str,                    # "Show users older than 25"
  expected_tables: List[str],   # ["users"]
  expected_action: str          # "SELECT"
)
```

### SQLCandidate
```python
SQLCandidate(
  sql: str,                     # "SELECT * FROM users WHERE age > 25"
  params: Dict[str, Any],       # {"min_age": 25}
  model_name: str               # "gemini-2.5-flash"
)
```

### VerificationStageResult
```python
VerificationStageResult(
  stage: str,                   # "semantic"
  passed: bool,                 # True
  reason: str,                  # "Intent and SQL are aligned"
  details: Dict[str, Any]       # {"action": "SELECT", "tables": ["users"]}
)
```

### PipelineResult
```python
PipelineResult(
  accepted: bool,               # SQL passed all checks
  committed: bool,              # Changes persisted
  stages: List[VerificationStageResult],
  execution: ExecutionResult,   # {"success": true, "rowcount": 42}
  attempts: int                 # 1 (or > 1 if retried)
)
```

## Extension Points

### 1. Add Custom Verifier

```python
from plain_db.interfaces import SemanticVerifier

class LLMSemanticVerifier(SemanticVerifier):
    def verify(self, intent, candidate):
        # Call external LLM API
        # Return VerificationStageResult(stage="semantic", passed=True/False, ...)
        pass

# Use in pipeline
pipeline = PlainDBPipeline(
    adapter=adapter,
    semantic_verifier=LLMSemanticVerifier()
)
```

### 2. Add Database Support

```python
from plain_db.interfaces import DatabaseAdapter

class PostgreSQLAdapter(DatabaseAdapter):
    def __init__(self, connection_string):
        self.conn = psycopg2.connect(connection_string)
    
    def begin(self):
        # Start transaction
        pass
    
    def execute(self, tx, sql, params=None):
        # Run INSERT/UPDATE/DELETE
        pass
    
    # ... implement other methods
```

### 3. Add Custom Safety Rules

```python
from plain_db.interfaces import SafetyVerifier

class CompanyPolicyVerifier(SafetyVerifier):
    def verify(self, candidate):
        # Check against company policies
        # E.g., no deletes from audit tables
        pass

# Use in pipeline
pipeline = PlainDBPipeline(
    adapter=adapter,
    safety_verifier=CompanyPolicyVerifier()
)
```

## Deployment Scenarios

### Scenario 1: Local Development
- Backend: `python -m uvicorn api.main:app --reload`
- Plugin: Installed into local DBeaver
- Communication: `http://localhost:8000`

### Scenario 2: Docker Development
- Backend: `docker-compose up`
- Plugin: Installed into local DBeaver
- Communication: `http://localhost:8000`

### Scenario 3: Production
- Backend: Kubernetes deployment with replicas
- Plugin: Installed into DBeaver
- Communication: `https://plaindb.company.com`

### Scenario 4: Embedded (no DBeaver)
- Import plaindb package directly in Python app
- Use as library in custom application
- No plugin needed

## Security Model

### Input Validation
- **English-only guard** in plugin
- **Request validation** in FastAPI
- **SQL pattern matching** for forbidden operations

### SQL Safety
- **Parameterized queries** prevent injection
- **Forbidden patterns** blocked before execution
- **Transaction rollback** on errors

### Database Safety
- **All SQL runs in transaction**
- **Snapshots track row counts** (detect anomalies)
- **Verification stages provide audit trail**

### Network Security
- Backend behind firewall in production
- HTTPS for remote deployments
- OAuth2 for authentication (future)

## Testing

**Unit Tests:**
- Verifier behavior (`tests/test_pipeline.py`)
- Adapter functions
- Data model validation

**Integration Tests:**
- End-to-end pipeline
- API endpoints (`tests/test_api.py`)
- Database operations

**Run Tests:**
```bash
cd backend
pytest -v                    # All tests
pytest tests/test_api.py     # API tests only
pytest --cov               # With coverage
```

## Performance

- **FastAPI**: Non-blocking async I/O
- **SQLite**: <1ms for query operations
- **Pipeline**: ~50-100ms total (including I/O)
- **HTTP latency**: ~100-500ms (network dependent)

## See Also

- [Root README](../README.md) - Project overview
- [Backend README](../backend/README.md) - Deployment and API details
- [Plugin README](../dbeaver-plugin/README.md) - Installation and usage

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
