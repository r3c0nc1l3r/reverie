"""Durable coordination state shared by Reverie browser workers.

The append-only ``trail.jsonl`` remains the detailed run evidence.  This store is the
small, transactional index used to coordinate logical testing sessions, workers,
requests, commands, and retention across processes.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .project import coordination_path

MAX_TEXT = 65_536
MAX_JSON = 1_048_576
MAX_PAGE = 1_000
PURPOSES = {"smoke", "regression", "exploratory"}
LIFETIMES = {"temporary", "retained", "pinned"}
ACTIVE_STATES = {"active", "new", "pending", "queued", "running", "starting"}
SUCCESS_RESULTS = {"pass", "passed", "success", "succeeded"}
TRIAGE_RESULTS = {"fail", "failed", "blocked", "incomplete", "error", "errored", "crashed"}


class CoordinationError(ValueError):
    """Base class for coordination-store failures callers may handle."""


class CoordinationConflict(CoordinationError):
    """An optimistic-concurrency or idempotency check failed."""


class CoordinationNotFound(CoordinationError):
    """The requested session, run, request, worker, or command does not exist."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _time(value) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _text(value, name: str, *, allow_empty: bool = False, maximum: int = MAX_TEXT) -> str:
    value = str(value)
    if not allow_empty and not value:
        raise ValueError(f"{name} must not be empty")
    if len(value) > maximum:
        raise ValueError(f"{name} is too long")
    return value


def _dump(value, name: str = "value", *, canonical: bool = False) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=canonical, separators=(",", ":"), default=str)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} is not JSON serializable") from exc
    if len(encoded.encode("utf-8")) > MAX_JSON:
        raise ValueError(f"{name} is too large")
    return encoded


