import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional

from ..interfaces import DatabaseAdapter, TransactionHandle
from ..models import ExecutionResult

INVALID_TRANSACTION_HANDLE = "Invalid transaction handle"


@dataclass
class SQLiteTransaction(TransactionHandle):
    conn: sqlite3.Connection
    closed: bool = False

    def commit(self) -> None:
        if not self.closed:
            self.conn.commit()
            self.closed = True

    def rollback(self) -> None:
        if not self.closed:
            self.conn.rollback()
            self.closed = True


class SQLiteAdapter(DatabaseAdapter):
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row

    @contextmanager
    def begin(self) -> Generator[TransactionHandle, None, None]:
        tx = SQLiteTransaction(self._conn)
        self._conn.execute("BEGIN")
        try:
            yield tx
        finally:
            if not tx.closed:
                tx.rollback()

    def execute(self, tx: TransactionHandle, sql: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        if not isinstance(tx, SQLiteTransaction):
            return ExecutionResult(success=False, rowcount=0, error=INVALID_TRANSACTION_HANDLE)

        try:
            cursor = tx.conn.execute(sql, params or {})
            rowcount = cursor.rowcount if cursor.rowcount is not None else 0
            return ExecutionResult(success=True, rowcount=rowcount)
        except sqlite3.Error as exc:
            return ExecutionResult(success=False, rowcount=0, error=str(exc))

    def query(self, tx: Optional[TransactionHandle], sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        conn = self._conn
        if tx is not None:
            if not isinstance(tx, SQLiteTransaction):
                raise TypeError(INVALID_TRANSACTION_HANDLE)
            conn = tx.conn

        cursor = conn.execute(sql, params or {})
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def snapshot(self, tx: TransactionHandle, watched_tables: List[str]) -> Dict[str, Any]:
        if not isinstance(tx, SQLiteTransaction):
            raise TypeError(INVALID_TRANSACTION_HANDLE)

        snapshot: Dict[str, Any] = {}
        for table in watched_tables:
            rows = self.query(tx, f"SELECT COUNT(*) AS c FROM {table}")
            snapshot[table] = rows[0]["c"]
        return snapshot

    def close(self) -> None:
        self._conn.close()
