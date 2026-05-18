from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class UserIntent:
    """Natural-language request and optional structured expectations."""

    text: str
    expected_tables: List[str] = field(default_factory=list)
    expected_action: Optional[str] = None


@dataclass
class SQLCandidate:
    """AI generated SQL statement."""

    sql: str
    params: Optional[Dict[str, Any]] = None
    model_name: Optional[str] = None


@dataclass
class VerificationStageResult:
    stage: str
    passed: bool
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    success: bool
    rowcount: int
    lastrowid: Optional[int] = None
    rows: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class PipelineConfig:
    """Runtime knobs for pipeline behavior."""

    fail_fast: bool = True
    dry_run_only: bool = False
    watched_tables: List[str] = field(default_factory=list)
    max_retries: int = 0


@dataclass
class PipelineResult:
    accepted: bool
    committed: bool
    stages: List[VerificationStageResult]
    execution: Optional[ExecutionResult] = None
    attempts: int = 1


@dataclass
class DatabaseTarget:
    """Database target information and credentials supplied to the API."""

    dialect: str
    database: str
    username: Optional[str] = None
    password: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    schema_name: Optional[str] = None
    connection_string: Optional[str] = None
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BackendRequest:
    """Architecture-oriented API request."""

    english_explanation: str
    ai_provider: str
    api_key: str
    database: DatabaseTarget
    ai_model: Optional[str] = None
    endpoint_url: Optional[str] = None
    dry_run: bool = False
    max_retries: int = 0


@dataclass
class VerificationQueryResult:
    """Execution result for a generated verification query."""

    query: str
    rows: List[Dict[str, Any]] = field(default_factory=list)
    passed: bool = True
    reason: Optional[str] = None


@dataclass
class BackendRunResult:
    """End-to-end result for the backend architecture flow."""

    accepted: bool
    committed: bool
    generated_sql: Optional[str]
    verification_queries: List[str]
    verification_results: List[VerificationQueryResult]
    execution: Optional[ExecutionResult] = None
    stages: List[VerificationStageResult] = field(default_factory=list)
    attempts: int = 1
    error: Optional[str] = None
    error_kind: Optional[str] = None
    schema: Optional[Dict[str, Any]] = None
