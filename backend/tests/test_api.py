"""Tests for the PlainDB backend REST API."""

import pytest
from fastapi.testclient import TestClient

from api.main import app
from plain_db.models import BackendRunResult, ExecutionResult, VerificationQueryResult, VerificationStageResult
from plain_db.rollback import RollbackService


class FakePipeline:
    def run(self, request):
        return BackendRunResult(
            accepted=True,
            committed=not request.dry_run,
            generated_sql="SELECT 1",
            verification_queries=["SELECT 1 AS ok"],
            verification_results=[VerificationQueryResult(query="SELECT 1 AS ok", rows=[{"ok": 1}], passed=True)],
            execution=ExecutionResult(success=True, rowcount=1, lastrowid=None, rows=[{"ok": 1}]),
            stages=[
                VerificationStageResult(stage="generation", passed=True, reason="generated"),
                VerificationStageResult(stage="verification", passed=True, reason="verified"),
            ],
            attempts=1,
            schema={"dialect": "sqlite", "tables": []},
        )


class FakeMutatingPipeline:
    def run(self, request):
        return BackendRunResult(
            accepted=True,
            committed=True,
            generated_sql="UPDATE users SET name = 'Alice' WHERE id = 1",
            verification_queries=["SELECT 1"],
            verification_results=[VerificationQueryResult(query="SELECT 1", rows=[{"ok": 1}], passed=True)],
            execution=ExecutionResult(success=True, rowcount=1),
            stages=[VerificationStageResult(stage="commit", passed=True, reason="committed")],
            attempts=1,
            schema={"dialect": "sqlite", "tables": []},
        )


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        test_client.app.state.pipeline = FakePipeline()
        yield test_client


def test_health_check(client):
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "default_provider" in data
    assert "default_database" in data


def test_root_endpoint(client):
    response = client.get("/")

    assert response.status_code == 200
    data = response.json()
    assert "request_contract" in data


def test_run_endpoint_uses_new_contract(client):
    payload = {
        "intent_text": "Show all users",
        "api_key": "test-key",
        "provider": "gemini",
        "database_target": {
            "dialect": "sqlite",
            "database": ":memory:",
        },
        "dry_run": True,
    }

    response = client.post("/run", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] is True
    assert data["sql"] == "SELECT 1"
    assert data["generated_sql"] == "SELECT 1"
    assert data["verification_queries"] == ["SELECT 1 AS ok"]
    assert data["execution"]["success"] is True
    assert data["stages"][0]["stage"] == "generation"


def test_run_endpoint_requires_explanation(client):
    payload = {
        "api_key": "test-key",
        "database_target": {
            "dialect": "sqlite",
            "database": ":memory:",
        },
    }

    response = client.post("/run", json=payload)

    assert response.status_code == 422


def test_run_endpoint_returns_400_when_pipeline_raises():
    class FailingPipeline:
        def run(self, request):
            raise RuntimeError("pipeline boom")

    with TestClient(app) as test_client:
        test_client.app.state.pipeline = FailingPipeline()
        response = test_client.post(
            "/run",
            json={
                "intent_text": "show users",
                "api_key": "test-key",
                "provider": "gemini",
                "database_target": {"dialect": "sqlite", "database": ":memory:"},
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "pipeline boom"


def test_run_endpoint_returns_rollback_id_for_committed_mutation(tmp_path):
    db_file = tmp_path / "rollback_test.sqlite"
    db_file.write_text("placeholder", encoding="utf-8")

    with TestClient(app) as test_client:
        test_client.app.state.pipeline = FakeMutatingPipeline()
        test_client.app.state.rollback_service = RollbackService()

        response = test_client.post(
            "/run",
            json={
                "intent_text": "update user",
                "api_key": "test-key",
                "provider": "gemini",
                "database_target": {"dialect": "sqlite", "database": str(db_file)},
                "dry_run": False,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["rollback_id"] is not None

        list_response = test_client.get("/rollback/snapshots")
        assert list_response.status_code == 200
        assert any(item["rollback_id"] == body["rollback_id"] for item in list_response.json())
