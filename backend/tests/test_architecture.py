"""Tests for the architecture pipeline control flow."""

from contextlib import contextmanager

import pytest

from plain_db.architecture import PlainDBArchitecturePipeline
from plain_db.llm import AIJudgement
from plain_db.models import BackendRequest, DatabaseTarget, ExecutionResult
from plain_db.schema import DatabaseSchema


class FakeTx:
    def __init__(self):
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def commit(self):
        self.committed = True
        self.closed = True

    def rollback(self):
        self.rolled_back = True
        self.closed = True


class FakeAdapter:
    def __init__(self, execute_results=None, query_results=None):
        self.schema = DatabaseSchema(dialect="sqlite", tables=[])
        self.execute_results = list(execute_results or [ExecutionResult(success=True, rowcount=1)])
        self.query_results = query_results or {"SELECT 1": [{"ok": 1}]}
        self.transactions = []
        self.closed = False

    @contextmanager
    def begin(self):
        tx = FakeTx()
        self.transactions.append(tx)
        try:
            yield tx
        finally:
            if not tx.closed:
                tx.rollback()

    def execute(self, tx, sql, params=None):
        if self.execute_results:
            return self.execute_results.pop(0)
        return ExecutionResult(success=True, rowcount=1)

    def query(self, tx, sql, params=None):
        return self.query_results.get(sql, [{"ok": 1}])

    def describe_schema(self):
        return self.schema

    def close(self):
        self.closed = True


class FakeAIClient:
    def __init__(
        self,
        generated_sqls=None,
        sql_verifications=None,
        verification_queries=None,
        error_classifications=None,
        result_verifications=None,
    ):
        self.generated_sqls = list(generated_sqls or ["SELECT 1"])
        self.sql_verifications = list(sql_verifications or [AIJudgement(passed=True, reason="ok")])
        self.verification_queries = list(verification_queries or [["SELECT 1"]])
        self.error_classifications = list(
            error_classifications
            or [AIJudgement(passed=True, reason="human", retry=False, details={"kind": "human"})]
        )
        self.result_verifications = list(result_verifications or [AIJudgement(passed=True, reason="ok")])

    def generate_sql(self, explanation, schema, attempt=1, previous_sql=None, previous_error=None):
        if len(self.generated_sqls) > 1:
            return self.generated_sqls.pop(0)
        return self.generated_sqls[0]

    def verify_sql(self, explanation, sql, schema):
        if len(self.sql_verifications) > 1:
            return self.sql_verifications.pop(0)
        return self.sql_verifications[0]

    def generate_verification_queries(self, explanation, schema, sql):
        if len(self.verification_queries) > 1:
            return self.verification_queries.pop(0)
        return self.verification_queries[0]

    def classify_execution_error(self, explanation, sql, error_message, schema):
        if len(self.error_classifications) > 1:
            return self.error_classifications.pop(0)
        return self.error_classifications[0]

    def verify_results(self, explanation, sql, verification_queries, verification_results, schema):
        if len(self.result_verifications) > 1:
            return self.result_verifications.pop(0)
        return self.result_verifications[0]


class FailingQueriesAIClient(FakeAIClient):
    def generate_verification_queries(self, explanation, schema, sql):
        raise ValueError("AI returned an empty verification query set.")


def _request(**kwargs):
    payload = {
        "english_explanation": "list users",
        "ai_provider": "gemini",
        "api_key": "key",
        "database": DatabaseTarget(dialect="sqlite", database=":memory:"),
        "dry_run": False,
        "max_retries": 1,
    }
    payload.update(kwargs)
    return BackendRequest(**payload)


def test_architecture_dry_run_rolls_back():
    adapter = FakeAdapter(execute_results=[ExecutionResult(success=True, rowcount=1)])
    ai_client = FakeAIClient(
        result_verifications=[AIJudgement(passed=True, reason="ok", retry=False)],
        verification_queries=[["SELECT 1"]],
    )
    pipeline = PlainDBArchitecturePipeline(adapter_factory=lambda _: adapter, ai_client_factory=lambda **_: ai_client)

    result = pipeline.run(_request(dry_run=True))

    assert result.accepted is True
    assert result.committed is False
    assert adapter.transactions[0].rolled_back is True
    assert adapter.transactions[0].committed is False
    assert adapter.closed is True


def test_architecture_retries_when_execution_error_is_sql_generated():
    adapter = FakeAdapter(
        execute_results=[
            ExecutionResult(success=False, rowcount=0, error="syntax error"),
            ExecutionResult(success=True, rowcount=1),
        ]
    )
    ai_client = FakeAIClient(
        generated_sqls=["SELECT bad", "SELECT 1"],
        sql_verifications=[AIJudgement(passed=True, reason="ok"), AIJudgement(passed=True, reason="ok")],
        error_classifications=[
            AIJudgement(passed=False, reason="retry with fixed SQL", retry=True, details={"kind": "sql_generated"})
        ],
        result_verifications=[AIJudgement(passed=True, reason="verified")],
        verification_queries=[["SELECT 1"], ["SELECT 1"]],
    )
    pipeline = PlainDBArchitecturePipeline(adapter_factory=lambda _: adapter, ai_client_factory=lambda **_: ai_client)

    result = pipeline.run(_request(max_retries=1))

    assert result.accepted is True
    assert result.committed is True
    assert result.attempts == 2
    assert any(stage.stage == "execution_error_classification" for stage in result.stages)


