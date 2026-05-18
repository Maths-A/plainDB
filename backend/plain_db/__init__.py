"""PlainDB package - SQL generation and verification pipeline."""

from .architecture import PlainDBArchitecturePipeline
from .adapters import MySQLAdapter, PostgreSQLAdapter, SQLiteAdapter, create_database_adapter
from .models import BackendRequest, BackendRunResult, DatabaseTarget, PipelineConfig, PipelineResult, SQLCandidate, UserIntent
from .pipeline import PlainDBPipeline

__all__ = [
    "BackendRequest",
    "BackendRunResult",
    "DatabaseTarget",
    "MySQLAdapter",
    "PipelineConfig",
    "PipelineResult",
    "PostgreSQLAdapter",
    "SQLCandidate",
    "SQLiteAdapter",
    "UserIntent",
    "create_database_adapter",
    "PlainDBArchitecturePipeline",
    "PlainDBPipeline",
]
