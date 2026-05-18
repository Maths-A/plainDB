import os
import shutil
import subprocess
import tempfile
import uuid
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from shutil import which
from typing import Dict, List, Optional

from .models import DatabaseTarget


@dataclass
class PendingRollbackSnapshot:
    snapshot_id: str
    dialect: str
    database_path: str
    snapshot_path: str
    created_at: str
    target: DatabaseTarget


@dataclass
class RollbackSnapshot:
    snapshot_id: str
    dialect: str
    database_path: str
    snapshot_path: str
    created_at: str
    target: DatabaseTarget
    source_sql: Optional[str] = None


class RollbackService:
    """Stores pre-change snapshots and can restore them on demand."""

    def __init__(self, storage_dir: Optional[str] = None) -> None:
        self.storage_dir = storage_dir or os.path.join(tempfile.gettempdir(), "plaindb-rollbacks")
        os.makedirs(self.storage_dir, exist_ok=True)
        self._index_path = os.path.join(self.storage_dir, "snapshot-index.json")
        self._snapshots: Dict[str, RollbackSnapshot] = {}
        self._load_index()

    def prepare(self, target: DatabaseTarget) -> Optional[PendingRollbackSnapshot]:
        dialect = (target.dialect or "").strip().lower()
        if dialect == "sqlite":
            return self._prepare_sqlite(target)
        if dialect in {"postgres", "postgresql"}:
            return self._prepare_postgresql(target)
        if dialect == "mysql":
            return self._prepare_mysql(target)
        return None

    def _prepare_sqlite(self, target: DatabaseTarget) -> Optional[PendingRollbackSnapshot]:
        if not target.database or target.database == ":memory:":
            return None
        database_path = os.path.abspath(target.database)
        if not os.path.exists(database_path):
            return None
        snapshot_id = uuid.uuid4().hex
        snapshot_path = os.path.join(self.storage_dir, f"{snapshot_id}.sqlite")
        shutil.copy2(database_path, snapshot_path)
        created_at = datetime.now(timezone.utc).isoformat()
        return PendingRollbackSnapshot(
            snapshot_id=snapshot_id,
            dialect="sqlite",
            database_path=database_path,
            snapshot_path=snapshot_path,
            created_at=created_at,
            target=target,
        )

    def _prepare_postgresql(self, target: DatabaseTarget) -> Optional[PendingRollbackSnapshot]:
        if not target.database:
            return None
        if which("pg_dump") is None:
            raise RuntimeError("PostgreSQL snapshot requires pg_dump to be installed in the backend runtime.")

        snapshot_id = uuid.uuid4().hex
        snapshot_path = os.path.join(self.storage_dir, f"{snapshot_id}.postgres.sql")
        created_at = datetime.now(timezone.utc).isoformat()

        host = self._resolve_host_for_runtime(target.host)
        port = str(target.port or 5432)
        user = target.username or "postgres"
        cmd = [
            "pg_dump",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "-h",
            host,
            "-p",
            port,
            "-U",
            user,
            "-d",
            target.database,
            "-f",
            snapshot_path,
        ]
        env = os.environ.copy()
        if target.password:
            env["PGPASSWORD"] = target.password
        self._run_command(cmd, env=env, error_prefix="Failed to create PostgreSQL checkpoint")
        self._sanitize_postgresql_dump(snapshot_path)

        return PendingRollbackSnapshot(
            snapshot_id=snapshot_id,
            dialect="postgresql",
            database_path=f"{target.database}@{host}:{port}",
            snapshot_path=snapshot_path,
            created_at=created_at,
            target=target,
        )

    def _prepare_mysql(self, target: DatabaseTarget) -> Optional[PendingRollbackSnapshot]:
        if not target.database:
            return None
        if which("mysqldump") is None:
            raise RuntimeError("MySQL snapshot requires mysqldump to be installed in the backend runtime.")

        snapshot_id = uuid.uuid4().hex
        snapshot_path = os.path.join(self.storage_dir, f"{snapshot_id}.mysql.sql")
        created_at = datetime.now(timezone.utc).isoformat()

        host = self._resolve_host_for_runtime(target.host)
        port = str(target.port or 3306)
        user = target.username or "root"
        cmd = [
            "mysqldump",
            "--single-transaction",
            "--add-drop-table",
            "--quick",
            "-h",
            host,
            "-P",
            port,
            "-u",
            user,
            "--result-file",
            snapshot_path,
            target.database,
        ]
        env = os.environ.copy()
        if target.password:
            env["MYSQL_PWD"] = target.password
        self._run_command(cmd, env=env, error_prefix="Failed to create MySQL checkpoint")

        return PendingRollbackSnapshot(
            snapshot_id=snapshot_id,
            dialect="mysql",
            database_path=f"{target.database}@{host}:{port}",
            snapshot_path=snapshot_path,
            created_at=created_at,
            target=target,
        )

    def commit(self, pending: PendingRollbackSnapshot, source_sql: Optional[str] = None) -> str:
        self._snapshots[pending.snapshot_id] = RollbackSnapshot(
            snapshot_id=pending.snapshot_id,
            dialect=pending.dialect,
            database_path=pending.database_path,
            snapshot_path=pending.snapshot_path,
            created_at=pending.created_at,
            target=pending.target,
            source_sql=source_sql,
        )
        self._persist_index()
        return pending.snapshot_id

    def discard(self, pending: PendingRollbackSnapshot) -> None:
        self._safe_remove(pending.snapshot_path)

    def list_snapshots(self) -> List[RollbackSnapshot]:
        return sorted(self._snapshots.values(), key=lambda item: item.created_at, reverse=True)

    def rollback(self, snapshot_id: str) -> RollbackSnapshot:
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot is None:
            raise ValueError(f"Unknown rollback snapshot: {snapshot_id}")

        if not os.path.exists(snapshot.snapshot_path):
            raise ValueError(f"Snapshot file is missing for rollback id: {snapshot_id}")

        if snapshot.dialect == "sqlite":
            os.makedirs(os.path.dirname(snapshot.database_path), exist_ok=True)
            shutil.copy2(snapshot.snapshot_path, snapshot.database_path)
            return snapshot
        if snapshot.dialect in {"postgres", "postgresql"}:
            self._restore_postgresql(snapshot)
            return snapshot
        if snapshot.dialect == "mysql":
            self._restore_mysql(snapshot)
            return snapshot

        raise ValueError(f"Rollback is not supported for dialect: {snapshot.dialect}")

    def _restore_postgresql(self, snapshot: RollbackSnapshot) -> None:
        if which("psql") is None:
            raise RuntimeError("PostgreSQL restore requires psql to be installed in the backend runtime.")
        target = snapshot.target
        host = self._resolve_host_for_runtime(target.host)
        port = str(target.port or 5432)
        user = target.username or "postgres"
        cmd = [
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-h",
            host,
            "-p",
            port,
            "-U",
            user,
            "-d",
            target.database,
            "-f",
            snapshot.snapshot_path,
        ]
        env = os.environ.copy()
        if target.password:
            env["PGPASSWORD"] = target.password
        self._run_command(cmd, env=env, error_prefix="Failed to apply PostgreSQL checkpoint")

    def _restore_mysql(self, snapshot: RollbackSnapshot) -> None:
        if which("mysql") is None:
            raise RuntimeError("MySQL restore requires mysql client to be installed in the backend runtime.")
        target = snapshot.target
        host = self._resolve_host_for_runtime(target.host)
        port = str(target.port or 3306)
        user = target.username or "root"
        cmd = [
            "mysql",
            "-h",
            host,
            "-P",
            port,
            "-u",
            user,
            target.database,
        ]
        env = os.environ.copy()
        if target.password:
            env["MYSQL_PWD"] = target.password
        with open(snapshot.snapshot_path, "rb") as dump_file:
            self._run_command(cmd, stdin=dump_file, env=env, error_prefix="Failed to apply MySQL checkpoint")

    @staticmethod
    def _run_command(
        command: List[str],
        *,
        stdin=None,
        env: Optional[Dict[str, str]] = None,
        error_prefix: str,
    ) -> None:
        try:
            subprocess.run(
                command,
                stdin=stdin,
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"{error_prefix}: command not found: {command[0]}") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            stdout = (exc.stdout or "").strip()
            detail = stderr or stdout or "unknown error"
            raise RuntimeError(f"{error_prefix}: {detail}") from exc

    @staticmethod
    def _sanitize_postgresql_dump(dump_path: str) -> None:
        """
        Remove settings that may be emitted by newer pg_dump versions but are not
        recognized by older PostgreSQL servers during restore.
        """
        try:
            with open(dump_path, "r", encoding="utf-8") as handle:
                lines = handle.readlines()
        except FileNotFoundError:
            return

        filtered = []
        for line in lines:
            if line.startswith("SET transaction_timeout ="):
                continue
            filtered.append(line)

        if filtered != lines:
            with open(dump_path, "w", encoding="utf-8") as handle:
                handle.writelines(filtered)

    def delete_snapshot(self, snapshot_id: str) -> None:
        snapshot = self._snapshots.pop(snapshot_id, None)
        if snapshot is None:
            return
        self._safe_remove(snapshot.snapshot_path)
        self._persist_index()

    def _load_index(self) -> None:
        try:
            with open(self._index_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            return
        except Exception:
            return

        raw_snapshots = payload.get("snapshots") if isinstance(payload, dict) else None
        if not isinstance(raw_snapshots, list):
            return

        loaded: Dict[str, RollbackSnapshot] = {}
        for item in raw_snapshots:
            if not isinstance(item, dict):
                continue
            snapshot = self._snapshot_from_dict(item)
            if snapshot is None:
                continue
            if not os.path.exists(snapshot.snapshot_path):
                continue
            loaded[snapshot.snapshot_id] = snapshot

        self._snapshots = loaded

    def _persist_index(self) -> None:
        snapshots = [self._snapshot_to_dict(item) for item in self._snapshots.values()]
        payload = {"snapshots": snapshots}

        temp_path = self._index_path + ".tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
            os.replace(temp_path, self._index_path)
        except Exception:
            self._safe_remove(temp_path)

    @staticmethod
    def _snapshot_to_dict(snapshot: RollbackSnapshot) -> Dict[str, object]:
        return {
            "snapshot_id": snapshot.snapshot_id,
            "dialect": snapshot.dialect,
            "database_path": snapshot.database_path,
            "snapshot_path": snapshot.snapshot_path,
            "created_at": snapshot.created_at,
            "source_sql": snapshot.source_sql,
            "target": {
                "dialect": snapshot.target.dialect,
                "database": snapshot.target.database,
                "username": snapshot.target.username,
                "password": snapshot.target.password,
                "host": snapshot.target.host,
                "port": snapshot.target.port,
                "schema_name": snapshot.target.schema_name,
                "connection_string": snapshot.target.connection_string,
                "options": snapshot.target.options,
            },
        }

    @staticmethod
    def _snapshot_from_dict(item: Dict[str, object]) -> Optional[RollbackSnapshot]:
        target_raw = item.get("target")
        if not isinstance(target_raw, dict):
            return None

        snapshot_id = item.get("snapshot_id")
        dialect = item.get("dialect")
        database_path = item.get("database_path")
        snapshot_path = item.get("snapshot_path")
        created_at = item.get("created_at")

        if not all(isinstance(v, str) and v for v in [snapshot_id, dialect, database_path, snapshot_path, created_at]):
            return None

        target = DatabaseTarget(
            dialect=str(target_raw.get("dialect") or ""),
            database=str(target_raw.get("database") or ""),
            username=target_raw.get("username") if isinstance(target_raw.get("username"), str) else None,
            password=target_raw.get("password") if isinstance(target_raw.get("password"), str) else None,
            host=target_raw.get("host") if isinstance(target_raw.get("host"), str) else None,
            port=target_raw.get("port") if isinstance(target_raw.get("port"), int) else None,
            schema_name=target_raw.get("schema_name") if isinstance(target_raw.get("schema_name"), str) else None,
            connection_string=target_raw.get("connection_string") if isinstance(target_raw.get("connection_string"), str) else None,
            options=target_raw.get("options") if isinstance(target_raw.get("options"), dict) else {},
        )

        return RollbackSnapshot(
            snapshot_id=snapshot_id,
            dialect=dialect,
            database_path=database_path,
            snapshot_path=snapshot_path,
            created_at=created_at,
            target=target,
            source_sql=item.get("source_sql") if isinstance(item.get("source_sql"), str) else None,
        )

    @staticmethod
    def _safe_remove(path: str) -> None:
        try:
            os.remove(path)
        except FileNotFoundError:
            return

    @staticmethod
    def _resolve_host_for_runtime(host: Optional[str]) -> str:
        """
        Map localhost to host.docker.internal when running inside a container.
        This mirrors adapter runtime host resolution behavior.
        """
        value = (host or "localhost").strip()
        if value in {"localhost", "127.0.0.1", "::1"} and os.path.exists("/.dockerenv"):
            return "host.docker.internal"
        return value
