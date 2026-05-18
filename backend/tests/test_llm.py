"""Tests for PlainDB AI client parsing and provider error handling."""

import io
from urllib.error import HTTPError

import pytest

from plain_db.llm import PlainDBAIClient, _safe_json_loads
from plain_db.schema import DatabaseSchema


class StubAIClient(PlainDBAIClient):
    def __init__(self, responses, provider="gemini", api_key="key"):
        super().__init__(provider=provider, api_key=api_key)
        self.responses = list(responses)

    def _complete_text(self, prompt: str) -> str:
        if self.responses:
            return self.responses.pop(0)
        return "{}"


def _schema() -> DatabaseSchema:
    return DatabaseSchema(dialect="sqlite", tables=[])


def test_safe_json_loads_accepts_code_fence_payload():
    payload = "```json\n{\"sql\": \"SELECT 1\"}\n```"
    parsed = _safe_json_loads(payload)
    assert parsed["sql"] == "SELECT 1"


def test_generate_sql_raises_for_missing_sql_field():
    client = StubAIClient(["{\"reason\": \"missing sql\"}"])

    with pytest.raises(ValueError, match="AI did not return SQL"):
        client.generate_sql("list users", _schema())


def test_generate_sql_raises_for_malformed_json_text_response():
    client = StubAIClient(["this is not json"])

    with pytest.raises(ValueError, match="AI did not return SQL"):
        client.generate_sql("list users", _schema())


def test_generate_verification_queries_falls_back_to_probe_when_ai_returns_empty_list():
    client = StubAIClient(["{\"queries\": []}"])

    queries = client.generate_verification_queries("check users", _schema(), "ALTER TABLE users ADD COLUMN name TEXT")

    assert queries == ["SELECT 1 AS verification_probe"]


def test_generate_verification_queries_uses_ai_for_unknown_sql_shape():
    client = StubAIClient(["{\"queries\": [\"SELECT name FROM pragma_table_info('users')\"]}"])

    queries = client.generate_verification_queries("add name column", _schema(), "ALTER TABLE users ADD COLUMN name TEXT")

    assert queries == ["SELECT name FROM pragma_table_info('users')"]


def test_generate_verification_queries_preserves_delete_where_clause():
    client = StubAIClient([])

    queries = client.generate_verification_queries(
        "delete John Smith",
        _schema(),
        "DELETE FROM person WHERE firstname = 'John' AND surname = 'Smith'",
    )

    assert queries == [
        'SELECT COUNT(*) AS row_count FROM "person" WHERE firstname = \'John\' AND surname = \'Smith\''
    ]


def test_complete_text_requires_api_key():
    client = PlainDBAIClient(provider="gemini", api_key="")

    with pytest.raises(ValueError, match="API key is required"):
        client._complete_text("prompt")


def test_complete_text_rejects_unsupported_provider():
    client = PlainDBAIClient(provider="anthropic", api_key="x")

    with pytest.raises(ValueError, match="Unsupported AI provider"):
        client._complete_text("prompt")


def test_openai_http_error_is_wrapped(monkeypatch):
    client = PlainDBAIClient(provider="openai", api_key="x", endpoint_url="https://api.openai.com")

    def fake_urlopen(req, timeout=0):
        raise HTTPError(
            url="https://api.openai.com/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b"bad key"),
        )

    monkeypatch.setattr("plain_db.llm.urllib_request.urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="OpenAI API error 401"):
        client._call_openai("hello")


def test_gemini_http_error_is_wrapped(monkeypatch):
    client = PlainDBAIClient(provider="gemini", api_key="x", model_name="gemini-2.5-flash")

    def fake_urlopen(req, timeout=0):
        raise HTTPError(
            url="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(b"rate limit"),
        )

    monkeypatch.setattr("plain_db.llm.urllib_request.urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="Gemini API error 429"):
        client._call_gemini("hello")