def _load(value, default=None):
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class CoordinationStore:
    """SQLite-backed coordination for one project.

    A new connection is used for each operation so one instance can safely be shared
    by threads and independent processes. WAL mode permits readers during writes;
    write methods use ``BEGIN IMMEDIATE`` to make compare-and-swap decisions atomic.
    """

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.path = coordination_path(self.root)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self):
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    environment TEXT NOT NULL DEFAULT '',
                    source_revision TEXT NOT NULL DEFAULT '',
                    purpose TEXT NOT NULL,
                    lifetime TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'active',
                    version INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    browser_session TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    lifetime TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    result TEXT NOT NULL DEFAULT 'running',
                    active INTEGER NOT NULL DEFAULT 1,
                    artifact_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    triaged_at TEXT,
                    expired_at TEXT,
                    purged_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS runs_session_idx ON runs(session_id, created_at);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    seq INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    run_id TEXT,
                    worker_id TEXT,
                    timestamp TEXT NOT NULL,
                    UNIQUE(session_id, seq)
                );
                CREATE INDEX IF NOT EXISTS events_session_seq_idx ON events(session_id, seq);
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    run_id TEXT,
                    need TEXT NOT NULL,
                    assigned_to TEXT NOT NULL,
                    owner TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    resolved_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS requests_session_idx ON requests(session_id, created_at);
                CREATE TABLE IF NOT EXISTS workers (
                    worker_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    run_id TEXT,
                    owner TEXT NOT NULL,
                    epoch INTEGER NOT NULL,
                    incarnation TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS workers_session_idx ON workers(session_id, worker_id);
                CREATE TABLE IF NOT EXISTS commands (
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    operation_id TEXT NOT NULL,
                    command_json TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    command_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error_json TEXT,
                    worker_id TEXT,
                    owner TEXT,
                    epoch INTEGER,
                    incarnation TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(session_id, operation_id)
                );
                """
            )

    @contextmanager
    def _write(self):
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _session_row(self, connection, session_id):
        row = connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise CoordinationNotFound(f"session {session_id!r} does not exist")
        return row

    def _check_revision(self, row, expected_revision):
        if expected_revision is not None and row["version"] != int(expected_revision):
            raise CoordinationConflict(
                f"session revision changed (expected {expected_revision}, current {row['version']})"
            )

    def _bump(self, connection, session_id, timestamp=None):
        timestamp = timestamp or _now()
        changed = connection.execute(
            "UPDATE sessions SET version = version + 1, updated_at = ? WHERE id = ?", (timestamp, session_id)
        ).rowcount
        if not changed:
            raise CoordinationNotFound(f"session {session_id!r} does not exist")
        return connection.execute("SELECT version FROM sessions WHERE id = ?", (session_id,)).fetchone()[0]

    def _append_event_in_tx(self, connection, session_id, event_type, payload, *, run_id=None, worker_id=None,
                            include_session=False):
        timestamp = _now()
        seq = self._bump(connection, session_id, timestamp)
        if include_session:
            # Capture after the bump so replay sees exactly the committed session revision.
            payload = {**payload, "session": self._session_dict(self._session_row(connection, session_id))}
        cursor = connection.execute(
            """INSERT INTO events(session_id, seq, type, payload_json, run_id, worker_id, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, seq, _text(event_type, "event_type", maximum=255), _dump(payload, "payload"),
             run_id, worker_id, timestamp),
        )
        return {
            "id": cursor.lastrowid,
            "seq": seq,
            "session_id": session_id,
            "type": event_type,
            "payload": payload,
            "run_id": run_id,
            "worker_id": worker_id,
            "timestamp": timestamp,
        }

    @staticmethod
    def _session_dict(row):
        metadata = _load(row["metadata_json"], {})
        return {
            **metadata,
            "id": row["id"],
            "title": row["title"],
            "environment": row["environment"],
            "source_revision": row["source_revision"],
            "purpose": row["purpose"],
            "lifetime": row["lifetime"],
            "temporary": row["lifetime"] == "temporary",
            "state": row["state"],
            "revision": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "metadata": metadata,
        }

    @staticmethod
    def _run_dict(row):
        metadata = _load(row["metadata_json"], {})
        return {
            **metadata,
            "id": row["id"],
            "run_id": row["id"],
            "session_id": row["session_id"],
            "browser_session": row["browser_session"],
            "purpose": row["purpose"],
            "lifetime": row["lifetime"],
            "status": row["status"],
            "state": row["status"],
            "result": row["result"],
            "active": bool(row["active"]),
            "artifact_path": row["artifact_path"],
            "artifact_dir": row["artifact_path"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
            "triaged_at": row["triaged_at"],
            "expired_at": row["expired_at"],
            "purged_at": row["purged_at"],
            "metadata": metadata,
        }

    @staticmethod
    def _request_dict(row):
        metadata = _load(row["metadata_json"], {})
        return {
            **metadata,
            "id": row["id"],
            "request_id": row["id"],
            "session_id": row["session_id"],
            "run_id": row["run_id"],
            "need": row["need"],
            "assigned_to": row["assigned_to"],
            "owner": row["owner"],
            "status": row["status"],
            "result": _load(row["result_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "resolved_at": row["resolved_at"],
            "metadata": metadata,
        }

    @staticmethod
    def _worker_dict(row):
        metadata = _load(row["metadata_json"], {})
        return {
            **metadata,
            "worker_id": row["worker_id"],
            "session_id": row["session_id"],
            "run_id": row["run_id"],
            "owner": row["owner"],
            "epoch": row["epoch"],
            "incarnation": row["incarnation"],
            "state": row["state"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "metadata": metadata,
        }

    @staticmethod
    def _command_dict(row, status=None):
        return {
            "session_id": row["session_id"],
            "operation_id": row["operation_id"],
            "command": _load(row["command_json"]),
            "arguments": _load(row["arguments_json"]),
            "digest": row["command_digest"],
            "status": status or row["status"],
            "result": _load(row["result_json"]),
            "error": _load(row["error_json"]),
            "worker_id": row["worker_id"],
            "owner": row["owner"],
            "epoch": row["epoch"],
            "incarnation": row["incarnation"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _command_event_payload(row):
        """Public lifecycle events never carry command arguments, results, or errors."""
        command = _load(row["command_json"])
        name = command if isinstance(command, str) else None
        if isinstance(command, dict):
            name = command.get("name", command.get("command", command.get("op")))
        return {"command": {"operation_id": row["operation_id"],
                            "name": name if isinstance(name, str) else None, "status": row["status"]}}

    def create_session(self, title, environment="", revision="", purpose="smoke", temporary=True, session_id=None):
        session_id = _text(session_id or uuid.uuid4().hex, "session_id", maximum=255)
        title = _text(title, "title")
        environment = _text(environment, "environment", allow_empty=True)
        source_revision = _text(revision, "revision", allow_empty=True)
        if purpose not in PURPOSES:
            raise ValueError(f"purpose must be one of {sorted(PURPOSES)}")
        lifetime = "temporary" if temporary else "retained"
        timestamp = _now()
        try:
            with self._write() as connection:
                connection.execute(
                    """INSERT INTO sessions(id, title, environment, source_revision, purpose, lifetime,
                                             created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (session_id, title, environment, source_revision, purpose, lifetime, timestamp, timestamp),
                )
                row = self._session_row(connection, session_id)
        except sqlite3.IntegrityError as exc:
            raise CoordinationConflict(f"session {session_id!r} already exists") from exc
        return self._session_dict(row)

    def get_session(self, session_id):
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return self._session_dict(row) if row else None

    def list_sessions(self, include_archived=False):
        query = "SELECT * FROM sessions"
        params = ()
        if not include_archived:
            query += " WHERE state != ?"
            params = ("archived",)
        query += " ORDER BY created_at DESC, id LIMIT ?"
        with self._connect() as connection:
            rows = connection.execute(query, (*params, MAX_PAGE)).fetchall()
        return [self._session_dict(row) for row in rows]

    def update_session(self, session_id, **fields):
        allowed = {"title", "environment", "purpose", "lifetime", "state", "source_revision"}
        if "temporary" in fields:
            fields["lifetime"] = "temporary" if fields.pop("temporary") else "retained"
        if "archived" in fields:
            fields["state"] = "archived" if fields.pop("archived") else "active"
        if "code_revision" in fields:
            fields["source_revision"] = fields.pop("code_revision")
        # A string revision is an alias for the tested source revision. Integer revisions are read-only.
        if "revision" in fields:
            value = fields.pop("revision")
            if not isinstance(value, str):
                raise ValueError("session revision is read-only")
            fields["source_revision"] = value
        metadata_update = fields.pop("metadata", {}) or {}
        extras = {key: fields.pop(key) for key in list(fields) if key not in allowed}
        if not isinstance(metadata_update, dict):
            raise ValueError("metadata must be an object")
        metadata_update = {**metadata_update, **extras}
        if fields.get("purpose") not in (None, *PURPOSES):
            raise ValueError(f"purpose must be one of {sorted(PURPOSES)}")
        if fields.get("lifetime") not in (None, *LIFETIMES):
            raise ValueError(f"lifetime must be one of {sorted(LIFETIMES)}")
        for key, value in fields.items():
            may_be_empty = key in {"environment", "source_revision"}
            fields[key] = _text(value, key, allow_empty=may_be_empty)
        with self._write() as connection:
            row = self._session_row(connection, session_id)
            metadata = {**_load(row["metadata_json"], {}), **metadata_update}
            assignments, values = [], []
            for key, value in fields.items():
                assignments.append(f"{key} = ?")
                values.append(value)
            if metadata_update:
                assignments.append("metadata_json = ?")
                values.append(_dump(metadata, "metadata"))
            if assignments:
                timestamp = _now()
                assignments.append("updated_at = ?")
                values.append(timestamp)
                connection.execute(f"UPDATE sessions SET {', '.join(assignments)} WHERE id = ?", (*values, session_id))
                self._append_event_in_tx(connection, session_id, "session.updated", {}, include_session=True)
            row = self._session_row(connection, session_id)
        return self._session_dict(row)

    def register_run(self, session_id, run_id, browser_session, **metadata):
        run_id = _text(run_id, "run_id", maximum=255)
        browser_session = _text(browser_session, "browser_session", maximum=255)
        nested = metadata.pop("metadata", {}) or {}
        if not isinstance(nested, dict):
            raise ValueError("metadata must be an object")
        metadata = {**nested, **metadata}
        timestamp = _now()
        with self._write() as connection:
            session = self._session_row(connection, session_id)
            existing = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if existing:
                if existing["session_id"] != session_id or existing["browser_session"] != browser_session:
                    raise CoordinationConflict(f"run {run_id!r} is already registered differently")
                return self._run_dict(existing)
            purpose = metadata.pop("purpose", session["purpose"])
            lifetime = metadata.pop("lifetime", session["lifetime"])
            if purpose not in PURPOSES or lifetime not in LIFETIMES:
                raise ValueError("invalid run purpose or lifetime")
            status = str(metadata.pop("status", metadata.pop("state", "active")))
            result = str(metadata.pop("result", metadata.pop("verdict", "running")))
            if result == "running" and status.lower() in SUCCESS_RESULTS | TRIAGE_RESULTS:
                result = status
            artifact_path = metadata.pop("artifact_path", metadata.pop("artifact_dir", None))
            completed_at = metadata.pop("completed_at", None)
            triaged_at = metadata.pop("triaged_at", None)
            active_value = metadata.pop("active", None)
            terminal = result.lower() in SUCCESS_RESULTS | TRIAGE_RESULTS or status.lower() not in ACTIVE_STATES
            active = bool(active_value) if active_value is not None else not terminal
            if terminal and completed_at is None:
                completed_at = timestamp
            if terminal and status.lower() in ACTIVE_STATES:
                status = "completed"
            connection.execute(
                """INSERT INTO runs(id, session_id, browser_session, purpose, lifetime, status, result, active,
                                    artifact_path, created_at, updated_at, completed_at, triaged_at, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, session_id, browser_session, purpose, lifetime, status, result, int(active),
                 str(artifact_path) if artifact_path is not None else None, timestamp, timestamp, completed_at,
                 triaged_at, _dump(metadata, "metadata")),
            )
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            self._append_event_in_tx(connection, session_id, "run.registered", {"run": self._run_dict(row)},
                                     run_id=run_id, include_session=True)
        return self._run_dict(row)

    def update_run(self, run_id, **fields):
        aliases = {"state": "status", "verdict": "result", "artifact_dir": "artifact_path"}
        for old, new in aliases.items():
            if old in fields and new not in fields:
                fields[new] = fields.pop(old)
        allowed = {
            "browser_session", "purpose", "lifetime", "status", "result", "active", "artifact_path",
            "completed_at", "triaged_at", "expired_at", "purged_at",
        }
        nested = fields.pop("metadata", {}) or {}
        if not isinstance(nested, dict):
            raise ValueError("metadata must be an object")
        extras = {key: fields.pop(key) for key in list(fields) if key not in allowed}
        metadata_update = {**nested, **extras}
        if fields.get("purpose") not in (None, *PURPOSES):
            raise ValueError(f"purpose must be one of {sorted(PURPOSES)}")
        if fields.get("lifetime") not in (None, *LIFETIMES):
            raise ValueError(f"lifetime must be one of {sorted(LIFETIMES)}")
        timestamp = _now()
        with self._write() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise CoordinationNotFound(f"run {run_id!r} does not exist")
            if row["expired_at"] and fields.get("active"):
                raise CoordinationConflict("expired evidence cannot be made active")
            if "result" in fields and str(fields["result"]).lower() in SUCCESS_RESULTS | TRIAGE_RESULTS:
                fields.setdefault("active", False)
                fields.setdefault("completed_at", timestamp)
                fields.setdefault("status", "completed")
            if ("status" in fields and "result" not in fields
                    and str(fields["status"]).lower() in SUCCESS_RESULTS | TRIAGE_RESULTS):
                fields["result"] = fields["status"]
            if "status" in fields and str(fields["status"]).lower() not in ACTIVE_STATES:
                fields.setdefault("active", False)
                fields.setdefault("completed_at", timestamp)
            metadata = {**_load(row["metadata_json"], {}), **metadata_update}
            assignments, values = [], []
            for key, value in fields.items():
                if key == "active":
                    value = int(bool(value))
                assignments.append(f"{key} = ?")
                values.append(str(value) if isinstance(value, Path) else value)
            if metadata_update:
                assignments.append("metadata_json = ?")
                values.append(_dump(metadata, "metadata"))
            if assignments:
                assignments.append("updated_at = ?")
                values.append(timestamp)
                connection.execute(f"UPDATE runs SET {', '.join(assignments)} WHERE id = ?", (*values, run_id))
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if assignments:
                self._append_event_in_tx(connection, row["session_id"], "run.updated",
                                         {"run": self._run_dict(row)}, run_id=run_id, include_session=True)
        return self._run_dict(row)

    def list_runs(self, session_id=None, include_expired=False):
        clauses, params = [], []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if not include_expired:
            clauses.append("expired_at IS NULL")
        query = "SELECT * FROM runs"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at, id LIMIT ?"
        with self._connect() as connection:
            rows = connection.execute(query, (*params, MAX_PAGE)).fetchall()
        return [self._run_dict(row) for row in rows]

    def append_event(self, session_id, event_type, payload, run_id=None, worker_id=None):
        with self._write() as connection:
            self._session_row(connection, session_id)
            return self._append_event_in_tx(
                connection, session_id, event_type, payload, run_id=run_id, worker_id=worker_id
            )

    def events(self, session_id, after=0, limit=200):
        after = max(0, int(after))
        limit = min(MAX_PAGE, max(1, int(limit)))
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            session = self._session_row(connection, session_id)
            rows = connection.execute(
                "SELECT * FROM events WHERE session_id = ? AND seq > ? ORDER BY seq LIMIT ?",
                (session_id, after, limit + 1),
            ).fetchall()
            watermark = connection.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM events WHERE session_id = ?", (session_id,)
            ).fetchone()[0]
            connection.commit()
        finally:
            connection.close()
        truncated = len(rows) > limit
        rows = rows[:limit]
        items = [
            {
                "id": row["id"], "seq": row["seq"], "session_id": row["session_id"], "type": row["type"],
                "payload": _load(row["payload_json"]), "run_id": row["run_id"], "worker_id": row["worker_id"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]
        cursor = rows[-1]["seq"] if truncated and rows else max(after, watermark)
        return {"events": items, "cursor": cursor, "revision": session["version"],
                "watermark": watermark, "truncated": truncated}

    def snapshot(self, session_id, run_offset=0, run_limit=200):
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            session = self._session_row(connection, session_id)
            run_offset, run_limit = max(0, int(run_offset)), min(MAX_PAGE, max(1, int(run_limit)))
            run_total = connection.execute("SELECT count(*) FROM runs WHERE session_id = ?", (session_id,)).fetchone()[0]
            runs = connection.execute(
                "SELECT * FROM runs WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (session_id, run_limit, run_offset)
            ).fetchall()
            requests = connection.execute(
                "SELECT * FROM requests WHERE session_id = ? ORDER BY (status = 'resolved'), created_at, id LIMIT ?", (session_id, MAX_PAGE)
            ).fetchall()
            workers = connection.execute(
                "SELECT * FROM workers WHERE session_id = ? ORDER BY worker_id LIMIT ?", (session_id, MAX_PAGE)
            ).fetchall()
            cursor = connection.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM events WHERE session_id = ?", (session_id,)
            ).fetchone()[0]
            connection.commit()
        finally:
            connection.close()
        return {
            "session": self._session_dict(session),
            "runs": [self._run_dict(row) for row in runs],
            "run_total": run_total, "run_offset": run_offset,
            "runs_next": run_offset + len(runs) if run_offset + len(runs) < run_total else None,
            "requests": [self._request_dict(row) for row in requests],
            "workers": [self._worker_dict(row) for row in workers],
            "revision": session["version"], "cursor": cursor,
        }

    def create_request(self, session_id, need, assigned_to="coordinator", run_id=None, request_id=None, **metadata):
        request_id = _text(request_id or f"req-{uuid.uuid4().hex}", "request_id", maximum=255)
        need = _text(need, "need")
        assigned_to = _text(assigned_to, "assigned_to", maximum=255)
        nested = metadata.pop("metadata", {}) or {}
        if not isinstance(nested, dict):
            raise ValueError("metadata must be an object")
        timestamp = _now()
        try:
            with self._write() as connection:
                self._session_row(connection, session_id)
                if run_id is not None:
                    run = connection.execute("SELECT session_id FROM runs WHERE id = ?", (run_id,)).fetchone()
                    if run is None or run["session_id"] != session_id:
                        raise CoordinationConflict("request run must belong to the same testing session")
                connection.execute(
                    """INSERT INTO requests(id, session_id, run_id, need, assigned_to, created_at, updated_at,
                                            metadata_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (request_id, session_id, run_id, need, assigned_to, timestamp, timestamp,
                     _dump({**nested, **metadata}, "metadata")),
                )
                row = connection.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
                self._append_event_in_tx(connection, session_id, "request.created",
                                         {"request": self._request_dict(row)}, run_id=run_id, include_session=True)
        except sqlite3.IntegrityError as exc:
            raise CoordinationConflict(f"request {request_id!r} already exists") from exc
        return self._request_dict(row)

    def claim_request(self, request_id, owner, expected_revision=None):
        owner = _text(owner, "owner", maximum=255)
        timestamp = _now()
        with self._write() as connection:
            row = connection.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
            if row is None:
                raise CoordinationNotFound(f"request {request_id!r} does not exist")
            session = self._session_row(connection, row["session_id"])
            self._check_revision(session, expected_revision)
            if row["status"] != "pending":
                raise CoordinationConflict(f"request is already {row['status']}")
            changed = connection.execute(
                "UPDATE requests SET status = 'claimed', owner = ?, updated_at = ? WHERE id = ? AND status = 'pending'",
                (owner, timestamp, request_id),
            ).rowcount
            if changed != 1:
                raise CoordinationConflict("request was claimed concurrently")
            row = connection.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
            self._append_event_in_tx(connection, row["session_id"], "request.claimed",
                                     {"request": self._request_dict(row)}, run_id=row["run_id"], include_session=True)
        return self._request_dict(row)

    def resolve_request(self, request_id, result, owner=None, expected_revision=None):
        timestamp = _now()
        encoded = _dump(result, "result")
        with self._write() as connection:
            row = connection.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
            if row is None:
                raise CoordinationNotFound(f"request {request_id!r} does not exist")
            session = self._session_row(connection, row["session_id"])
            self._check_revision(session, expected_revision)
            if row["status"] == "resolved":
                raise CoordinationConflict("request is already resolved")
            if owner is not None and row["owner"] not in (None, owner):
                raise CoordinationConflict(f"request is owned by {row['owner']!r}")
            effective_owner = owner or row["owner"] or row["assigned_to"]
            changed = connection.execute(
                """UPDATE requests SET status = 'resolved', owner = ?, result_json = ?, updated_at = ?, resolved_at = ?
                   WHERE id = ? AND status != 'resolved'""",
                (effective_owner, encoded, timestamp, timestamp, request_id),
            ).rowcount
            if changed != 1:
                raise CoordinationConflict("request was resolved concurrently")
            row = connection.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
            self._append_event_in_tx(connection, row["session_id"], "request.resolved",
                                     {"request": self._request_dict(row)}, run_id=row["run_id"], include_session=True)
        return self._request_dict(row)

    def list_requests(self, session_id):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM requests WHERE session_id = ? ORDER BY (status = 'resolved'), created_at, id LIMIT ?", (session_id, MAX_PAGE)
            ).fetchall()
        return [self._request_dict(row) for row in rows]

    def register_worker(self, session_id, worker_id, run_id, incarnation, metadata=None):
        worker_id = _text(worker_id, "worker_id", maximum=255)
        incarnation = _text(incarnation, "incarnation", maximum=255)
        metadata = metadata or {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        timestamp = _now()
        with self._write() as connection:
            self._session_row(connection, session_id)
            row = connection.execute("SELECT * FROM workers WHERE worker_id = ?", (worker_id,)).fetchone()
            if row and row["incarnation"] == incarnation:
                if row["session_id"] != session_id or row["run_id"] != run_id:
                    raise CoordinationConflict("worker incarnation is already bound to another run")
                return self._worker_dict(row)
            if row:
                epoch = row["epoch"] + 1
                connection.execute(
                    """UPDATE workers SET session_id = ?, run_id = ?, owner = 'coordinator', epoch = ?,
                                          incarnation = ?, state = 'active', updated_at = ?, metadata_json = ?
                       WHERE worker_id = ?""",
                    (session_id, run_id, epoch, incarnation, timestamp, _dump(metadata, "metadata"), worker_id),
                )
                event_type = "worker.reincarnated"
            else:
                epoch = 0
                connection.execute(
                    """INSERT INTO workers(worker_id, session_id, run_id, owner, epoch, incarnation, state,
                                           created_at, updated_at, metadata_json)
                       VALUES (?, ?, ?, 'coordinator', 0, ?, 'active', ?, ?, ?)""",
                    (worker_id, session_id, run_id, incarnation, timestamp, timestamp, _dump(metadata, "metadata")),
                )
                event_type = "worker.registered"
            self._append_event_in_tx(
                connection, session_id, event_type,
                {"worker_id": worker_id, "run_id": run_id, "owner": "coordinator", "epoch": epoch,
                 "incarnation": incarnation},
                run_id=run_id, worker_id=worker_id,
            )
            row = connection.execute("SELECT * FROM workers WHERE worker_id = ?", (worker_id,)).fetchone()
        return self._worker_dict(row)

    def worker_control(self, worker_id):
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM workers WHERE worker_id = ?", (worker_id,)).fetchone()
        if row is None:
            raise CoordinationNotFound(f"worker {worker_id!r} does not exist")
        return self._worker_dict(row)

    def bind_worker_run(self, worker_id, run_id):
        """Start another run in the same browser incarnation, invalidating old commands."""
        with self._write() as connection:
            worker = connection.execute("SELECT * FROM workers WHERE worker_id = ?", (worker_id,)).fetchone()
            if worker is None:
                raise CoordinationNotFound(f"worker {worker_id!r} does not exist")
            run = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                raise CoordinationNotFound(f"run {run_id!r} does not exist")
            if run["session_id"] != worker["session_id"]:
                raise CoordinationConflict("worker and run must belong to the same session")
            if worker["run_id"] == run_id:
                return self._worker_dict(worker)
            timestamp = _now()
            connection.execute(
                "UPDATE workers SET run_id = ?, epoch = epoch + 1, updated_at = ? WHERE worker_id = ?",
                (run_id, timestamp, worker_id),
            )
            row = connection.execute("SELECT * FROM workers WHERE worker_id = ?", (worker_id,)).fetchone()
            payload = {**self._worker_dict(row), "previous_run_id": worker["run_id"]}
            self._append_event_in_tx(connection, row["session_id"], "worker.run_bound", payload,
                                     run_id=run_id, worker_id=worker_id, include_session=True)
        return self._worker_dict(row)

    def transfer_control(self, worker_id, actor, expected_epoch, new_owner, override=False):
        actor = _text(actor, "actor", maximum=255)
        new_owner = _text(new_owner, "new_owner", maximum=255)
        with self._write() as connection:
            row = connection.execute("SELECT * FROM workers WHERE worker_id = ?", (worker_id,)).fetchone()
            if row is None:
                raise CoordinationNotFound(f"worker {worker_id!r} does not exist")
            if row["epoch"] != int(expected_epoch):
                raise CoordinationConflict(f"worker epoch changed (expected {expected_epoch}, current {row['epoch']})")
            if not override and row["owner"] != actor:
                raise CoordinationConflict(f"worker is owned by {row['owner']!r}")
            epoch = row["epoch"] + 1
            timestamp = _now()
            changed = connection.execute(
                """UPDATE workers SET owner = ?, epoch = ?, updated_at = ?
                   WHERE worker_id = ? AND epoch = ?""",
                (new_owner, epoch, timestamp, worker_id, row["epoch"]),
            ).rowcount
            if changed != 1:
                raise CoordinationConflict("worker control changed concurrently")
            self._append_event_in_tx(
                connection, row["session_id"], "worker.control_transferred",
                {"worker_id": worker_id, "actor": actor, "previous_owner": row["owner"], "owner": new_owner,
                 "epoch": epoch, "incarnation": row["incarnation"], "override": bool(override)},
                run_id=row["run_id"], worker_id=worker_id,
            )
            row = connection.execute("SELECT * FROM workers WHERE worker_id = ?", (worker_id,)).fetchone()
        return self._worker_dict(row)

    def _validate_worker_binding(self, connection, worker_id, owner, epoch, incarnation):
        if worker_id is None:
            if any(value is not None for value in (owner, epoch, incarnation)):
                raise ValueError("worker_id is required with owner, epoch, or incarnation")
            return
        row = connection.execute("SELECT * FROM workers WHERE worker_id = ?", (worker_id,)).fetchone()
        if row is None:
            raise CoordinationNotFound(f"worker {worker_id!r} does not exist")
        if owner is not None and row["owner"] != owner:
            raise CoordinationConflict(f"worker is owned by {row['owner']!r}")
        if epoch is not None and row["epoch"] != int(epoch):
            raise CoordinationConflict(f"worker epoch changed (current {row['epoch']})")
        if incarnation is not None and row["incarnation"] != incarnation:
            raise CoordinationConflict("worker incarnation changed")
        return row

    def begin_command(self, session_id, operation_id, command, expected_revision=None, arguments=None,
                      worker_id=None, owner=None, epoch=None, incarnation=None):
        operation_id = _text(operation_id, "operation_id", maximum=255)
        command_json = _dump(command, "command", canonical=True)
        arguments_json = _dump(arguments, "arguments", canonical=True)
        digest = hashlib.sha256(f"{command_json}\n{arguments_json}".encode()).hexdigest()
        timestamp = _now()
        with self._write() as connection:
            session = self._session_row(connection, session_id)
            worker = self._validate_worker_binding(connection, worker_id, owner, epoch, incarnation)
            if worker is not None:
                if worker["session_id"] != session_id:
                    raise CoordinationConflict("worker and command must belong to the same session")
                owner, epoch, incarnation = worker["owner"], worker["epoch"], worker["incarnation"]
            existing = connection.execute(
                "SELECT * FROM commands WHERE session_id = ? AND operation_id = ?", (session_id, operation_id)
            ).fetchone()
            if existing:
                if existing["command_digest"] != digest:
                    raise CoordinationConflict("operation_id was already used for a different command")
                binding = (worker_id, owner, epoch, incarnation)
                recorded = tuple(existing[key] for key in ("worker_id", "owner", "epoch", "incarnation"))
                if binding != recorded:
                    raise CoordinationConflict("operation_id was already used with a different worker or control identity")
                return self._command_dict(existing)
            self._check_revision(session, expected_revision)
            connection.execute(
                """INSERT INTO commands(session_id, operation_id, command_json, arguments_json, command_digest,
                                        status, worker_id, owner, epoch, incarnation, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?)""",
                (session_id, operation_id, command_json, arguments_json, digest, worker_id, owner, epoch,
                 incarnation, timestamp, timestamp),
            )
            row = connection.execute(
                "SELECT * FROM commands WHERE session_id = ? AND operation_id = ?", (session_id, operation_id)
            ).fetchone()
            self._append_event_in_tx(connection, session_id, "command.started", self._command_event_payload(row),
                                     worker_id=worker_id, include_session=True)
        return self._command_dict(row, status="new")

    def finish_command(self, session_id, operation_id, result=None, error=None):
        timestamp = _now()
        with self._write() as connection:
            row = connection.execute(
                "SELECT * FROM commands WHERE session_id = ? AND operation_id = ?", (session_id, operation_id)
            ).fetchone()
            if row is None:
                raise CoordinationNotFound(f"command {operation_id!r} does not exist")
            if row["status"] in {"completed", "failed"}:
                return self._command_dict(row)
            status = "failed" if error is not None else "completed"
            connection.execute(
                """UPDATE commands SET status = ?, result_json = ?, error_json = ?, updated_at = ?
                   WHERE session_id = ? AND operation_id = ? AND status = 'running'""",
                (status, _dump(result, "result"), _dump(error, "error") if error is not None else None, timestamp,
                 session_id, operation_id),
            )
            row = connection.execute(
                "SELECT * FROM commands WHERE session_id = ? AND operation_id = ?", (session_id, operation_id)
            ).fetchone()
            self._append_event_in_tx(connection, session_id, "command.finished", self._command_event_payload(row),
                                     worker_id=row["worker_id"], include_session=True)
        return self._command_dict(row)

    def pin_run(self, run_id, pinned=True):
        return self.update_run(run_id, lifetime="pinned" if pinned else "retained")

    def triage_run(self, run_id, triage=None, **metadata):
        if triage is not None:
            metadata["triage"] = triage
        return self.update_run(run_id, triaged_at=_now(), **metadata)

    def _artifact_folder(self, row):
        runs_root = (self.root / ".reverie" / "runs").resolve()
        raw = row["artifact_path"] or str(runs_root / row["id"].partition("~")[0])
        path = Path(raw)
        if not path.is_absolute():
            path = self.root / path
        if path.name in {"trail.jsonl", "run.json"}:
            path = path.parent
        try:
            resolved = path.resolve()
            resolved.relative_to(runs_root)
        except (OSError, ValueError):
            return None
        if resolved.parent != runs_root or path.is_symlink():
            return None
        return resolved

    @staticmethod
    def _expiry(row, now):
        # An expired row without purged_at is a durable deletion intent. Recheck
        # its protections and allow a later explicit apply to finish that work.
        if row["purged_at"] or row["active"] or row["status"].lower() in ACTIVE_STATES:
            return None
        if row["lifetime"] != "temporary":
            return None
        metadata = _load(row["metadata_json"], {})
        findings = metadata.get("findings")
        untriaged = metadata.get("untriaged_findings") or metadata.get("has_findings")
        if isinstance(findings, list):
            untriaged = untriaged or any(
                not isinstance(finding, dict)
                or str(finding.get("status", "open")).lower() in {"", "open", "pending", "untriaged"}
                for finding in findings
            )
        try:
            untriaged = untriaged or int(metadata.get("finding_count", 0)) > 0
        except (TypeError, ValueError):
            untriaged = True
        if untriaged and not row["triaged_at"]:
            return None
        result = row["result"].lower()
        if result in SUCCESS_RESULTS:
            due = _time(row["completed_at"] or row["updated_at"]) + timedelta(hours=24)
            return (due, "successful temporary run") if due <= now else None
        if result in TRIAGE_RESULTS:
            if not row["triaged_at"]:
                return None
            due = _time(row["triaged_at"]) + timedelta(days=7)
            return (due, "triaged temporary run") if due <= now else None
        return None

    @staticmethod
    def _purge_folder(folder):
        purged = False
        frames = folder / "frames"
        if frames.is_symlink():
            frames.unlink()
            purged = True
        elif frames.is_dir():
            shutil.rmtree(frames)
            purged = True
        for name in ("trail.jsonl",):
            path = folder / name
            if path.is_file() or path.is_symlink():
                path.unlink()
                purged = True
        return purged

    def _expiry_candidates(self, rows, now):
        due = {row["id"]: self._expiry(row, now) for row in rows}
        folders = {row["id"]: self._artifact_folder(row) for row in rows}
        candidates = []
        for row in rows:
            expiry = due[row["id"]]
            folder = folders[row["id"]]
            if not expiry or folder is None:
                continue
            # A session folder can contain ~0, ~1, ... attempts. Preserve all of it if
            # any current attempt in that folder is not independently eligible.
            shared = [other for other in rows if not other["purged_at"] and folders[other["id"]] == folder]
            if any(due[other["id"]] is None for other in shared):
                continue
            item = self._run_dict(row)
            item.update(expires_due_at=expiry[0].isoformat(), expiry_reason=expiry[1], artifact_dir=str(folder),
                        purge_pending=bool(row["expired_at"]))
            candidates.append(item)
        return candidates

    def _purge_expired_folder(self, folder, now):
        """Revalidate under the writer lock; committed tombstones survive any failure."""
        with self._write() as connection:
            rows = connection.execute("SELECT * FROM runs ORDER BY created_at, id").fetchall()
            shared = [row for row in rows if not row["purged_at"] and self._artifact_folder(row) == folder]
            # A new run, pin, or finding may have arrived after tombstones were
            # committed. Every remaining attempt must still permit deletion.
            if not shared or any(not row["expired_at"] or self._expiry(row, now) is None for row in shared):
                return []
            self._purge_folder(folder)
            purged = []
            timestamp = now.isoformat()
            for row in shared:
                connection.execute("UPDATE runs SET purged_at = ?, updated_at = ? WHERE id = ?",
                                   (timestamp, timestamp, row["id"]))
                updated = connection.execute("SELECT * FROM runs WHERE id = ?", (row["id"],)).fetchone()
                self._append_event_in_tx(connection, row["session_id"], "run.purged",
                                         {"run": self._run_dict(updated)}, run_id=row["id"], include_session=True)
                expiry = self._expiry(row, now)
                purged.append({**self._run_dict(updated), "expires_due_at": expiry[0].isoformat(),
                               "expiry_reason": expiry[1], "artifact_dir": str(folder), "purge_pending": False})
        return purged

    def expire_runs(self, now=None, dry_run=True):
        now = _time(now)
        connection = self._connect()
        try:
            rows = connection.execute("SELECT * FROM runs ORDER BY created_at, id").fetchall()
        finally:
            connection.close()
        candidates = self._expiry_candidates(rows, now)
        if dry_run or not candidates:
            return candidates

        candidate_ids = {item["id"] for item in candidates}
        folders = set()
        timestamp = now.isoformat()
        with self._write() as connection:
            all_current = connection.execute("SELECT * FROM runs ORDER BY created_at, id").fetchall()
            for item in self._expiry_candidates(all_current, now):
                if item["id"] not in candidate_ids:
                    continue
                folders.add(Path(item["artifact_dir"]))
                if item["expired_at"]:
                    continue
                connection.execute(
                    "UPDATE runs SET expired_at = ?, updated_at = ? WHERE id = ?",
                    (timestamp, timestamp, item["id"]),
                )
                updated = connection.execute("SELECT * FROM runs WHERE id = ?", (item["id"],)).fetchone()
                self._append_event_in_tx(connection, item["session_id"], "run.expired",
                                         {"run": self._run_dict(updated)}, run_id=item["id"], include_session=True)
        # No filesystem deletion begins until the tombstone transaction commits.
        # Each purge holds the writer lock through revalidation and removal, so
        # another process cannot register a newly protected shared run mid-purge.
        purged = []
        for folder in sorted(folders):
            purged.extend(self._purge_expired_folder(folder, now))
        return purged
