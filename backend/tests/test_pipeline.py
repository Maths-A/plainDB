"""Tests for PlainDB pipeline and verifiers."""

import pytest
from plain_db import PlainDBPipeline, PipelineConfig, SQLCandidate, UserIntent
from plain_db.adapters import SQLiteAdapter
from plain_db.default_verifiers import HeuristicSemanticVerifier, PostCommitRowCountVerifier
from plain_db.safety import RuleBasedSafetyVerifier


@pytest.fixture
def sqlite_adapter():
    """Create an in-memory SQLite adapter for testing."""
    adapter = SQLiteAdapter(":memory:")
    
    # Create a test table
    adapter.query(None, "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
    adapter.query(None, "INSERT INTO users (name, age) VALUES ('Alice', 30)")
    adapter.query(None, "INSERT INTO users (name, age) VALUES ('Bob', 25)")
    
    yield adapter
    adapter.close()


@pytest.fixture
def pipeline(sqlite_adapter):
    """Create a PlainDBPipeline for testing."""
    return PlainDBPipeline(
        adapter=sqlite_adapter,
        semantic_verifier=HeuristicSemanticVerifier(),
        safety_verifier=RuleBasedSafetyVerifier(),
    )


class TestSemanticVerifier:
    """Tests for semantic verification."""
    
    def test_select_intent_matches_semantic(self):
        """SELECT intent should match SELECT SQL."""
        verifier = HeuristicSemanticVerifier()
        intent = UserIntent(
            text="Show all users",
            expected_action="SELECT",
        )
        candidate = SQLCandidate(sql="SELECT * FROM users")
        
        result = verifier.verify(intent, candidate)
        assert result.passed
        assert "SELECT" in result.details["action"]
    
    def test_insert_intent_matches_semantic(self):
        """INSERT intent should match INSERT SQL."""
        verifier = HeuristicSemanticVerifier()
        intent = UserIntent(
            text="Add a new user",
            expected_action="INSERT",
        )
        candidate = SQLCandidate(sql="INSERT INTO users (name, age) VALUES ('Charlie', 35)")
        
        result = verifier.verify(intent, candidate)
        assert result.passed
    
    def test_expected_tables_validation(self):
        """Verifier should check for expected tables."""
        verifier = HeuristicSemanticVerifier()
        intent = UserIntent(
            text="Get users",
            expected_tables=["users", "missing_table"],
        )
        candidate = SQLCandidate(sql="SELECT * FROM users")
        
        result = verifier.verify(intent, candidate)
        assert not result.passed
        assert "missing_table" in str(result.details)


class TestSafetyVerifier:
    """Tests for safety verification."""
    
    def test_forbidden_drop_database(self):
        """DROP DATABASE should be rejected."""
        verifier = RuleBasedSafetyVerifier(allow_ddl=False)
        candidate = SQLCandidate(sql="DROP DATABASE main")
        
        result = verifier.verify(candidate)
        assert not result.passed
        assert "forbidden" in result.reason.lower()
    
    def test_allowed_select(self):
        """SELECT should pass safety checks."""
        verifier = RuleBasedSafetyVerifier()
        candidate = SQLCandidate(sql="SELECT * FROM users")
        
        result = verifier.verify(candidate)
        assert result.passed
    
    def test_allowed_insert(self):
        """INSERT should pass safety checks."""
        verifier = RuleBasedSafetyVerifier()
        candidate = SQLCandidate(sql="INSERT INTO users (name) VALUES ('David')")
        
        result = verifier.verify(candidate)
        assert result.passed
    
    def test_multiple_statements_rejected(self):
        """Multiple statements should be rejected."""
        verifier = RuleBasedSafetyVerifier()
        candidate = SQLCandidate(sql="SELECT * FROM users; DELETE FROM users;")
        
        result = verifier.verify(candidate)
        assert not result.passed


class TestPipeline:
    """Tests for the complete pipeline."""
    
    def test_simple_select_execution(self, pipeline):
        """Test execution of a simple SELECT statement."""
        intent = UserIntent(
            text="Get all users",
            expected_action="SELECT",
            expected_tables=["users"],
        )
        candidate = SQLCandidate(sql="SELECT * FROM users")
        
        result = pipeline.run(intent, candidate)
        
        assert result.accepted
        assert any(s.stage == "execution" and s.passed for s in result.stages)
    
    def test_dry_run_mode(self, pipeline, sqlite_adapter):
        """Test dry-run mode doesn't commit."""
        intent = UserIntent(
            text="Add a user",
            expected_action="INSERT",
            expected_tables=["users"],
        )
        candidate = SQLCandidate(sql="INSERT INTO users (name, age) VALUES ('Eve', 28)")
        config = PipelineConfig(
            dry_run_only=True,
            watched_tables=["users"],
        )
        
        # Count before
        before = sqlite_adapter.query(None, "SELECT COUNT(*) as c FROM users")
        before_count = before[0]["c"]
        
        # Run in dry-run mode
        result = pipeline.run(intent, candidate, config)
        
        # Count after (should be unchanged)
        after = sqlite_adapter.query(None, "SELECT COUNT(*) as c FROM users")
        after_count = after[0]["c"]
        
        assert before_count == after_count
        assert not result.committed


class TestSQLiteAdapter:
    """Tests for SQLite adapter."""
    
    def test_adapter_creation(self, sqlite_adapter):
        """Adapter should create and open connections."""
        assert sqlite_adapter.db_path == ":memory:"
    
    def test_query_execution(self, sqlite_adapter):
        """Query should return results."""
        result = sqlite_adapter.query(None, "SELECT COUNT(*) as c FROM users")
        assert len(result) == 1
        assert result[0]["c"] == 2
    
    def test_transaction_commit(self, sqlite_adapter):
        """Transaction should commit changes."""
        with sqlite_adapter.begin() as tx:
            sqlite_adapter.execute(tx, "INSERT INTO users (name, age) VALUES ('Frank', 40)")
            tx.commit()
        
        result = sqlite_adapter.query(None, "SELECT COUNT(*) as c FROM users")
        assert result[0]["c"] == 3
    
    def test_transaction_rollback(self, sqlite_adapter):
        """Transaction should rollback on error."""
        try:
            with sqlite_adapter.begin() as tx:
                sqlite_adapter.execute(tx, "INSERT INTO users (name, age) VALUES ('Grace', 32)")
                # Force an error by calling non-existent table
                sqlite_adapter.query(tx, "SELECT * FROM nonexistent")
        except Exception:
            pass
        
        result = sqlite_adapter.query(None, "SELECT COUNT(*) as c FROM users")
        # Should still be 2 (rollback occurred)
        assert result[0]["c"] == 2
