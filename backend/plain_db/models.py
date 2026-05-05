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
