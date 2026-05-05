import re
from typing import List

from .interfaces import SafetyVerifier
from .models import SQLCandidate, VerificationStageResult


FORBIDDEN_PATTERNS = [
    r"\bDROP\s+DATABASE\b",
    r"\bALTER\s+SYSTEM\b",
    r"\bTRUNCATE\b",
    r"\bGRANT\b",
    r"\bREVOKE\b",
    r"\bATTACH\s+DATABASE\b",
    r"\bDETACH\s+DATABASE\b",
]

ALLOWED_ROOT_COMMANDS = {"SELECT", "INSERT", "UPDATE", "DELETE"}


class RuleBasedSafetyVerifier(SafetyVerifier):
    """Baseline SQL safety policy before execution."""

    def __init__(self, allow_ddl: bool = False) -> None:
        self.allow_ddl = allow_ddl

    def verify(self, candidate: SQLCandidate) -> VerificationStageResult:
        sql = candidate.sql.strip()
        normalized = re.sub(r"\s+", " ", sql).upper()

        if not normalized:
            return VerificationStageResult(
                stage="safety",
                passed=False,
                reason="Empty SQL statement.",
            )

        for pattern in FORBIDDEN_PATTERNS:
            if re.search(pattern, normalized):
                return VerificationStageResult(
                    stage="safety",
                    passed=False,
                    reason="SQL contains forbidden operation.",
                    details={"pattern": pattern},
                )

        command = normalized.split(" ", 1)[0]
        if not self.allow_ddl and command not in ALLOWED_ROOT_COMMANDS:
            return VerificationStageResult(
                stage="safety",
                passed=False,
                reason="Only DML commands are allowed by policy.",
                details={"command": command, "allowed": sorted(ALLOWED_ROOT_COMMANDS)},
            )

        if ";" in normalized.strip(";"):
            return VerificationStageResult(
                stage="safety",
                passed=False,
                reason="Multiple statements are not allowed.",
            )

        return VerificationStageResult(
            stage="safety",
            passed=True,
            reason="SQL passed rule-based safety checks.",
            details={"command": command},
        )


class CompositeSafetyVerifier(SafetyVerifier):
    """Runs multiple safety verifiers and aggregates decisions."""

    def __init__(self, verifiers: List[SafetyVerifier]) -> None:
        self.verifiers = verifiers

    def verify(self, candidate: SQLCandidate) -> VerificationStageResult:
        failed = []
        checks = []
        for verifier in self.verifiers:
            result = verifier.verify(candidate)
            checks.append({"stage": result.stage, "passed": result.passed, "reason": result.reason})
            if not result.passed:
                failed.append(result.reason)

        if failed:
            return VerificationStageResult(
                stage="safety",
                passed=False,
                reason="; ".join(failed),
                details={"checks": checks},
            )

        return VerificationStageResult(
            stage="safety",
            passed=True,
            reason="All safety verifiers passed.",
            details={"checks": checks},
        )
