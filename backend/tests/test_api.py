"""Tests for PlainDB REST API."""

import pytest
from fastapi.testclient import TestClient
from api.main import app, lifespan
import tempfile
import os


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["PLAINDB_DB_PATH"] = path
    yield path
    if os.path.exists(path):
        os.remove(path)


class TestHealthEndpoint:
    """Tests for health check endpoint."""
    
    def test_health_check(self, client):
        """Health endpoint should return status."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "service" in data


class TestInfoEndpoint:
    """Tests for service info endpoint."""
    
    def test_service_info(self, client):
        """Info endpoint should return service details."""
        response = client.get("/api/v1/info")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "plaindb-backend"
        assert "endpoints" in data
        assert len(data["endpoints"]) > 0


class TestGenerateSQLEndpoint:
    """Tests for SQL generation endpoint."""
    
    def test_generate_sql_basic(self, client):
        """Should handle basic SQL generation request."""
        payload = {
            "intent_text": "Show all users",
            "expected_tables": ["users"],
            "expected_action": "SELECT",
        }
        response = client.post("/api/v1/generate-sql", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert "accepted" in data
        assert "stages" in data
        assert "attempts" in data
        assert isinstance(data["stages"], list)
    
    def test_generate_sql_with_dry_run(self, client):
        """Should handle dry-run mode."""
        payload = {
            "intent_text": "Insert new record",
            "expected_action": "INSERT",
            "dry_run": True,
            "watched_tables": ["users"],
        }
        response = client.post("/api/v1/generate-sql", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert "dry_run" in str(data) or "stages" in data
    
    def test_generate_sql_missing_intent(self, client):
        """Should reject request without intent."""
        payload = {
            "expected_tables": ["users"],
        }
        response = client.post("/api/v1/generate-sql", json=payload)
        
        assert response.status_code == 422  # Validation error


class TestAPIResponseFormat:
    """Tests for API response format compliance."""
    
    def test_verification_stage_structure(self, client):
        """Verification stages should have expected structure."""
        payload = {
            "intent_text": "Select all data",
            "expected_action": "SELECT",
        }
        response = client.post("/api/v1/generate-sql", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # Check stages
        for stage in data["stages"]:
            assert "stage" in stage
            assert "passed" in stage
            assert "reason" in stage
            assert "details" in stage
    
    def test_execution_response_structure(self, client):
        """Execution response should have expected structure."""
        payload = {
            "intent_text": "Select all users",
            "expected_action": "SELECT",
        }
        response = client.post("/api/v1/generate-sql", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        if data["execution"]:
            execution = data["execution"]
            assert "success" in execution
            assert "rowcount" in execution
            assert "error" in execution or execution["error"] is None


class TestErrorHandling:
    """Tests for error handling."""
    
    def test_generate_sql_error_handling(self, client):
        """Should handle errors gracefully."""
        # This test checks that API can handle edge cases
        payload = {
            "intent_text": "",
            "expected_tables": [],
        }
        response = client.post("/api/v1/generate-sql", json=payload)
        
        # Should either succeed with validation or return error
        assert response.status_code in [200, 422]
