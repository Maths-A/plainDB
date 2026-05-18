from dataclasses import dataclass, field
import re
from typing import Callable
from typing import Any, Dict, List, Optional

from .adapters.factory import create_database_adapter
from .models import BackendRequest, BackendRunResult, ExecutionResult, VerificationQueryResult, VerificationStageResult
from .schema import DatabaseSchema
from .llm import AIJudgement, PlainDBAIClient


@dataclass
class ArchitectureAttempt:
    generated_sql: str
    verification_queries: List[str] = field(default_factory=list)
    verification_results: List[VerificationQueryResult] = field(default_factory=list)
    execution: Optional[ExecutionResult] = None
    stages: List[VerificationStageResult] = field(default_factory=list)


class PlainDBArchitecturePipeline:
    """Backend flow aligned with the six-step architecture described in the README."""

    def __init__(self, adapter_factory=None, ai_client_factory=None) -> None:
        self.adapter_factory = adapter_factory or create_database_adapter
        self.ai_client_factory = ai_client_factory or PlainDBAIClient

    def run(
        self,
        request: BackendRequest,
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> BackendRunResult:
        if not request.english_explanation.strip():
            raise ValueError("English explanation is required.")
        if not request.api_key.strip():
            raise ValueError("API key is required.")

        adapter = self.adapter_factory(request.database)
        try:
            self._emit_progress(progress_callback, "schema", {"status": "starting"})
            schema = adapter.describe_schema()
            self._emit_progress(
                progress_callback,
                "schema",
                {"status": "ready", "table_count": len(schema.tables)},
            )
            ai_client = self.ai_client_factory(
                provider=request.ai_provider,
                api_key=request.api_key,
                model_name=request.ai_model,
                endpoint_url=request.endpoint_url,
            )

            return self._run_with_retries(adapter, schema, ai_client, request, progress_callback)
        finally:
            adapter.close()

    def _run_with_retries(
        self,
        adapter,
        schema: DatabaseSchema,
        ai_client: PlainDBAIClient,
        request: BackendRequest,
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> BackendRunResult:
        stages: List[VerificationStageResult] = []
        last_execution: Optional[ExecutionResult] = None
        last_sql = ""
        last_verification_queries: List[str] = []
        last_verification_results: List[VerificationQueryResult] = []
        last_error: Optional[str] = None
        last_error_kind: Optional[str] = None

        max_attempts = max(1, request.max_retries + 1)

        for attempt in range(1, max_attempts + 1):
            self._emit_progress(
                progress_callback,
                "generation",
                {"status": "starting", "attempt": attempt, "max_attempts": max_attempts},
            )
            if hasattr(ai_client, "generate_sql_with_verification"):
                generation_result = ai_client.generate_sql_with_verification(
                    request.english_explanation,
                    schema,
                    attempt=attempt,
                    previous_sql=last_sql or None,
                    previous_error=last_error,
                )
                generated_sql = generation_result["sql"]
                sql_verification = generation_result["verification"]
            else:
                generated_sql = ai_client.generate_sql(
                    request.english_explanation,
                    schema,
                    attempt=attempt,
                    previous_sql=last_sql or None,
                    previous_error=last_error,
                )
                sql_verification = ai_client.verify_sql(request.english_explanation, generated_sql, schema)
            last_sql = generated_sql
            stages.append(
                VerificationStageResult(
                    stage="generation",
                    passed=True,
                    reason="AI generated SQL from the English explanation.",
                    details={"attempt": attempt, "sql": generated_sql},
                )
            )
            self._emit_progress(
                progress_callback,
                "generation",
                {
                    "status": "done",
                    "attempt": attempt,
                    "passed": sql_verification.passed,
                    "reason": sql_verification.reason,
                },
            )

            stages.append(
                VerificationStageResult(
                    stage="sql_verification",
                    passed=sql_verification.passed,
                    reason=sql_verification.reason,
                    details={"attempt": attempt, **sql_verification.details},
                )
            )
            if not sql_verification.passed:
                self._emit_progress(
                    progress_callback,
                    "sql_verification",
                    {
                        "status": "failed",
                        "attempt": attempt,
                        "reason": sql_verification.reason,
                    },
                )
                last_error = sql_verification.reason
                last_error_kind = "sql_generated"
                if sql_verification.retry and attempt < max_attempts:
                    continue
                return BackendRunResult(
                    accepted=False,
                    committed=False,
                    generated_sql=generated_sql,
                    verification_queries=[],
                    verification_results=[],
                    execution=None,
                    stages=stages,
                    attempts=attempt,
                    error=sql_verification.reason,
                    error_kind="sql_generated",
                    schema=schema.to_prompt_payload(),
                )
            self._emit_progress(
                progress_callback,
                "sql_verification",
                {"status": "passed", "attempt": attempt},
            )

            self._emit_progress(
                progress_callback,
                "verification_query_planning",
                {"status": "starting", "attempt": attempt},
            )
            verification_queries = ai_client.generate_verification_queries(request.english_explanation, schema, generated_sql)
            last_verification_queries = verification_queries
            stages.append(
                VerificationStageResult(
                    stage="verification_query_planning",
                    passed=True,
                    reason="AI generated verification SELECT queries.",
                    details={"attempt": attempt, "queries": verification_queries},
                )
            )
            self._emit_progress(
                progress_callback,
                "verification_query_planning",
                {"status": "done", "attempt": attempt, "query_count": len(verification_queries)},
            )

            try:
                with adapter.begin() as tx:
                    self._emit_progress(
                        progress_callback,
                        "execution",
                        {"status": "starting", "attempt": attempt},
                    )
                    execution = adapter.execute(tx, generated_sql)
                    last_execution = execution
                    stages.append(
                        VerificationStageResult(
                            stage="execution",
                            passed=execution.success,
                            reason="SQL executed successfully." if execution.success else "SQL execution failed.",
                            details={"attempt": attempt, "rowcount": execution.rowcount, "error": execution.error},
                        )
                    )
                    self._emit_progress(
                        progress_callback,
                        "execution",
                        {
                            "status": "done",
                            "attempt": attempt,
                            "success": execution.success,
                            "rowcount": execution.rowcount,
                        },
                    )

                    # For DML statements that must affect rows, zero rowcount means the
                    # target rows did not exist — treat as a rejection immediately so the
                    # pipeline doesn't silently succeed on a no-op.
                    if execution.success and execution.rowcount == 0 and self._is_row_mutating_sql(generated_sql):
                        tx.rollback()
                        no_op_reason = (
                            "The SQL executed without error but affected 0 rows. "
                            "The targeted row(s) may not exist."
                        )
                        stages.append(
                            VerificationStageResult(
                                stage="execution_rowcount",
                                passed=False,
                                reason=no_op_reason,
                                details={"attempt": attempt, "rowcount": 0},
                            )
                        )
                        self._emit_progress(
                            progress_callback,
                            "execution_rowcount",
                            {"status": "zero_rows_affected", "attempt": attempt},
                        )
                        last_error = no_op_reason
                        last_error_kind = "no_rows_affected"
                        return BackendRunResult(
                            accepted=False,
                            committed=False,
                            generated_sql=generated_sql,
                            verification_queries=verification_queries,
                            verification_results=[],
                            execution=execution,
                            stages=stages,
                            attempts=attempt,
                            error=no_op_reason,
                            error_kind=last_error_kind,
                            schema=schema.to_prompt_payload(),
                        )

                    if not execution.success:
                        tx.rollback()
                        self._emit_progress(
                            progress_callback,
                            "execution_error_classification",
                            {"status": "starting", "attempt": attempt},
                        )
                        classification = ai_client.classify_execution_error(
                            request.english_explanation,
                            generated_sql,
                            execution.error or "Unknown execution error.",
                            schema,
                        )
                        stages.append(
                            VerificationStageResult(
                                stage="execution_error_classification",
                                passed=not classification.retry,
                                reason=classification.reason,
                                details={"attempt": attempt, **classification.details},
                            )
                        )
                        self._emit_progress(
                            progress_callback,
                            "execution_error_classification",
                            {
                                "status": "done",
                                "attempt": attempt,
                                "retry": classification.retry,
                                "reason": classification.reason,
                            },
                        )
                        last_error = classification.reason
                        last_error_kind = classification.details.get("kind", "unknown")
                        if classification.retry and attempt < max_attempts:
                            continue
                        return BackendRunResult(
                            accepted=False,
                            committed=False,
                            generated_sql=generated_sql,
                            verification_queries=verification_queries,
                            verification_results=[],
                            execution=execution,
                            stages=stages,
                            attempts=attempt,
                            error=classification.reason,
                            error_kind=last_error_kind,
                            schema=schema.to_prompt_payload(),
                        )

                    self._emit_progress(
                        progress_callback,
                        "verification_execution",
                        {"status": "starting", "attempt": attempt, "query_count": len(verification_queries)},
                    )
                    verification_results = self._run_verification_queries(adapter, tx, verification_queries)
                    last_verification_results = verification_results
                    self._emit_progress(
                        progress_callback,
                        "verification_execution",
                        {"status": "done", "attempt": attempt},
                    )

                    verification_judgement: AIJudgement
                    if self._is_read_only_select(generated_sql):
                        select_passed = all(item.passed for item in verification_results)
                        verification_judgement = AIJudgement(
                            passed=select_passed,
                            reason=(
                                "Read-only SELECT verified via deterministic query execution."
                                if select_passed
                                else "One or more deterministic verification queries failed."
                            ),
                            retry=False,
                            details={
                                "kind": "deterministic_select_verification" if select_passed else "verification_failed",
                                "skipped_llm": True,
                            },
                        )
                    else:
                        self._emit_progress(
                            progress_callback,
                            "verification",
                            {"status": "starting", "attempt": attempt},
                        )
                        verification_payload = [
                            {"query": item.query, "rows": item.rows, "passed": item.passed, "reason": item.reason}
                            for item in verification_results
                        ]
                        verification_judgement = ai_client.verify_results(
                            request.english_explanation,
                            generated_sql,
                            verification_queries,
                            verification_payload,
                            schema,
                        )

                    stages.append(
                        VerificationStageResult(
                            stage="verification",
                            passed=verification_judgement.passed,
                            reason=verification_judgement.reason,
                            details={"attempt": attempt, **verification_judgement.details},
                        )
                    )
                    self._emit_progress(
                        progress_callback,
                        "verification",
                        {
                            "status": "done",
                            "attempt": attempt,
                            "passed": verification_judgement.passed,
                            "reason": verification_judgement.reason,
                            "skipped_llm": bool(verification_judgement.details.get("skipped_llm", False)),
                        },
                    )

                    if not verification_judgement.passed:
                        tx.rollback()
                        last_error = verification_judgement.reason
                        last_error_kind = verification_judgement.details.get("kind", "verification_failed")
                        if verification_judgement.retry and attempt < max_attempts:
                            continue
                        return BackendRunResult(
                            accepted=False,
                            committed=False,
                            generated_sql=generated_sql,
                            verification_queries=verification_queries,
                            verification_results=verification_results,
                            execution=execution,
                            stages=stages,
                            attempts=attempt,
                            error=verification_judgement.reason,
                            error_kind=last_error_kind,
                            schema=schema.to_prompt_payload(),
                        )

                    if request.dry_run:
                        tx.rollback()
                        self._emit_progress(
                            progress_callback,
                            "commit",
                            {"status": "dry_run_rollback", "attempt": attempt},
                        )
                        stages.append(
                            VerificationStageResult(
                                stage="commit",
                                passed=True,
                                reason="Dry-run mode enabled; transaction rolled back.",
                                details={"attempt": attempt},
                            )
                        )
                        return BackendRunResult(
                            accepted=True,
                            committed=False,
                            generated_sql=generated_sql,
                            verification_queries=verification_queries,
                            verification_results=verification_results,
                            execution=execution,
                            stages=stages,
                            attempts=attempt,
                            schema=schema.to_prompt_payload(),
                        )

                    tx.commit()

                self._emit_progress(
                    progress_callback,
                    "commit",
                    {"status": "committed", "attempt": attempt},
                )
                stages.append(
                    VerificationStageResult(
                        stage="commit",
                        passed=True,
                        reason="Transaction committed.",
                        details={"attempt": attempt},
                    )
                )
                return BackendRunResult(
                    accepted=True,
                    committed=True,
                    generated_sql=generated_sql,
                    verification_queries=verification_queries,
                    verification_results=verification_results,
                    execution=execution,
                    stages=stages,
                    attempts=attempt,
                    schema=schema.to_prompt_payload(),
                )

            except Exception as exc:
                last_error = str(exc)
                last_error_kind = "human"
                self._emit_progress(
                    progress_callback,
                    "execution_error",
                    {"status": "failed", "attempt": attempt, "reason": last_error},
                )
                stages.append(
                    VerificationStageResult(
                        stage="execution_error",
                        passed=False,
                        reason=last_error,
                        details={"attempt": attempt, "kind": last_error_kind},
                    )
                )
                if attempt < max_attempts:
                    continue
                return BackendRunResult(
                    accepted=False,
                    committed=False,
                    generated_sql=generated_sql,
                    verification_queries=verification_queries,
                    verification_results=last_verification_results,
                    execution=last_execution,
                    stages=stages,
                    attempts=attempt,
                    error=last_error,
                    error_kind=last_error_kind,
                    schema=schema.to_prompt_payload(),
                )

        return BackendRunResult(
            accepted=False,
            committed=False,
            generated_sql=last_sql or None,
            verification_queries=last_verification_queries,
            verification_results=last_verification_results,
            execution=last_execution,
            stages=stages,
            attempts=max_attempts,
            error=last_error,
            error_kind=last_error_kind,
            schema=schema.to_prompt_payload(),
        )

    @staticmethod
    def _emit_progress(
        callback: Optional[Callable[[str, Dict[str, Any]], None]],
        stage: str,
        details: Dict[str, Any],
    ) -> None:
        if callback is None:
            return
        callback(stage, details)

    @staticmethod
    def _is_read_only_select(sql: str) -> bool:
        if not sql:
            return False
        return sql.strip().upper().startswith("SELECT")

    @staticmethod
    def _is_row_mutating_sql(sql: str) -> bool:
        """Return True for DML statements that must affect at least one row to be meaningful."""
        if not sql:
            return False
        text = sql.strip()
        text = re.sub(r"^(?:\s|;+|--[^\n]*\n|/\*.*?\*/)+", "", text, flags=re.DOTALL)
        verb = text.upper().split()[0] if text else ""
        return verb in {"DELETE", "UPDATE"}

    def _run_verification_queries(
        self,
        adapter,
        tx,
        verification_queries: List[str],
    ) -> List[VerificationQueryResult]:
        results: List[VerificationQueryResult] = []
        for query in verification_queries:
            try:
                rows = adapter.query(tx, query)
                results.append(VerificationQueryResult(query=query, rows=rows, passed=True))
            except Exception as exc:
                results.append(VerificationQueryResult(query=query, rows=[], passed=False, reason=str(exc)))
        return results