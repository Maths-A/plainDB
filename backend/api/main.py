import os
import re
import json
import queue
import threading
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import StreamingResponse

from plain_db.architecture import PlainDBArchitecturePipeline
from plain_db.models import (
    BackendRequest,
    BackendRunResult,
    DatabaseTarget,
    ExecutionResult,
    VerificationQueryResult,
    VerificationStageResult,
)
from plain_db.rollback import RollbackService


class _TestSqlPipeline:
    """Stub pipeline used when PLAINDB_TEST_SQL env var is set.

    Executes the SQL literally and returns a committed BackendRunResult, allowing
    full HTTP-level integration tests without a live LLM key.
    """

    def __init__(self, sql: str) -> None:
        self._sql = sql

    def run(self, request: BackendRequest, progress_callback=None) -> BackendRunResult:
        from plain_db.adapters.sqlite_adapter import SQLiteAdapter
        from plain_db.adapters.postgresql_adapter import PostgreSQLAdapter
        from plain_db.adapters.mysql_adapter import MySQLAdapter

        t = request.database
        dialect = t.dialect

        if dialect in ("postgresql", "postgres"):
            adapter = PostgreSQLAdapter(
                database=t.database,
                username=t.username,
                password=t.password,
                host=t.host,
                port=t.port,
                schema_name=t.schema_name,
                connection_string=t.connection_string,
                options=t.options or {},
            )
        elif dialect == "mysql":
            adapter = MySQLAdapter(
                database=t.database,
                username=t.username,
                password=t.password,
                host=t.host,
                port=t.port,
                options=t.options or {},
            )
        elif dialect == "sqlite":
            adapter = SQLiteAdapter(db_path=t.database)
        else:
            raise ValueError(f"No test adapter for dialect '{dialect}'")

        rowcount = 0
        with adapter.begin() as tx:
            result = adapter.execute(tx, self._sql)
            rowcount = result.rowcount if result.rowcount >= 0 else 0
            tx.commit()
        return BackendRunResult(
            accepted=True,
            committed=True,
            generated_sql=self._sql,
            verification_queries=["SELECT 1"],
            verification_results=[VerificationQueryResult(query="SELECT 1", rows=[{"ok": 1}], passed=True)],
            execution=ExecutionResult(success=True, rowcount=rowcount),
            stages=[VerificationStageResult(stage="commit", passed=True, reason="test-pipeline committed")],
            attempts=1,
            schema={"dialect": dialect, "tables": []},
        )


DEFAULT_DATABASE = os.environ.get("PLAINDB_DEFAULT_DATABASE", os.environ.get("PLAINDB_DATABASE", ":memory:"))
DEFAULT_PROVIDER = os.environ.get("PLAINDB_DEFAULT_AI_PROVIDER", "gemini")
DEFAULT_MODEL = os.environ.get("PLAINDB_DEFAULT_MODEL")


class DatabaseTargetRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    dialect: str = "sqlite"
    database: str = Field(default=DEFAULT_DATABASE)
    username: Optional[str] = None
    password: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    schema_name: Optional[str] = Field(default=None, alias="schema")
    connection_string: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)


class BackendRequestBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    english_explanation: str = Field(alias="intent_text")
    ai_provider: str = Field(default=DEFAULT_PROVIDER, alias="provider")
    api_key: str
    ai_model: Optional[str] = Field(default=DEFAULT_MODEL, alias="model_name")
    endpoint_url: Optional[str] = None
    database: DatabaseTargetRequest = Field(alias="database_target")
    dry_run: bool = True
    max_retries: int = 0


class VerificationQueryResponse(BaseModel):
    query: str
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    passed: bool
    reason: Optional[str] = None


class StageResponse(BaseModel):
    stage: str
    passed: bool
    reason: str
    details: Dict[str, Any] = Field(default_factory=dict)


class ExecutionResponse(BaseModel):
    success: bool
    rowcount: int
    lastrowid: Optional[int] = None
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


class BackendResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    accepted: bool
    committed: bool
    sql: Optional[str] = None
    generated_sql: Optional[str] = None
    verification_queries: List[str] = Field(default_factory=list)
    verification_results: List[VerificationQueryResponse] = Field(default_factory=list)
    execution: Optional[ExecutionResponse] = None
    stages: List[StageResponse] = Field(default_factory=list)
    attempts: int = 0
    error: Optional[str] = None
    error_kind: Optional[str] = None
    rollback_id: Optional[str] = None
    database_schema: Dict[str, Any] = Field(default_factory=dict, alias="schema")


class RollbackSnapshotResponse(BaseModel):
    rollback_id: str
    dialect: str
    database: str
    created_at: str
    source_sql: Optional[str] = None


class RollbackApplyResponse(BaseModel):
    rollback_id: str
    applied: bool
    message: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    test_sql = os.environ.get("PLAINDB_TEST_SQL")
    app.state.pipeline = _TestSqlPipeline(test_sql) if test_sql else PlainDBArchitecturePipeline()
    app.state.rollback_service = RollbackService()
    yield


app = FastAPI(title="PlainDB Backend", lifespan=lifespan)


def _status_from_exception(exc: Exception) -> int:
    text = "" if exc is None else str(exc)
    match = re.search(r"API error\s+(\d{3})", text)
    if match:
        code = int(match.group(1))
        if 400 <= code <= 599:
            return code
    return 400


def _to_backend_request(payload: BackendRequestBody) -> BackendRequest:
    return BackendRequest(
        english_explanation=payload.english_explanation,
        ai_provider=payload.ai_provider,
        api_key=payload.api_key,
        ai_model=payload.ai_model,
        endpoint_url=payload.endpoint_url,
        database=DatabaseTarget(
            dialect=payload.database.dialect,
            database=payload.database.database,
            username=payload.database.username,
            password=payload.database.password,
            host=payload.database.host,
            port=payload.database.port,
            schema_name=payload.database.schema_name,
            connection_string=payload.database.connection_string,
            options=payload.database.options,
        ),
        dry_run=payload.dry_run,
        max_retries=payload.max_retries,
    )


def _to_response(payload, rollback_id: Optional[str] = None) -> BackendResponse:
    execution = None
    if payload.execution is not None:
        execution = ExecutionResponse(
            success=payload.execution.success,
            rowcount=payload.execution.rowcount,
            lastrowid=payload.execution.lastrowid,
            rows=payload.execution.rows,
            error=payload.execution.error,
        )

    return BackendResponse(
        accepted=payload.accepted,
        committed=payload.committed,
        sql=payload.generated_sql,
        generated_sql=payload.generated_sql,
        verification_queries=payload.verification_queries,
        verification_results=[
            VerificationQueryResponse(
                query=item.query,
                rows=item.rows,
                passed=item.passed,
                reason=item.reason,
            )
            for item in payload.verification_results
        ],
        execution=execution,
        stages=[
            StageResponse(
                stage=item.stage,
                passed=item.passed,
                reason=item.reason,
                details=item.details,
            )
            for item in payload.stages
        ],
        attempts=payload.attempts,
        error=payload.error,
        error_kind=payload.error_kind,
        rollback_id=rollback_id,
        database_schema=payload.schema,
    )


def _is_mutating_sql(sql: Optional[str]) -> bool:
    if not sql:
        return False
    # Skip leading comments/semicolons so mutating SQL like
    # "/* note */ ALTER TABLE ..." still produces rollback snapshots.
    text = sql.strip()
    text = re.sub(r"^(?:\s|;+|--[^\n]*\n|/\*.*?\*/)+", "", text, flags=re.DOTALL)
    first_token = text.split(None, 1)[0].upper() if text else ""
    return first_token in {"INSERT", "UPDATE", "DELETE", "REPLACE", "MERGE", "CREATE", "ALTER", "DROP", "TRUNCATE"}


@app.get("/")
def root() -> Dict[str, str]:
    return {
        "message": "PlainDB backend is running",
        "request_contract": "Send english_explanation, api_key, ai_provider, and database credentials.",
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "default_provider": DEFAULT_PROVIDER,
        "default_database": DEFAULT_DATABASE,
        "default_model": DEFAULT_MODEL,
    }