def test_architecture_rejects_when_result_verification_fails_without_retry():
    adapter = FakeAdapter(execute_results=[ExecutionResult(success=True, rowcount=1)])
    ai_client = FakeAIClient(
        verification_queries=[["SELECT 1"]],
        result_verifications=[
            AIJudgement(
                passed=False,
                reason="result did not match intent",
                retry=False,
                details={"kind": "verification_failed"},
            )
        ],
    )
    pipeline = PlainDBArchitecturePipeline(adapter_factory=lambda _: adapter, ai_client_factory=lambda **_: ai_client)

    result = pipeline.run(_request(max_retries=1))

    assert result.accepted is False
    assert result.committed is False
    assert result.error == "result did not match intent"
    assert result.error_kind == "verification_failed"
    assert adapter.transactions[0].rolled_back is True


def test_architecture_validates_required_fields_before_adapter():
    pipeline = PlainDBArchitecturePipeline(adapter_factory=lambda _: (_ for _ in ()).throw(RuntimeError("should not run")))

    with pytest.raises(ValueError, match="English explanation is required"):
        pipeline.run(_request(english_explanation="   "))

    with pytest.raises(ValueError, match="API key is required"):
        pipeline.run(_request(api_key=""))


def test_architecture_retries_when_sql_verification_requests_retry():
    adapter = FakeAdapter(execute_results=[ExecutionResult(success=True, rowcount=1)])
    ai_client = FakeAIClient(
        generated_sqls=["SELECT broken", "SELECT 1"],
        sql_verifications=[
            AIJudgement(passed=False, reason="not aligned", retry=True),
            AIJudgement(passed=True, reason="aligned", retry=False),
        ],
        verification_queries=[["SELECT 1"], ["SELECT 1"]],
        result_verifications=[AIJudgement(passed=True, reason="ok")],
    )
    pipeline = PlainDBArchitecturePipeline(adapter_factory=lambda _: adapter, ai_client_factory=lambda **_: ai_client)

    result = pipeline.run(_request(max_retries=1))

    assert result.accepted is True
    assert result.committed is True
    assert result.attempts == 2
    assert any(stage.stage == "sql_verification" and not stage.passed for stage in result.stages)


def test_architecture_stops_when_sql_verification_fails_without_retry():
    adapter = FakeAdapter(execute_results=[ExecutionResult(success=True, rowcount=1)])
    ai_client = FakeAIClient(
        generated_sqls=["SELECT broken"],
        sql_verifications=[AIJudgement(passed=False, reason="not aligned", retry=False)],
    )
    pipeline = PlainDBArchitecturePipeline(adapter_factory=lambda _: adapter, ai_client_factory=lambda **_: ai_client)

    result = pipeline.run(_request(max_retries=2))

    assert result.accepted is False
    assert result.error_kind == "sql_generated"
    assert result.error == "not aligned"
    assert len(adapter.transactions) == 0


def test_architecture_raises_when_ai_returns_invalid_verification_queries_and_closes_adapter():
    adapter = FakeAdapter(execute_results=[ExecutionResult(success=True, rowcount=1)])
    ai_client = FailingQueriesAIClient(sql_verifications=[AIJudgement(passed=True, reason="ok")])
    pipeline = PlainDBArchitecturePipeline(adapter_factory=lambda _: adapter, ai_client_factory=lambda **_: ai_client)

    with pytest.raises(ValueError, match="empty verification query set"):
        pipeline.run(_request())

    assert adapter.closed is True


def test_architecture_marks_failed_verification_queries_and_can_reject_result():
    class QueryFailingAdapter(FakeAdapter):
        def query(self, tx, sql, params=None):
            if "broken_check" in sql:
                raise RuntimeError("verification query failed")
            return super().query(tx, sql, params)

    adapter = QueryFailingAdapter(execute_results=[ExecutionResult(success=True, rowcount=1)])
    ai_client = FakeAIClient(
        verification_queries=[["SELECT 1", "SELECT * FROM broken_check"]],
        result_verifications=[
            AIJudgement(
                passed=False,
                reason="verification query failed",
                retry=False,
                details={"kind": "verification_failed"},
            )
        ],
    )
    pipeline = PlainDBArchitecturePipeline(adapter_factory=lambda _: adapter, ai_client_factory=lambda **_: ai_client)

    result = pipeline.run(_request())

    assert result.accepted is False
    assert result.error_kind == "verification_failed"
    assert any(item.passed is False and item.reason == "verification query failed" for item in result.verification_results)