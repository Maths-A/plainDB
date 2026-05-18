import os
from typing import List, Optional

from ..schema import SchemaColumn, SchemaForeignKey
from .dbapi_adapter import DBAPIConnectionAdapter


class PostgreSQLAdapter(DBAPIConnectionAdapter):
    def __init__(
        self,
        database: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        schema_name: Optional[str] = None,
        connection_string: Optional[str] = None,
        options: Optional[dict] = None,
    ) -> None:
        psycopg2 = self._import_driver()
        resolved_host = self._resolve_host_for_runtime(host)
        if connection_string:
            connect_kwargs = dict(options or {})
            if username:
                connect_kwargs["user"] = username
            if password:
                connect_kwargs["password"] = password
            if resolved_host:
                connect_kwargs["host"] = resolved_host
            if port:
                connect_kwargs["port"] = port
            if database:
                connect_kwargs["dbname"] = database
            conn = psycopg2.connect(self._normalize_connection_string(connection_string), **connect_kwargs)
        else:
            conn = psycopg2.connect(
                dbname=database,
                user=username,
                password=password,
                host=resolved_host,
                port=port,
                **(options or {}),
            )

        super().__init__(conn)
        self._schema_name = schema_name or None
        if self._schema_name:
            with conn.cursor() as cursor:
                cursor.execute(f"SET search_path TO {self.quote_identifier(self._schema_name)}")

    @staticmethod
    def _import_driver():
        try:
            import psycopg2
        except ImportError as exc:  # pragma: no cover - dependency specific
            raise ImportError("PostgreSQL support requires the 'psycopg2-binary' package.") from exc
        return psycopg2

    @staticmethod
    def _normalize_connection_string(connection_string: str) -> str:
        normalized = (connection_string or "").strip()
        # DBeaver often provides JDBC-style URLs; psycopg2 expects libpq DSN or URI.
        if normalized.startswith("jdbc:postgresql://"):
            return "postgresql://" + normalized[len("jdbc:postgresql://") :]
        if normalized.startswith("jdbc:postgres://"):
            return "postgres://" + normalized[len("jdbc:postgres://") :]
        return normalized

    @staticmethod
    def _resolve_host_for_runtime(host: Optional[str]) -> Optional[str]:
        if host is None:
            return None
        lowered = host.strip().lower()
        if PostgreSQLAdapter._running_in_container() and lowered in {"localhost", "127.0.0.1", "::1"}:
            return "host.docker.internal"
        return host

    @staticmethod
    def _running_in_container() -> bool:
        return os.path.exists("/.dockerenv")

    def dialect_name(self) -> str:
        return "postgresql"

    def list_tables(self) -> List[str]:
        rows = self.query(
            None,
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
              AND table_schema = current_schema()
            ORDER BY table_name
            """,
        )
        return [row["table_name"] for row in rows]

    def describe_columns(self, table_name: str) -> List[SchemaColumn]:
        rows = self.query(
            None,
            """
            SELECT column_name, data_type, is_nullable, column_default, ordinal_position
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = %(table_name)s
            ORDER BY ordinal_position
            """,
            {"table_name": table_name},
        )
        primary_key_positions = self._primary_key_positions(table_name)
        return [
            SchemaColumn(
                name=row["column_name"],
                data_type=row["data_type"],
                not_null=row["is_nullable"] == "NO",
                default_value=row["column_default"],
                primary_key_ordinal=primary_key_positions.get(row["column_name"], 0),
            )
            for row in rows
        ]

    def describe_foreign_keys(self, table_name: str) -> List[SchemaForeignKey]:
        rows = self.query(
            None,
            """
            SELECT
                kcu.column_name AS column_name,
                ccu.table_name AS referenced_table,
                ccu.column_name AS referenced_column,
                rc.update_rule AS on_update,
                rc.delete_rule AS on_delete
            FROM information_schema.table_constraints tc
            JOIN information_schema.referential_constraints rc
              ON tc.constraint_name = rc.constraint_name
             AND tc.constraint_schema = rc.constraint_schema
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.constraint_schema = kcu.constraint_schema
            JOIN information_schema.constraint_column_usage ccu
              ON rc.unique_constraint_name = ccu.constraint_name
             AND rc.unique_constraint_schema = ccu.constraint_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = current_schema()
              AND tc.table_name = %(table_name)s
            ORDER BY kcu.ordinal_position
            """,
            {"table_name": table_name},
        )
        return [
            SchemaForeignKey(
                column=row["column_name"],
                referenced_table=row["referenced_table"],
                referenced_column=row["referenced_column"],
                on_update=row["on_update"],
                on_delete=row["on_delete"],
            )
            for row in rows
        ]

    def count_rows(self, table_name: str) -> Optional[int]:
        rows = self.query(None, f"SELECT COUNT(*) AS c FROM {self.quote_identifier(table_name)}")
        return int(rows[0]["c"]) if rows else 0

    @staticmethod
    def quote_identifier(identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    def _primary_key_positions(self, table_name: str) -> dict:
        rows = self.query(
            None,
            """
            SELECT kcu.column_name, kcu.ordinal_position
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.constraint_schema = kcu.constraint_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = current_schema()
              AND tc.table_name = %(table_name)s
            ORDER BY kcu.ordinal_position
            """,
            {"table_name": table_name},
        )
        return {row["column_name"]: int(row["ordinal_position"]) for row in rows}