@app.post("/run", response_model=BackendResponse)
def run_request(payload: BackendRequestBody) -> BackendResponse:
    backend_request = _to_backend_request(payload)
    pipeline: PlainDBArchitecturePipeline = app.state.pipeline
    rollback_service: RollbackService = app.state.rollback_service
    pending_snapshot = None

    try:
        pending_snapshot = rollback_service.prepare(backend_request.database)
        result = pipeline.run(backend_request)
    except Exception as exc:
        if pending_snapshot is not None:
            rollback_service.discard(pending_snapshot)
        raise HTTPException(status_code=_status_from_exception(exc), detail=str(exc)) from exc

    rollback_id = None
    if pending_snapshot is not None:
        if result.committed and _is_mutating_sql(result.generated_sql):
            rollback_id = rollback_service.commit(pending_snapshot, source_sql=result.generated_sql)
        else:
            rollback_service.discard(pending_snapshot)

    return _to_response(result, rollback_id=rollback_id)


@app.post("/run/stream")
def run_request_stream(payload: BackendRequestBody) -> StreamingResponse:
    backend_request = _to_backend_request(payload)
    pipeline: PlainDBArchitecturePipeline = app.state.pipeline
    rollback_service: RollbackService = app.state.rollback_service

    def event_stream():
        event_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()

        def send_progress(stage: str, details: Dict[str, Any]) -> None:
            event_queue.put(
                {
                    "event": "progress",
                    "stage": stage,
                    "message": _progress_message(stage, details),
                    "details": details,
                }
            )

        def worker() -> None:
            pending_snapshot = None
            try:
                pending_snapshot = rollback_service.prepare(backend_request.database)
                result = pipeline.run(backend_request, progress_callback=send_progress)
            except Exception as exc:
                if pending_snapshot is not None:
                    rollback_service.discard(pending_snapshot)
                event_queue.put(
                    {
                        "event": "error",
                        "status": _status_from_exception(exc),
                        "error": str(exc),
                    }
                )
                event_queue.put({"event": "done"})
                return

            rollback_id = None
            if pending_snapshot is not None:
                if result.committed and _is_mutating_sql(result.generated_sql):
                    rollback_id = rollback_service.commit(pending_snapshot, source_sql=result.generated_sql)
                else:
                    rollback_service.discard(pending_snapshot)

            response = _to_response(result, rollback_id=rollback_id)
            final_payload = response.model_dump(by_alias=True)
            final_payload["event"] = "final"
            event_queue.put(final_payload)
            event_queue.put({"event": "done"})

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        while True:
            event = event_queue.get()
            if event.get("event") == "done":
                break
            # Emit compact JSON so the plugin's lightweight parser can match keys reliably.
            yield json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


def _progress_message(stage: str, details: Dict[str, Any]) -> str:
    status = str(details.get("status", "")).strip().replace("_", " ")
    attempt = details.get("attempt")
    suffix = f" (attempt {attempt})" if attempt is not None else ""

    if status:
        return f"{stage}: {status}{suffix}"
    return f"{stage}{suffix}"


@app.get("/rollback/snapshots", response_model=List[RollbackSnapshotResponse])
def list_rollbacks() -> List[RollbackSnapshotResponse]:
    rollback_service: RollbackService = app.state.rollback_service
    return [
        RollbackSnapshotResponse(
            rollback_id=item.snapshot_id,
            dialect=item.dialect,
            database=item.database_path,
            created_at=item.created_at,
            source_sql=item.source_sql,
        )
        for item in rollback_service.list_snapshots()
    ]


@app.post("/rollback/{rollback_id}", response_model=RollbackApplyResponse)
def apply_rollback(rollback_id: str) -> RollbackApplyResponse:
    rollback_service: RollbackService = app.state.rollback_service
    try:
        rollback_service.rollback(rollback_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return RollbackApplyResponse(
        rollback_id=rollback_id,
        applied=True,
        message="Rollback applied successfully.",
    )
