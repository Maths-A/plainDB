"""Optional smoke tests against real PostgreSQL/MySQL instances.

These tests are skipped unless explicit DSN environment variables are provided.
"""

import os
import uuid
from urllib.parse import urlparse, urlunparse

import pytest

from plain_db.adapters import create_database_adapter
from plain_db.models import DatabaseTarget


def _env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"Set {name} to run this smoke test")
    return value


def test_postgresql_adapter_smoke():
    dsn = _env_or_skip("PLAINDB_TEST_POSTGRES_DSN")
    pytest.importorskip("psycopg2")

    adapter = create_database_adapter(
        DatabaseTarget(
            dialect="postgresql",
            database="postgres",
            connection_string=dsn,
        )
    )
    try:
        rows = adapter.query(None, "SELECT 1 AS one")
        schema = adapter.describe_schema()
        assert int(rows[0]["one"]) == 1
        assert schema.dialect == "postgresql"
    finally:
        adapter.close()


def test_mysql_adapter_smoke():
    dsn = _env_or_skip("PLAINDB_TEST_MYSQL_DSN")
    pytest.importorskip("pymysql")

    adapter = create_database_adapter(
        DatabaseTarget(
            dialect="mysql",
            database="mysql",
            connection_string=dsn,
        )
    )
    try:
        rows = adapter.query(None, "SELECT 1 AS one")
        schema = adapter.describe_schema()
        assert int(rows[0]["one"]) == 1
        assert schema.dialect == "mysql"
    finally:
        adapter.close()


def _dsn_with_password(dsn: str, new_password: str) -> str:
    parsed = urlparse(dsn)
    username = parsed.username or ""
    host = parsed.hostname or "localhost"
    auth = f"{username}:{new_password}@{host}"
    if parsed.port:
        auth += f":{parsed.port}"
    return urlunparse((parsed.scheme, auth, parsed.path, parsed.params, parsed.query, parsed.fragment))


def test_postgresql_adapter_auth_failure_with_wrong_password():
    dsn = _env_or_skip("PLAINDB_TEST_POSTGRES_DSN")
    pytest.importorskip("psycopg2")
    bad_dsn = _dsn_with_password(dsn, "definitely-wrong-password")

    with pytest.raises(Exception):
        create_database_adapter(DatabaseTarget(dialect="postgresql", database="postgres", connection_string=bad_dsn))


def test_mysql_adapter_auth_failure_with_wrong_password():
    dsn = _env_or_skip("PLAINDB_TEST_MYSQL_DSN")
    pytest.importorskip("pymysql")
    bad_dsn = _dsn_with_password(dsn, "definitely-wrong-password")

    with pytest.raises(Exception):
        create_database_adapter(DatabaseTarget(dialect="mysql", database="mysql", connection_string=bad_dsn))


def test_postgresql_schema_edge_cases_reserved_composite_fk():
    dsn = _env_or_skip("PLAINDB_TEST_POSTGRES_DSN")
    pytest.importorskip("psycopg2")

    suffix = uuid.uuid4().hex[:8]
    parent = f"parent_{suffix}"
    child = f"child_{suffix}"
    reserved = f"order_{suffix}"

    adapter = create_database_adapter(DatabaseTarget(dialect="postgresql", database="postgres", connection_string=dsn))
    try:
        adapter.query(None, f'CREATE TABLE "{parent}" (id INT PRIMARY KEY)')
        adapter.query(
            None,
            f'CREATE TABLE "{child}" (a INT NOT NULL, b INT NOT NULL, parent_id INT REFERENCES "{parent}"(id) ON DELETE CASCADE, PRIMARY KEY (a, b))',
        )
        adapter.query(None, f'CREATE TABLE "{reserved}" (id INT PRIMARY KEY, note TEXT)')

        schema = adapter.describe_schema()
        by_name = {table.name: table for table in schema.tables}

        assert parent in by_name
        assert child in by_name
        assert reserved in by_name
        assert len([column for column in by_name[child].columns if column.primary_key_ordinal > 0]) == 2
        assert any(fk.referenced_table == parent for fk in by_name[child].foreign_keys)
    finally:
        adapter.query(None, f'DROP TABLE IF EXISTS "{child}"')
        adapter.query(None, f'DROP TABLE IF EXISTS "{reserved}"')
        adapter.query(None, f'DROP TABLE IF EXISTS "{parent}"')
        adapter.close()


def test_mysql_schema_edge_cases_reserved_composite_fk():
    dsn = _env_or_skip("PLAINDB_TEST_MYSQL_DSN")
    pytest.importorskip("pymysql")

    suffix = uuid.uuid4().hex[:8]
    parent = f"parent_{suffix}"
    child = f"child_{suffix}"
    reserved = f"order_{suffix}"

    adapter = create_database_adapter(DatabaseTarget(dialect="mysql", database="mysql", connection_string=dsn))
    try:
        adapter.query(None, f'CREATE TABLE `{parent}` (id INT PRIMARY KEY) ENGINE=InnoDB')
        adapter.query(
            None,
            f'CREATE TABLE `{child}` (a INT NOT NULL, b INT NOT NULL, parent_id INT, PRIMARY KEY (a, b), CONSTRAINT `fk_{suffix}` FOREIGN KEY (parent_id) REFERENCES `{parent}`(id) ON DELETE CASCADE ON UPDATE CASCADE) ENGINE=InnoDB',
        )
        adapter.query(None, f'CREATE TABLE `{reserved}` (id INT PRIMARY KEY, note TEXT) ENGINE=InnoDB')

        schema = adapter.describe_schema()
        by_name = {table.name: table for table in schema.tables}

        assert parent in by_name
        assert child in by_name
        assert reserved in by_name
        assert len([column for column in by_name[child].columns if column.primary_key_ordinal > 0]) >= 2
        assert any(fk.referenced_table == parent for fk in by_name[child].foreign_keys)
    finally:
        adapter.query(None, f'DROP TABLE IF EXISTS `{child}`')
        adapter.query(None, f'DROP TABLE IF EXISTS `{reserved}`')
        adapter.query(None, f'DROP TABLE IF EXISTS `{parent}`')
        adapter.close()