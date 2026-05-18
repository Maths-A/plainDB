"""Integration-style API tests using the real architecture pipeline and sqlite adapter."""

import sqlite3

from fastapi.testclient import TestClient

from api.main import app
from plain_db.architecture import PlainDBArchitecturePipeline
from plain_db.llm import AIJudgement
from plain_db.rollback import RollbackService


class FakeIntegrationAIClient:
    def __init__(self, *args, **kwargs):
        pass

    def generate_sql(self, explanation, schema, attempt=1, previous_sql=None, previous_error=None):
        return "UPDATE users SET name = 'Bob' WHERE id = 1"

    def verify_sql(self, explanation, sql, schema):
        return AIJudgement(passed=True, reason="aligned")

    def generate_verification_queries(self, explanation, schema, sql):
        return ["SELECT name FROM users WHERE id = 1"]

    def classify_execution_error(self, explanation, sql, error_message, schema):
        return AIJudgement(passed=True, reason="human", retry=False, details={"kind": "human"})

    def verify_results(self, explanation, sql, verification_queries, verification_results, schema):
        rows = verification_results[0]["rows"] if verification_results else []
        if rows and rows[0].get("name") == "Bob":
            return AIJudgement(passed=True, reason="state updated")
        return AIJudgement(passed=False, reason="update missing", retry=False, details={"kind": "verification_failed"})


def _seed_sqlite(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO users (id, name) VALUES (1, 'Alice')")
    conn.commit()
    conn.close()


def test_run_endpoint_with_real_pipeline_and_rollback(tmp_path):
    db_file = tmp_path / "integration.sqlite"
    _seed_sqlite(str(db_file))

    pipeline = PlainDBArchitecturePipeline(ai_client_factory=FakeIntegrationAIClient)

    with TestClient(app) as client:
        client.app.state.pipeline = pipeline
        client.app.state.rollback_service = RollbackService()

        run_response = client.post(
            "/run",
            json={
                "intent_text": "rename user 1 to Bob",
                "api_key": "test-key",
                "provider": "gemini",
                "database_target": {"dialect": "sqlite", "database": str(db_file)},
                "dry_run": False,
                "max_retries": 0,
            },
        )

        assert run_response.status_code == 200
        run_body = run_response.json()
        assert run_body["accepted"] is True
        assert run_body["committed"] is True
        assert run_body["rollback_id"] is not None

        conn = sqlite3.connect(str(db_file))
        row = conn.execute("SELECT name FROM users WHERE id = 1").fetchone()
        conn.close()
        assert row[0] == "Bob"

        rollback_response = client.post(f"/rollback/{run_body['rollback_id']}")
        assert rollback_response.status_code == 200

        conn = sqlite3.connect(str(db_file))
        row = conn.execute("SELECT name FROM users WHERE id = 1").fetchone()
        conn.close()
        assert row[0] == "Alice"