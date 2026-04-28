from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from typing import Any, Dict, List, Optional

from .models import ExecutionResult, SQLCandidate, UserIntent, VerificationStageResult


class TransactionHandle(ABC):
    @abstractmethod
    def commit(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def rollback(self) -> None:
        raise NotImplementedError


class DatabaseAdapter(ABC):
    """Database-agnostic adapter API."""

    @abstractmethod
    def begin(self) -> AbstractContextManager[TransactionHandle]:
        raise NotImplementedError

    @abstractmethod
    def execute(self, tx: TransactionHandle, sql: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def query(self, tx: Optional[TransactionHandle], sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def snapshot(self, tx: TransactionHandle, watched_tables: List[str]) -> Dict[str, Any]:
        raise NotImplementedError


class SemanticVerifier(ABC):
    """Checks whether user intent and generated SQL are semantically aligned."""

    @abstractmethod
    def verify(self, intent: UserIntent, candidate: SQLCandidate) -> VerificationStageResult:
        raise NotImplementedError


class SafetyVerifier(ABC):
    """Checks SQL against safety policy and harmful patterns."""

    @abstractmethod
    def verify(self, candidate: SQLCandidate) -> VerificationStageResult:
        raise NotImplementedError


class InTransactionEffectVerifier(ABC):
    """Checks whether transaction effects match user intent before commit."""

    @abstractmethod
    def verify(
        self,
        adapter: DatabaseAdapter,
        tx: TransactionHandle,
        intent: UserIntent,
        candidate: SQLCandidate,
        before_snapshot: Dict[str, Any],
        execution_result: ExecutionResult,
    ) -> VerificationStageResult:
        raise NotImplementedError


class PostCommitVerifier(ABC):
    """Verifies final persisted state after successful commit."""

    @abstractmethod
    def verify(self, adapter: DatabaseAdapter, intent: UserIntent, candidate: SQLCandidate) -> VerificationStageResult:
        raise NotImplementedError
