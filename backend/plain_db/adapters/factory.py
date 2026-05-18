from ..models import DatabaseTarget
from .mysql_adapter import MySQLAdapter
from .postgresql_adapter import PostgreSQLAdapter
from .sqlite_adapter import SQLiteAdapter


def _normalize_dialect(dialect: str) -> str:
    normalized = (dialect or "").strip().lower()
    if "+" in normalized:
        normalized = normalized.split("+", 1)[0]
    return normalized


def create_database_adapter(target: DatabaseTarget):
    dialect = _normalize_dialect(target.dialect)
    if dialect in {"sqlite"}:
        return SQLiteAdapter(target.database)
    if dialect in {"postgres", "postgresql", "pg"}:
        return PostgreSQLAdapter(
            database=target.database,
            username=target.username,
            password=target.password,
            host=target.host,
            port=target.port,
            schema_name=target.schema_name,
            connection_string=target.connection_string,
            options=target.options,
        )
    if dialect in {"mysql", "mariadb"}:
        return MySQLAdapter(
            database=target.database,
            username=target.username,
            password=target.password,
            host=target.host,
            port=target.port,
            schema_name=target.schema_name,
            connection_string=target.connection_string,
            options=target.options,
        )

    raise ValueError(f"Unsupported database dialect: {target.dialect}")