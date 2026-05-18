from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SchemaColumn:
    name: str
    data_type: str
    not_null: bool = False
    default_value: Optional[str] = None
    primary_key_ordinal: int = 0


@dataclass
class SchemaForeignKey:
    column: str
    referenced_table: str
    referenced_column: str
    on_update: Optional[str] = None
    on_delete: Optional[str] = None


@dataclass
class SchemaTable:
    name: str
    columns: List[SchemaColumn] = field(default_factory=list)
    foreign_keys: List[SchemaForeignKey] = field(default_factory=list)
    row_count: Optional[int] = None


@dataclass
class DatabaseSchema:
    dialect: str
    tables: List[SchemaTable] = field(default_factory=list)

    def table_names(self) -> List[str]:
        return [table.name for table in self.tables]

    def to_prompt_payload(self) -> Dict[str, Any]:
        return {
            "dialect": self.dialect,
            "tables": [
                {
                    "name": table.name,
                    "row_count": table.row_count,
                    "columns": [
                        {
                            "name": column.name,
                            "data_type": column.data_type,
                            "not_null": column.not_null,
                            "default_value": column.default_value,
                            "primary_key_ordinal": column.primary_key_ordinal,
                        }
                        for column in table.columns
                    ],
                    "foreign_keys": [
                        {
                            "column": fk.column,
                            "referenced_table": fk.referenced_table,
                            "referenced_column": fk.referenced_column,
                            "on_update": fk.on_update,
                            "on_delete": fk.on_delete,
                        }
                        for fk in table.foreign_keys
                    ],
                }
                for table in self.tables
            ],
        }