from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional, Sequence

from ..interfaces import DatabaseAdapter, TransactionHandle
from ..models import ExecutionResult
from ..schema import DatabaseSchema, SchemaColumn, SchemaForeignKey, SchemaTable

INVALID_TRANSACTION_HANDLE = "Invalid transaction handle"


@dataclass
class DBAPITransaction(TransactionHandle):
    conn: Any
    closed: bool = False

    def commit(self) -> None:
        if not self.closed:
            self.conn.commit()
            self.closed = True

    def rollback(self) -> None:
        if not self.closed:
            self.conn.rollback()
            self.closed = True


class DBAPIConnectionAdapter(DatabaseAdapter, ABC):
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    @contextmanager
    def begin(self) -> Generator[TransactionHandle, None, None]:
        tx = DBAPITransaction(self._conn)
        self._begin_transaction(self._conn)
        try:
            yield tx
        finally:
            if not tx.closed:
                tx.rollback()

    def execute(self, tx: TransactionHandle, sql: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        conn = self._transaction_connection(tx)
        if conn is None:
            return ExecutionResult(success=False, rowcount=0, error=INVALID_TRANSACTION_HANDLE)

        try:
            cursor = self._execute_sql(conn, sql, params)
            rowcount = cursor.rowcount if cursor.rowcount is not None else 0
            rows = self._rows_from_cursor(cursor)
            return ExecutionResult(success=True, rowcount=rowcount, lastrowid=getattr(cursor, "lastrowid", None), rows=rows)
        except Exception as exc:  # pragma: no cover - database driver specific failures
            return ExecutionResult(success=False, rowcount=0, error=str(exc))

    def query(self, tx: Optional[TransactionHandle], sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        conn = self._transaction_connection(tx) if tx is not None else self._conn
        if tx is not None and conn is None:
            raise TypeError(INVALID_TRANSACTION_HANDLE)

        cursor = self._execute_sql(conn, sql, params)
        rows = self._rows_from_cursor(cursor)
        if tx is None and cursor.description is None:
            conn.commit()
        return rows

    def snapshot(self, tx: TransactionHandle, watched_tables: List[str]) -> Dict[str, Any]:
        if self._transaction_connection(tx) is None:
            raise TypeError(INVALID_TRANSACTION_HANDLE)

        snapshot: Dict[str, Any] = {}
        for table in watched_tables:
            rows = self.query(tx, f"SELECT COUNT(*) AS c FROM {self.quote_identifier(table)}")
            snapshot[table] = rows[0]["c"]
        return snapshot

    def describe_schema(self) -> DatabaseSchema:
        tables = []
        for table_name in self.list_tables():
            columns = self.describe_columns(table_name)
            foreign_keys = self.describe_foreign_keys(table_name)
            tables.append(
                SchemaTable(
                    name=table_name,
                    columns=columns,
                    foreign_keys=foreign_keys,
                    # Avoid expensive COUNT(*) scans during request-time introspection.
                    row_count=None,
                )
            )
        return DatabaseSchema(dialect=self.dialect_name(), tables=tables)

    def close(self) -> None:
        self._conn.close()

    def _transaction_connection(self, tx: Optional[TransactionHandle]) -> Optional[Any]:
        if tx is None:
            return self._conn
        if not isinstance(tx, DBAPITransaction):
            return None
        return tx.conn

    @staticmethod
    def _rows_from_cursor(cursor: Any) -> List[Dict[str, Any]]:
        if cursor.description is None:
            return []

        rows = cursor.fetchall()
        column_names = [column[0] for column in cursor.description]
        result: List[Dict[str, Any]] = []
        for row in rows:
            if isinstance(row, dict):
                result.append(dict(row))
            elif hasattr(row, "keys"):
                result.append(dict(row))
            else:
                result.append({name: value for name, value in zip(column_names, row)})
        return result

    @staticmethod
    def _execute_sql(conn: Any, sql: str, params: Optional[Dict[str, Any]] = None) -> Any:
        cursor = conn.cursor()
        cursor.execute(sql, params or {})
        return cursor

    @staticmethod
    def _begin_transaction(conn: Any) -> None:
        cursor = conn.cursor()
        cursor.execute("BEGIN")

    @abstractmethod
    def dialect_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def list_tables(self) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def describe_columns(self, table_name: str) -> List[SchemaColumn]:
        raise NotImplementedError

    @abstractmethod
    def describe_foreign_keys(self, table_name: str) -> List[SchemaForeignKey]:
        raise NotImplementedError

    @abstractmethod
    def count_rows(self, table_name: str) -> Optional[int]:
        raise NotImplementedError

    @abstractmethod
    def quote_identifier(self, identifier: str) -> str:
        raise NotImplementedError