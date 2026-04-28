from dataclasses import dataclass
from typing import Callable, List

from .default_verifiers import (
    HeuristicSemanticVerifier,
    PostCommitRowCountVerifier,
    SnapshotDiffEffectVerifier,
)
from .interfaces import DatabaseAdapter, InTransactionEffectVerifier, PostCommitVerifier, SemanticVerifier, SafetyVerifier
from .models import ExecutionResult, PipelineConfig, PipelineResult, SQLCandidate, UserIntent, VerificationStageResult
from .safety import RuleBasedSafetyVerifier

SQLRegenerator = Callable[[UserIntent, SQLCandidate, str, int], SQLCandidate]


@dataclass
class AttemptResult:
    stages: List[VerificationStageResult]
    execution: ExecutionResult | None
    failure_context: str
    accepted: bool
    committed: bool


class PlainDBPipeline:
    """End-to-end verification and execution pipeline for AI-generated SQL."""

    def __init__(
        self,
        adapter: DatabaseAdapter,
        semantic_verifier: SemanticVerifier | None = None,
        safety_verifier: SafetyVerifier | None = None,
        effect_verifier: InTransactionEffectVerifier | None = None,
        post_commit_verifier: PostCommitVerifier | None = None,
    ) -> None:
        self.adapter = adapter
        self.semantic_verifier = semantic_verifier or HeuristicSemanticVerifier()
        self.safety_verifier = safety_verifier or RuleBasedSafetyVerifier()
        self.effect_verifier = effect_verifier or SnapshotDiffEffectVerifier()
        self.post_commit_verifier = post_commit_verifier

    def run(
        self,
        intent: UserIntent,
        candidate: SQLCandidate,
        config: PipelineConfig | None = None,
        regenerate_sql: SQLRegenerator | None = None,
    ) -> PipelineResult:
        cfg = config or PipelineConfig()
        all_stages: List[VerificationStageResult] = []
        current_candidate = candidate
        last_execution: ExecutionResult | None = None
        max_attempts = max(1, cfg.max_retries + 1)

        for attempt in range(1, max_attempts + 1):
            result = self._run_attempt(intent, current_candidate, cfg, attempt)
            all_stages.extend(result.stages)
            last_execution = result.execution or last_execution

            if result.accepted:
                return PipelineResult(
                    accepted=True,
                    committed=result.committed,
                    stages=all_stages,
                    execution=last_execution,
                    attempts=attempt,
                )

            if not self._can_retry(regenerate_sql, attempt, max_attempts):
                return PipelineResult(
                    accepted=False,
                    committed=False,
                    stages=all_stages,
                    execution=last_execution,
                    attempts=attempt,
                )

            assert regenerate_sql is not None
            current_candidate = regenerate_sql(intent, current_candidate, result.failure_context, attempt)
            all_stages.append(self._build_reiterate_stage(attempt, result.failure_context, current_candidate))

        return PipelineResult(
            accepted=False,
            committed=False,
            stages=all_stages,
            execution=last_execution,
            attempts=max_attempts,
        )

    def _run_attempt(
        self,
        intent: UserIntent,
        candidate: SQLCandidate,
        cfg: PipelineConfig,
        attempt: int,
    ) -> AttemptResult:
        stages: List[VerificationStageResult] = []

        semantic_result = self.semantic_verifier.verify(intent, candidate)
        self._attach_attempt(semantic_result, attempt)
        stages.append(semantic_result)
        if not semantic_result.passed and cfg.fail_fast:
            return AttemptResult(stages, None, f"semantic: {semantic_result.reason}", False, False)

        safety_result = self.safety_verifier.verify(candidate)
        self._attach_attempt(safety_result, attempt)
        stages.append(safety_result)
        if not safety_result.passed:
            return AttemptResult(stages, None, f"safety: {safety_result.reason}", False, False)

        return self._execute_transaction(intent, candidate, cfg, attempt, stages)

    def _execute_transaction(
        self,
        intent: UserIntent,
        candidate: SQLCandidate,
        cfg: PipelineConfig,
        attempt: int,
        stages: List[VerificationStageResult],
    ) -> AttemptResult:
        with self.adapter.begin() as tx:
            before_snapshot = self.adapter.snapshot(tx, cfg.watched_tables)
            execution = self.adapter.execute(tx, candidate.sql, candidate.params)

            execution_stage = VerificationStageResult(
                stage="execution",
                passed=execution.success,
                reason="SQL executed successfully." if execution.success else "SQL execution failed.",
                details={"rowcount": execution.rowcount, "error": execution.error, "attempt": attempt},
            )
            stages.append(execution_stage)
            if not execution.success:
                tx.rollback()
                return AttemptResult(stages, execution, f"execution: {execution.error or execution_stage.reason}", False, False)

            effect_result = self.effect_verifier.verify(
                self.adapter,
                tx,
                intent,
                candidate,
                before_snapshot,
                execution,
            )
            self._attach_attempt(effect_result, attempt)
            stages.append(effect_result)
            if not effect_result.passed:
                tx.rollback()
                return AttemptResult(stages, execution, f"effect: {effect_result.reason}", False, False)

            if cfg.dry_run_only:
                tx.rollback()
                stages.append(
                    VerificationStageResult(
                        stage="commit",
                        passed=True,
                        reason="Dry-run mode enabled, transaction intentionally rolled back.",
                        details={"attempt": attempt},
                    )
                )
                return AttemptResult(stages, execution, "", True, False)

            tx.commit()

        post_verifier = self.post_commit_verifier or PostCommitRowCountVerifier(cfg.watched_tables)
        post_result = post_verifier.verify(self.adapter, intent, candidate)
        self._attach_attempt(post_result, attempt)
        stages.append(post_result)
        return AttemptResult(stages, execution, "", post_result.passed, post_result.passed)

    @staticmethod
    def _attach_attempt(stage: VerificationStageResult, attempt: int) -> None:
        stage.details["attempt"] = attempt

    @staticmethod
    def _can_retry(regenerate_sql: SQLRegenerator | None, attempt: int, max_attempts: int) -> bool:
        return regenerate_sql is not None and attempt < max_attempts

    @staticmethod
    def _build_reiterate_stage(attempt: int, error: str, next_candidate: SQLCandidate) -> VerificationStageResult:
        return VerificationStageResult(
            stage="reiterate",
            passed=True,
            reason="Generated a new SQL candidate from previous error context.",
            details={"attempt": attempt, "error": error, "next_sql": next_candidate.sql},
        )
