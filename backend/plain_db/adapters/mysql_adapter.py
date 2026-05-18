import os
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlparse

from ..schema import SchemaColumn, SchemaForeignKey
from .dbapi_adapter import DBAPIConnectionAdapter


class MySQLAdapter(DBAPIConnectionAdapter):
    def __init__(
        self,
        database: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        schema_name: Optional[str] = None,
        connection_string: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        pymysql = self._import_driver()
        connect_kwargs = self._build_connect_kwargs(
            database=database,
            username=username,
            password=password,
            host=host,
            port=port,
            schema_name=schema_name,
            connection_string=connection_string,
            options=options,
        )
        conn = pymysql.connect(**connect_kwargs)
        super().__init__(conn)
        self._database_name = connect_kwargs.get("database") or database

    @staticmethod
    def _import_driver():
        try:
            import pymysql
        except ImportError as exc:  # pragma: no cover - dependency specific
            raise ImportError("MySQL support requires the 'PyMySQL' package.") from exc
        return pymysql

    @staticmethod
    def _build_connect_kwargs(
        database: str,
        username: Optional[str],
        password: Optional[str],
        host: Optional[str],
        port: Optional[int],
        schema_name: Optional[str],
        connection_string: Optional[str],
        options: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        connect_kwargs: Dict[str, Any] = dict(options or {})
        if connection_string:
            parsed = urlparse(connection_string)
            if parsed.scheme and parsed.scheme.startswith("mysql"):
                connect_kwargs.setdefault("host", parsed.hostname)
                if parsed.port:
                    connect_kwargs.setdefault("port", parsed.port)
                if parsed.username:
                    connect_kwargs.setdefault("user", parsed.username)
                if parsed.password:
                    connect_kwargs.setdefault("password", parsed.password)
                if parsed.path and parsed.path != "/":
                    connect_kwargs.setdefault("database", parsed.path.lstrip("/"))
                for key, value in parse_qsl(parsed.query):
                    connect_kwargs.setdefault(key, value)
            else:
                connect_kwargs["database"] = connection_string
        else:
            connect_kwargs.setdefault("host", host)
            connect_kwargs.setdefault("port", port)
            connect_kwargs.setdefault("user", username)
            connect_kwargs.setdefault("password", password)
            connect_kwargs.setdefault("database", schema_name or database)

        connect_kwargs.pop("schema_name", None)
        connect_kwargs.pop("connection_string", None)
        connect_kwargs["host"] = MySQLAdapter._resolve_host_for_runtime(connect_kwargs.get("host"))
        connect_kwargs.setdefault("charset", "utf8mb4")
        return {key: value for key, value in connect_kwargs.items() if value is not None}

    @staticmethod
    def _resolve_host_for_runtime(host: Optional[str]) -> Optional[str]:
        if host is None:
            return None
        lowered = host.strip().lower()
        if MySQLAdapter._running_in_container() and lowered in {"localhost", "127.0.0.1", "::1"}:
            return "host.docker.internal"
        return host

    @staticmethod
    def _running_in_container() -> bool:
        return os.path.exists("/.dockerenv")

    def dialect_name(self) -> str:
        return "mysql"

    def list_tables(self) -> List[str]:
        rows = self.query(
            None,
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """,
        )
        return [self._row_value(row, "table_name") for row in rows]

    def describe_columns(self, table_name: str) -> List[SchemaColumn]:
        rows = self.query(
            None,
            """
            SELECT column_name, data_type, is_nullable, column_default, ordinal_position, column_key
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = %(table_name)s
            ORDER BY ordinal_position
            """,
            {"table_name": table_name},
        )
        return [
            SchemaColumn(
                name=self._row_value(row, "column_name"),
                data_type=self._row_value(row, "data_type"),
                not_null=self._row_value(row, "is_nullable") == "NO",
                default_value=self._row_value(row, "column_default"),
                primary_key_ordinal=1 if self._row_value(row, "column_key") == "PRI" else 0,
            )
            for row in rows
        ]

    def describe_foreign_keys(self, table_name: str) -> List[SchemaForeignKey]:
        rows = self.query(
            None,
            """
            SELECT
                kcu.column_name AS column_name,
                kcu.referenced_table_name AS referenced_table_name,
                kcu.referenced_column_name AS referenced_column_name,
                rc.update_rule AS update_rule,
                rc.delete_rule AS delete_rule
            FROM information_schema.key_column_usage kcu
            JOIN information_schema.referential_constraints rc
              ON kcu.constraint_name = rc.constraint_name
             AND kcu.constraint_schema = rc.constraint_schema
            WHERE kcu.table_schema = DATABASE()
              AND kcu.table_name = %(table_name)s
              AND kcu.referenced_table_name IS NOT NULL
            ORDER BY kcu.ordinal_position
            """,
            {"table_name": table_name},
        )
        return [
            SchemaForeignKey(
                column=self._row_value(row, "column_name"),
                referenced_table=self._row_value(row, "referenced_table_name"),
                referenced_column=self._row_value(row, "referenced_column_name"),
                on_update=self._row_value(row, "update_rule"),
                on_delete=self._row_value(row, "delete_rule"),
            )
            for row in rows
        ]

    def count_rows(self, table_name: str) -> Optional[int]:
        rows = self.query(None, f"SELECT COUNT(*) AS c FROM {self.quote_identifier(table_name)}")
        return int(self._row_value(rows[0], "c")) if rows else 0

    @staticmethod
    def quote_identifier(identifier: str) -> str:
        return "`" + identifier.replace("`", "``") + "`"

    @staticmethod
    def _row_value(row: Dict[str, Any], key: str):
        if key in row:
            return row[key]
        lowered = key.lower()
        for existing_key, value in row.items():
            if str(existing_key).lower() == lowered:
                return value
        raise KeyError(key)