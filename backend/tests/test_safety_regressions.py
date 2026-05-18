"""Regression tests for dangerous SQL safety bypass patterns."""

from plain_db.models import SQLCandidate
from plain_db.safety import RuleBasedSafetyVerifier


def test_safety_blocks_drop_database_with_comment_prefix():
    verifier = RuleBasedSafetyVerifier()
    result = verifier.verify(SQLCandidate(sql="/* keep */ DROP DATABASE prod"))
    assert result.passed is False


def test_safety_blocks_attach_database_statement():
    verifier = RuleBasedSafetyVerifier()
    result = verifier.verify(SQLCandidate(sql="attach database 'other.db' as aux"))
    assert result.passed is False


def test_safety_blocks_multi_statement_with_hidden_delete():
    verifier = RuleBasedSafetyVerifier()
    result = verifier.verify(SQLCandidate(sql="SELECT 1;\nDELETE FROM users"))
    assert result.passed is False
    assert "Multiple statements" in result.reason


def test_safety_rejects_with_clause_root_command_when_ddl_not_allowed():
    verifier = RuleBasedSafetyVerifier(allow_ddl=False)
    result = verifier.verify(SQLCandidate(sql="WITH c AS (SELECT 1) SELECT * FROM c"))
    assert result.passed is False
    assert "Only DML commands" in result.reason


def test_safety_allows_standard_dml_with_lowercase():
    verifier = RuleBasedSafetyVerifier()
    result = verifier.verify(SQLCandidate(sql="update users set name = 'new' where id = 1"))
    assert result.passed is True