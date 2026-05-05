import re
from typing import Any, Dict

from .interfaces import InTransactionEffectVerifier, PostCommitVerifier, SemanticVerifier
from .models import ExecutionResult, SQLCandidate, UserIntent, VerificationStageResult


class HeuristicSemanticVerifier(SemanticVerifier):
    """Simple semantic verifier that can be replaced by an LLM-based checker."""

    ACTION_KEYWORDS = {
        "SELECT": ["read", "show", "list", "get", "find"],
        "INSERT": ["insert", "add", "create"],
        "UPDATE": ["update", "change", "modify", "set"],
        "DELETE": ["delete", "remove"],
    }

    def verify(self, intent: UserIntent, candidate: SQLCandidate) -> VerificationStageResult:
        sql_upper = candidate.sql.upper()
        action = self._extract_sql_action(sql_upper)
        intent_lower = intent.text.lower()

        expected_action = intent.expected_action.upper() if intent.expected_action else None
        if expected_action and expected_action != action:
            return VerificationStageResult(
                stage="semantic",
                passed=False,
                reason="Intent expected action differs from SQL action.",
                details={"expected": expected_action, "actual": action},
            )

        if not expected_action and not self._action_matches_intent(action, intent_lower):
            return VerificationStageResult(
                stage="semantic",
                passed=False,
                reason="Intent wording does not match SQL action.",
                details={"action": action},
            )

        missing_tables = [t for t in intent.expected_tables if t.lower() not in sql_upper.lower()]
        if missing_tables:
            return VerificationStageResult(
                stage="semantic",
                passed=False,
                reason="Expected table(s) not found in SQL.",
                details={"missing_tables": missing_tables},
            )

        return VerificationStageResult(
            stage="semantic",
            passed=True,
            reason="Intent and SQL are semantically aligned (heuristic check).",
            details={"action": action},
        )

    @staticmethod
    def _extract_sql_action(sql_upper: str) -> str:
        first = sql_upper.strip().split(" ", 1)
        return first[0] if first else "UNKNOWN"

    def _action_matches_intent(self, action: str, intent_lower: str) -> bool:
        expected_words = self.ACTION_KEYWORDS.get(action, [])
        if not expected_words:
            return False
        return any(word in intent_lower for word in expected_words)


class SnapshotDiffEffectVerifier(InTransactionEffectVerifier):
    """Checks that watched table row counts change in expected direction."""

    def verify(
        self,
        adapter,
        tx,
        intent: UserIntent,
        candidate: SQLCandidate,
        before_snapshot: Dict[str, Any],
        execution_result: ExecutionResult,
    ) -> VerificationStageResult:
        _ = intent
        after_snapshot = adapter.snapshot(tx, list(before_snapshot.keys()))
        action = candidate.sql.strip().split(" ", 1)[0].upper()

        mismatches = []
        for table, before_count in before_snapshot.items():
            after_count = after_snapshot.get(table)
            if after_count is None:
                mismatches.append(f"missing after-snapshot for table {table}")
                continue

            if action == "INSERT" and after_count < before_count:
                mismatches.append(f"{table}: expected rows to stay or increase")
            elif action == "DELETE" and after_count > before_count:
                mismatches.append(f"{table}: expected rows to stay or decrease")

        if mismatches:
            return VerificationStageResult(
                stage="effect",
                passed=False,
                reason="In-transaction effect validation failed.",
                details={"mismatches": mismatches, "before": before_snapshot, "after": after_snapshot},
            )

        return VerificationStageResult(
            stage="effect",
            passed=True,
            reason="In-transaction effects are consistent with intent.",
            details={"before": before_snapshot, "after": after_snapshot, "rowcount": execution_result.rowcount},
        )


class PostCommitRowCountVerifier(PostCommitVerifier):
    """Confirms watched table state exists and is queryable after commit."""

    def __init__(self, watched_tables):
        self.watched_tables = watched_tables

    def verify(self, adapter, intent: UserIntent, candidate: SQLCandidate) -> VerificationStageResult:
        _ = intent
        _ = candidate
        counts = {}
        for table in self.watched_tables:
            rows = adapter.query(None, f"SELECT COUNT(*) AS c FROM {table}")
            counts[table] = rows[0]["c"]

        return VerificationStageResult(
            stage="post_commit",
            passed=True,
            reason="Post-commit checks succeeded.",
            details={"row_counts": counts},
        )


class StubAISemanticVerifier(SemanticVerifier):
    """Adapter point for plugging in a real LLM verifier service."""

    def __init__(self, client_name: str = "external-llm") -> None:
        self.client_name = client_name

    def verify(self, intent: UserIntent, candidate: SQLCandidate) -> VerificationStageResult:
        _ = intent
        # Replace this stub with a real API call that returns confidence and verdict.
        match = bool(re.search(r"\b" + re.escape(candidate.sql.split(" ", 1)[0]) + r"\b", candidate.sql, re.I))
        return VerificationStageResult(
            stage="semantic",
            passed=match,
            reason="Stub AI verifier approved SQL." if match else "Stub AI verifier rejected SQL.",
            details={"client": self.client_name},
        )
