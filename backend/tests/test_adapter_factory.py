"""Tests for dialect-based adapter selection."""

import pytest

from plain_db.adapters import factory
from plain_db.models import DatabaseTarget


def test_factory_selects_sqlite():
    adapter = factory.create_database_adapter(
        DatabaseTarget(dialect="sqlite", database=":memory:")
    )

    from plain_db.adapters.sqlite_adapter import SQLiteAdapter

    assert isinstance(adapter, SQLiteAdapter)
    adapter.close()


@pytest.mark.parametrize(
    "dialect,expected_type",
    [
        ("postgresql", "postgres"),
        ("postgres", "postgres"),
        ("mysql", "mysql"),
        ("mariadb", "mysql"),
    ],
)
def test_factory_routes_supported_dialects(monkeypatch, dialect, expected_type):
    class PostgresAdapterFake:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class MySQLAdapterFake:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class SQLiteAdapterFake:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    monkeypatch.setattr(factory, "PostgreSQLAdapter", PostgresAdapterFake)
    monkeypatch.setattr(factory, "MySQLAdapter", MySQLAdapterFake)
    monkeypatch.setattr(factory, "SQLiteAdapter", SQLiteAdapterFake)

    adapter = factory.create_database_adapter(
        DatabaseTarget(
            dialect=dialect,
            database="example_db",
            username="user",
            password="pass",
            host="localhost",
            port=5432,
            schema_name="public",
            connection_string=None,
            options={"connect_timeout": 10},
        )
    )

    if expected_type == "postgres":
        assert isinstance(adapter, PostgresAdapterFake)
        assert adapter.kwargs["database"] == "example_db"
    else:
        assert isinstance(adapter, MySQLAdapterFake)
        assert adapter.kwargs["database"] == "example_db"


def test_factory_rejects_unknown_dialect():
    with pytest.raises(ValueError):
        factory.create_database_adapter(DatabaseTarget(dialect="oracle", database="db"))