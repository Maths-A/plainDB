import sqlite3
from typing import List, Optional

from ..schema import SchemaColumn, SchemaForeignKey
from .dbapi_adapter import DBAPIConnectionAdapter


class SQLiteAdapter(DBAPIConnectionAdapter):
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        super().__init__(conn)

    def dialect_name(self) -> str:
        return "sqlite"

    def list_tables(self) -> List[str]:
        table_rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [table_row["name"] for table_row in table_rows]

    def describe_columns(self, table_name: str) -> List[SchemaColumn]:
        table_info = self._conn.execute(f"PRAGMA table_info({self.quote_identifier(table_name)})").fetchall()
        return [
            SchemaColumn(
                name=row["name"],
                data_type=row["type"] or "TEXT",
                not_null=bool(row["notnull"]),
                default_value=row["dflt_value"],
                primary_key_ordinal=int(row["pk"] or 0),
            )
            for row in table_info
        ]

    def describe_foreign_keys(self, table_name: str) -> List[SchemaForeignKey]:
        foreign_key_rows = self._conn.execute(
            f"PRAGMA foreign_key_list({self.quote_identifier(table_name)})"
        ).fetchall()
        return [
            SchemaForeignKey(
                column=row["from"],
                referenced_table=row["table"],
                referenced_column=row["to"],
                on_update=row["on_update"],
                on_delete=row["on_delete"],
            )
            for row in foreign_key_rows
        ]

    def count_rows(self, table_name: str) -> Optional[int]:
        try:
            row_count_result = self._conn.execute(
                f"SELECT COUNT(*) AS c FROM {self.quote_identifier(table_name)}"
            ).fetchone()
            if row_count_result is not None:
                return int(row_count_result["c"])
        except sqlite3.Error:
            return None
        return None

    @staticmethod
    def quote_identifier(identifier: str) -> str:
        safe_identifier = identifier.replace('"', '""')
        return f'"{safe_identifier}"'