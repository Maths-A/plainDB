import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plain_db import PipelineConfig, PlainDBPipeline, SQLCandidate, UserIntent
from plain_db.adapters import SQLiteAdapter


def bootstrap_demo_db(db_path: str) -> None:
    adapter = SQLiteAdapter(db_path)
    with adapter.begin() as tx:
        adapter.execute(
            tx,
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                score INTEGER NOT NULL
            )
            """,
        )
        adapter.execute(tx, "DELETE FROM users")
        adapter.execute(tx, "INSERT INTO users(name, score) VALUES ('Alice', 10)")
        adapter.execute(tx, "INSERT INTO users(name, score) VALUES ('Bob', 12)")
        tx.commit()
    adapter.close()


def run_pipeline_demo(db_path: str) -> None:
    adapter = SQLiteAdapter(db_path)
    pipeline = PlainDBPipeline(adapter=adapter)

    intent = UserIntent(
        text="Increase Alice score by 2 points",
        expected_tables=["users"],
        expected_action="UPDATE",
    )

    candidate = SQLCandidate(
        sql="UPDATE users SET scor = score + 2 WHERE name = :name",
        params={"name": "Alice"},
        model_name="ai-generator-v1",
    )

    def regenerate_sql(intent: UserIntent, previous: SQLCandidate, error: str, attempt: int) -> SQLCandidate:
        _ = intent
        _ = attempt
        fixed_sql = previous.sql
        if "no such column: scor" in error:
            fixed_sql = re.sub(r"\bscor\b", "score", previous.sql)
        return SQLCandidate(sql=fixed_sql, params=previous.params, model_name="ai-regenerator-v1")

    result = pipeline.run(
        intent,
        candidate,
        config=PipelineConfig(
            watched_tables=["users"],
            fail_fast=True,
            dry_run_only=False,
            max_retries=1,
        ),
        regenerate_sql=regenerate_sql,
    )

    print("Accepted:", result.accepted)
    print("Committed:", result.committed)
    print("Attempts:", result.attempts)
    for stage in result.stages:
        print(f"- {stage.stage}: {'PASS' if stage.passed else 'FAIL'} -> {stage.reason}")

    rows = adapter.query(None, "SELECT id, name, score FROM users ORDER BY id")
    print("Final rows:", rows)
    adapter.close()


if __name__ == "__main__":
    demo_db = str(Path(__file__).parent / "demo.sqlite3")
    bootstrap_demo_db(demo_db)
    run_pipeline_demo(demo_db)
