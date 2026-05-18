import json
import os
import re
import ssl
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

import certifi

from .schema import DatabaseSchema


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline >= 0:
            stripped = stripped[first_newline + 1 :]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()


def _safe_json_loads(text: str) -> Dict[str, Any]:
    payload = _strip_code_fences(text)
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {"text": payload}


@dataclass
class AIJudgement:
    passed: bool
    reason: str
    retry: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


class PlainDBAIClient:
    """Small provider adapter for generating and verifying SQL with an AI model."""

    def __init__(
        self,
        provider: str,
        api_key: str,
        model_name: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        timeout_seconds: int = 60,
    ) -> None:
        self.provider = (provider or "").strip().lower()
        self.api_key = api_key
        self.model_name = model_name or ("gpt-4o-mini" if self.provider == "openai" else "gemini-2.5-flash")
        self.endpoint_url = endpoint_url
        self.timeout_seconds = timeout_seconds

    def generate_sql(
        self,
        explanation: str,
        schema: DatabaseSchema,
        attempt: int = 1,
        previous_sql: Optional[str] = None,
        previous_error: Optional[str] = None,
    ) -> str:
        prompt = self._build_generation_prompt(explanation, schema, attempt, previous_sql, previous_error)
        result = self._complete_json(prompt, response_name="sql_generation")
        sql = str(result.get("sql", "")).strip()
        if not sql:
            raise ValueError("AI did not return SQL.")
        return sql

    def generate_sql_with_verification(
        self,
        explanation: str,
        schema: DatabaseSchema,
        attempt: int = 1,
        previous_sql: Optional[str] = None,
        previous_error: Optional[str] = None,
    ) -> Dict[str, Any]:
        prompt = self._build_generation_and_verification_prompt(explanation, schema, attempt, previous_sql, previous_error)
        result = self._complete_json(prompt, response_name="sql_generation_verification")
        sql = str(result.get("sql", "")).strip()
        if not sql:
            raise ValueError("AI did not return SQL.")

        verification = AIJudgement(
            passed=bool(result.get("passed", True)),
            reason=str(result.get("reason", "SQL verification returned no reason.")),
            retry=bool(result.get("retry", False)),
            details=result,
        )
        return {"sql": sql, "verification": verification}

    def verify_sql(self, explanation: str, sql: str, schema: DatabaseSchema) -> AIJudgement:
        prompt = self._build_verification_prompt(explanation, sql, schema)
        result = self._complete_json(prompt, response_name="sql_verification")
        return AIJudgement(
            passed=bool(result.get("passed", False)),
            reason=str(result.get("reason", "SQL verification returned no reason.")),
            retry=bool(result.get("retry", False)),
            details=result,
        )

    def generate_verification_queries(self, explanation: str, schema: DatabaseSchema, sql: str) -> List[str]:
        sql_text = (sql or "").strip()
        if sql_text.upper().startswith("SELECT"):
            # Deterministic planning for read-only statements.
            return [sql_text]

        fallback = self._fallback_verification_queries(schema, sql_text)
        if fallback:
            return fallback

        prompt = self._build_verification_queries_prompt(explanation, schema, sql_text)
        result = self._complete_json(prompt, response_name="verification_queries")
        queries = result.get("queries", [])
        if not isinstance(queries, list):
            queries = []
        cleaned = [str(query).strip() for query in queries if str(query).strip()]
        if cleaned:
            return cleaned

        # Last-resort fallback when SQL shape is unknown.
        return ["SELECT 1 AS verification_probe"]

    def _fallback_verification_queries(self, schema: DatabaseSchema, sql_text: str) -> List[str]:
        sql_upper = sql_text.upper()

        if sql_upper.startswith("CREATE TABLE"):
            table_name = self._extract_table_name(sql_text, r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[\w\.\"`]+)")
            if table_name:
                return [self._table_exists_query(schema.dialect, table_name)]

        if sql_upper.startswith("DROP TABLE"):
            table_name = self._extract_table_name(sql_text, r"^\s*DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?P<name>[\w\.\"`]+)")
            if table_name:
                return [self._table_exists_query(schema.dialect, table_name)]

        if sql_upper.startswith("INSERT INTO"):
            table_name = self._extract_table_name(sql_text, r"^\s*INSERT\s+INTO\s+(?P<name>[\w\.\"`]+)")
            if table_name:
                return [f"SELECT COUNT(*) AS row_count FROM {self._identifier_for_sql(table_name)}"]

        if sql_upper.startswith("UPDATE"):
            table_name = self._extract_table_name(sql_text, r"^\s*UPDATE\s+(?P<name>[\w\.\"`]+)")
            if table_name:
                return [f"SELECT COUNT(*) AS row_count FROM {self._identifier_for_sql(table_name)}"]

        if sql_upper.startswith("DELETE FROM"):
            table_name = self._extract_table_name(sql_text, r"^\s*DELETE\s+FROM\s+(?P<name>[\w\.\"`]+)")
            if table_name:
                where_clause = self._extract_where_clause(sql_text)
                if where_clause:
                    return [
                        f"SELECT COUNT(*) AS row_count FROM {self._identifier_for_sql(table_name)} WHERE {where_clause}"
                    ]
                return [f"SELECT COUNT(*) AS row_count FROM {self._identifier_for_sql(table_name)}"]

        return []

    def _extract_table_name(self, sql_text: str, pattern: str) -> Optional[str]:
        match = re.search(pattern, sql_text, flags=re.IGNORECASE)
        if not match:
            return None
        raw_name = (match.group("name") or "").strip()
        if not raw_name:
            return None
        # Keep only terminal identifier for information_schema checks.
        if "." in raw_name:
            raw_name = raw_name.split(".")[-1]
        return raw_name.strip('"`')

    def _identifier_for_sql(self, name: str) -> str:
        safe = (name or "").strip().replace('"', '""')
        return f'"{safe}"'

    def _extract_where_clause(self, sql_text: str) -> Optional[str]:
        match = re.search(
            r"\bWHERE\b\s+(?P<where>.+?)(?:\bRETURNING\b.+)?\s*;?\s*$",
            sql_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return None
        where_clause = (match.group("where") or "").strip()
        return where_clause or None

    def _table_exists_query(self, dialect: str, table_name: str) -> str:
        table_literal = table_name.replace("'", "''")
        normalized = (dialect or "").strip().lower()

        if normalized in {"sqlite", "sqlite3"}:
            return (
                "SELECT name "
                "FROM sqlite_master "
                f"WHERE type = 'table' AND name = '{table_literal}'"
            )

        if normalized in {"mysql", "mariadb"}:
            return (
                "SELECT table_name "
                "FROM information_schema.tables "
                f"WHERE table_schema = DATABASE() AND table_name = '{table_literal}'"
            )

        # Default: PostgreSQL-compatible check.
        return (
            "SELECT table_name "
            "FROM information_schema.tables "
            f"WHERE table_schema = current_schema() AND table_name = '{table_literal}'"
        )

    def classify_execution_error(self, explanation: str, sql: str, error_message: str, schema: DatabaseSchema) -> AIJudgement:
        prompt = self._build_error_classification_prompt(explanation, sql, error_message, schema)
        result = self._complete_json(prompt, response_name="execution_error_classification")
        return AIJudgement(
            passed=not bool(result.get("retry", False)),
            reason=str(result.get("reason", error_message)),
            retry=bool(result.get("retry", False)),
            details=result,
        )

    def verify_results(
        self,
        explanation: str,
        sql: str,
        verification_queries: List[str],
        verification_results: List[Dict[str, Any]],
        schema: DatabaseSchema,
    ) -> AIJudgement:
        prompt = self._build_result_verification_prompt(explanation, sql, verification_queries, verification_results, schema)
        result = self._complete_json(prompt, response_name="verification_result")
        return AIJudgement(
            passed=bool(result.get("passed", False)),
            reason=str(result.get("reason", "Verification result was inconclusive.")),
            retry=bool(result.get("retry", False)),
            details=result,
        )

    def _complete_json(self, prompt: str, response_name: str) -> Dict[str, Any]:
        raw_text = self._complete_text(prompt)
        parsed = _safe_json_loads(raw_text)
        if "text" in parsed and len(parsed) == 1:
            return {"passed": False, "reason": f"{response_name} response was not valid JSON.", "text": parsed["text"]}
        return parsed

    def _complete_text(self, prompt: str) -> str:
        if not self.api_key:
            raise ValueError("API key is required for AI calls.")

        if self.provider == "openai":
            return self._call_openai(prompt)
        if self.provider == "gemini":
            return self._call_gemini(prompt)

        raise ValueError(f"Unsupported AI provider: {self.provider}")

    def _call_openai(self, prompt: str) -> str:
        base_url = (self.endpoint_url or "https://api.openai.com").rstrip("/")
        if base_url.endswith("/v1"):
            url = f"{base_url}/chat/completions"
        else:
            url = f"{base_url}/v1/chat/completions"

        body = json.dumps(
            {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": "You are a backend SQL architect. Return only valid JSON when asked."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            }
        ).encode("utf-8")

        request = urllib_request.Request(url, data=body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"})
        try:
            with self._urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI API error {exc.code}: {body_text}") from exc

        choices = payload.get("choices", [])
        if not choices:
            raise RuntimeError("OpenAI response did not contain choices.")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if not content:
            raise RuntimeError("OpenAI response content was empty.")
        return content

    def _call_gemini(self, prompt: str) -> str:
        model = self.model_name or "gemini-2.5-flash"
        if self.endpoint_url:
            url = self.endpoint_url
            if "generateContent" not in url:
                url = url.rstrip("/") + f"/v1beta/models/{model}:generateContent"
        else:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

        body = json.dumps(
            {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
            }
        ).encode("utf-8")

        api_credential = (self.api_key or "").strip()
        # Accept common pasted formats like "Bearer <token>" or quoted strings.
        if api_credential.startswith("Bearer "):
            api_credential = api_credential[len("Bearer ") :].strip()
        if len(api_credential) >= 2 and api_credential[0] == api_credential[-1] and api_credential[0] in {'"', "'"}:
            api_credential = api_credential[1:-1].strip()
        headers = {"Content-Type": "application/json"}

        # Gemini accepts either API key query param or OAuth Bearer token.
        if "key=" in url:
            request_url = url
        elif api_credential.startswith("AIza"):
            joiner = "&" if "?" in url else "?"
            request_url = f"{url}{joiner}key={api_credential}"
        else:
            request_url = url
            headers["Authorization"] = f"Bearer {api_credential}"

        request = urllib_request.Request(request_url, data=body, headers=headers)

        try:
            with self._urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Gemini API error {exc.code}: {body_text}") from exc

        candidates = payload.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini response did not contain candidates.")

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        if not parts:
            raise RuntimeError("Gemini response did not contain text parts.")

        text = parts[0].get("text", "")
        if not text:
            raise RuntimeError("Gemini response text was empty.")
        return text

    def _urlopen(self, request: urllib_request.Request):
        # Use certifi CA bundle explicitly to avoid local trust-store gaps that
        # cause CERTIFICATE_VERIFY_FAILED on outbound HTTPS calls.
        context = ssl.create_default_context(cafile=certifi.where())
        try:
            return urllib_request.urlopen(request, timeout=self.timeout_seconds, context=context)
        except TypeError:
            return urllib_request.urlopen(request, timeout=self.timeout_seconds)

    @staticmethod
    def _schema_text(schema: DatabaseSchema) -> str:
        return json.dumps(schema.to_prompt_payload(), indent=2)

    def _build_generation_prompt(
        self,
        explanation: str,
        schema: DatabaseSchema,
        attempt: int,
        previous_sql: Optional[str],
        previous_error: Optional[str],
    ) -> str:
        retry_text = ""
        if previous_sql or previous_error:
            retry_text = (
                "\nPrevious attempt failed. Use this context to repair the SQL:\n"
                f"Previous SQL: {previous_sql or '(none)'}\n"
                f"Previous error: {previous_error or '(none)'}\n"
            )

        return (
            "Generate a single SQL statement as JSON with keys sql and reason. "
            "Use the provided database schema and the English explanation. "
            "Return only JSON.\n"
            f"Attempt: {attempt}\n"
            f"Database schema:\n{self._schema_text(schema)}\n"
            f"English explanation:\n{explanation}{retry_text}"
        )

    def _build_generation_and_verification_prompt(
        self,
        explanation: str,
        schema: DatabaseSchema,
        attempt: int,
        previous_sql: Optional[str],
        previous_error: Optional[str],
    ) -> str:
        retry_text = ""
        if previous_sql or previous_error:
            retry_text = (
                "\nPrevious attempt failed. Use this context to repair the SQL:\n"
                f"Previous SQL: {previous_sql or '(none)'}\n"
                f"Previous error: {previous_error or '(none)'}\n"
            )

        return (
            "Generate a single SQL statement and validate it against the English explanation and schema. "
            "Return only JSON with keys sql (string), passed (boolean), reason (string), retry (boolean).\n"
            f"Attempt: {attempt}\n"
            f"Database schema:\n{self._schema_text(schema)}\n"
            f"English explanation:\n{explanation}{retry_text}"
        )

    def _build_verification_prompt(self, explanation: str, sql: str, schema: DatabaseSchema) -> str:
        return (
            "Check whether the SQL matches the English explanation and schema. "
            "Return JSON with keys passed (boolean), reason (string), retry (boolean).\n"
            f"Database schema:\n{self._schema_text(schema)}\n"
            f"English explanation:\n{explanation}\n"
            f"SQL:\n{sql}"
        )

    def _build_verification_queries_prompt(self, explanation: str, schema: DatabaseSchema, sql: str) -> str:
        return (
            "From the schema and the English explanation, produce the minimal set of SELECT queries needed to verify the expectation. "
            "Return JSON with keys queries (array of SQL strings) and reason. Use only SELECT queries.\n"
            f"Database schema:\n{self._schema_text(schema)}\n"
            f"English explanation:\n{explanation}\n"
            f"Generated SQL:\n{sql}"
        )

    def _build_error_classification_prompt(self, explanation: str, sql: str, error_message: str, schema: DatabaseSchema) -> str:
        return (
            "Classify the database execution error. Decide whether this is likely caused by the generated SQL or by a human/configuration mistake. "
            "Return JSON with keys retry (boolean), kind (sql_generated|human|unknown), reason (string).\n"
            f"Database schema:\n{self._schema_text(schema)}\n"
            f"English explanation:\n{explanation}\n"
            f"SQL:\n{sql}\n"
            f"Error:\n{error_message}"
        )

    def _build_result_verification_prompt(
        self,
        explanation: str,
        sql: str,
        verification_queries: List[str],
        verification_results: List[Dict[str, Any]],
        schema: DatabaseSchema,
    ) -> str:
        return (
            "Review the verification query results and decide if they match the English expectation. "
            "Return JSON with keys passed (boolean), reason (string), retry (boolean).\n"
            f"Database schema:\n{self._schema_text(schema)}\n"
            f"English explanation:\n{explanation}\n"
            f"Generated SQL:\n{sql}\n"
            f"Verification queries:\n{json.dumps(verification_queries, indent=2)}\n"
            f"Verification results:\n{json.dumps(verification_results, indent=2)}"
        )