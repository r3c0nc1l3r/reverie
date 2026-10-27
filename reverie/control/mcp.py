"""Small, dependency-free MCP stdio adapter for Reverie's control plane."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

from .. import __version__
from .cli import call
from .coordination import CoordinationStore
from .project import project_root

SUPPORTED_PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MAX_RESULT_TEXT = 24_000
ACTIONABLE_EVENTS = {
    "checkpoint", "error", "finding", "stalled", "pilot_end", "pause_requested",
    "request.created", "request.pending", "request.resolved",
    "run.blocked", "run.failed", "session.blocked", "worker.blocked", "worker.needs_input",
}
DROP_OUTPUT_KEYS = {"frame", "crop", "target_crop", "screenshot", "image", "image_data", "raw_frame"}


class ToolError(ValueError):
    pass


def object_schema(properties=None, required=()):
    return {
        "type": "object",
        "properties": properties or {},
        "required": list(required),
        "additionalProperties": False,
    }


STRING = {"type": "string", "maxLength": 65_536}
ID = {"type": "string", "minLength": 1, "maxLength": 255}
BOOL = {"type": "boolean"}
NONNEGATIVE = {"type": "integer", "minimum": 0}


COMMAND_SCHEMAS = {
    "status": object_schema(),
    "observe": object_schema({
        "settle": BOOL, "grep": {"type": "string", "maxLength": 500},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        "text_limit": {"type": "integer", "minimum": 0, "maximum": 4_000},
    }),
    "tabs": object_schema(),
    "checkpoints": object_schema(),
    "act": object_schema({
        "ref": ID, "label": {"type": "string", "maxLength": 1_000},
        "kind": {"type": "string", "maxLength": 50}, "text": {"type": "string", "maxLength": 20_000},
        "option": {"type": "string", "maxLength": 2_000}, "narration": {"type": "string", "maxLength": 2_000},
        "redact": BOOL, "hint": {"type": "string", "maxLength": 2_000},
        "value": {"type": ["string", "number", "boolean", "null"]},
    }),
    "expand": object_schema({"ref": ID}, ("ref",)),
    "visual_act": object_schema({
        "x": {"type": "number", "minimum": 0}, "y": {"type": "number", "minimum": 0},
        "text": {"type": "string", "maxLength": 20_000},
    }, ("x", "y")),
    "hover": object_schema({"ref": ID, "label": {"type": "string", "maxLength": 1_000}}),
    "press": object_schema({"key": {"type": "string", "enum": ["Enter", "Tab", "Escape"]}}, ("key",)),
    "goto": object_schema({"url": {"type": "string", "maxLength": 4_096}}, ("url",)),
    "open_tab": object_schema({"url": {"type": "string", "maxLength": 4_096}, "isolated": BOOL}, ("url",)),
    "close_tab": object_schema(),
    "switch": object_schema({"target": ID}, ("target",)),
    "check": object_schema({
        "text": {"type": "string", "maxLength": 4_000}, "absent": {"type": "string", "maxLength": 4_000},
        "url": {"type": "string", "maxLength": 4_096},
        "link": {"type": "string", "maxLength": 4_000}, "href": {"type": "string", "maxLength": 4_096},
    }),
    "goal": object_schema({"goal": {"type": "string", "minLength": 1, "maxLength": 8_000}}, ("goal",)),
    "plan": object_schema({
        "title": {"type": "string", "maxLength": 2_000},
        "steps": {"type": "array", "items": {"type": "string", "maxLength": 4_000}, "maxItems": 200},
        "source": {"type": "string", "maxLength": 4_096},
        "role": {"type": "string", "maxLength": 255},
        "purpose": {"type": "string", "enum": ["smoke", "regression", "exploratory"]},
    }, ("title", "steps")),
    "finding": object_schema({
        "step": {"type": "integer", "minimum": 1}, "what": STRING,
        "severity": {"type": "string", "enum": ["high", "medium", "low"]},
        "expected": STRING, "actual": STRING, "workaround": STRING,
    }, ("step", "what")),
    "mark": object_schema({
        "step": {"type": "integer", "minimum": 1, "maximum": 10_000},
        "status": {"type": "string", "enum": ["pending", "running", "pass", "fail", "blocked", "skipped"]},
        "note": {"type": "string", "maxLength": 8_000},
    }, ("step", "status")),
    "do": object_schema({
        "intent": {"type": "string", "minLength": 1, "maxLength": 8_000},
        "hints": {"type": "array", "items": {"type": "string", "maxLength": 2_000}, "maxItems": 20},
        "max_steps": {"type": "integer", "minimum": 1, "maximum": 20},
        "until_text": {"type": "string", "maxLength": 2_000},
        "until_url": {"type": "string", "maxLength": 4_096},
        "min_confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }, ("intent",)),
    "step": object_schema({
        "goal": {"type": "string", "maxLength": 8_000},
        "engine": {"type": "string", "enum": ["stack", "escalation", "mercury", "laya", "jev", "liquid"]}, "confirm": BOOL,
    }),
    "suggest": object_schema({
        "engine": {"type": "string", "enum": ["stack", "escalation", "mercury", "laya", "jev", "liquid"]},
        "hint": {"type": "string", "maxLength": 4_000}, "goal": {"type": "string", "maxLength": 8_000},
    }),
    "accept": object_schema(),
    "reject": object_schema({"hint": {"type": "string", "maxLength": 4_000}}),
    "reply": object_schema({
        "choice": {"type": "string", "maxLength": 1_000}, "text": {"type": "string", "maxLength": 8_000},
    }),
    "recap": object_schema({
        "outcome": {"type": "string", "enum": ["pass", "fail", "blocked", "incomplete"]},
        "note": {"type": "string", "maxLength": 8_000},
    }),
    "pilot": object_schema({
        "max_ops": {"type": "integer", "minimum": 1, "maximum": 150},
        "through": {"type": "integer", "minimum": 1}, "detach": {"type": "boolean", "enum": [True]},
    }),
    "audio": object_schema({
        "mode": {"type": "string", "enum": ["fast", "follow", "step"]},
        "padding_ms": {"type": "integer", "minimum": 0, "maximum": 5000},
        "skip": BOOL, "retry": BOOL, "muted": BOOL,
    }),
    "note": object_schema({"text": STRING}, ("text",)),
    "progress": object_schema(),
    "pilot_pause": object_schema(),
    "take_control": object_schema({
        "owner": {"type": "string", "enum": ["coordinator", "human"]}, "expected_epoch": NONNEGATIVE,
    }),
    "release_control": object_schema({"expected_epoch": NONNEGATIVE}),
}


TOOLS = [
    {
        "name": "session_create",
        "description": "Create a durable logical testing session shared by browser workers.",
        "inputSchema": object_schema({
            "title": {"type": "string", "minLength": 1, "maxLength": 4_000},
            "environment": {"type": "string", "maxLength": 2_000},
            "source_revision": {"type": "string", "maxLength": 1_000},
            "purpose": {"type": "string", "enum": ["smoke", "regression", "exploratory"]},
            "temporary": BOOL, "session_id": ID,
        }, ("title",)),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    },
    {
        "name": "session_list",
        "description": "List logical testing sessions; archived sessions are hidden unless requested.",
        "inputSchema": object_schema({"include_archived": BOOL}),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "session_snapshot",
        "description": "Read one atomic session snapshot with runs, requests, workers, and revision.",
        "inputSchema": object_schema({"session_id": ID, "run_offset": NONNEGATIVE,
                                     "run_limit": {"type": "integer", "minimum": 1, "maximum": 200}},
                                    ("session_id",)),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "session_events",
        "description": "Read a compact ordered event feed. Pass the returned cursor as after to reconnect.",
        "inputSchema": object_schema({
            "session_id": ID, "after": NONNEGATIVE,
            "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            "types": {"type": "array", "items": {"type": "string", "maxLength": 255}, "maxItems": 50},
        }, ("session_id",)),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "request_create",
        "description": "Create a durable coordination request for a person or worker.",
        "inputSchema": object_schema({
            "session_id": ID, "need": {"type": "string", "minLength": 1, "maxLength": 20_000},
            "assigned_to": ID, "run_id": ID, "request_id": ID,
        }, ("session_id", "need")),
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
    {
        "name": "request_claim",
        "description": "Atomically claim a pending coordination request.",
        "inputSchema": object_schema({
            "request_id": ID, "owner": ID, "expected_revision": NONNEGATIVE,
        }, ("request_id", "owner")),
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
    {
        "name": "request_resolve",
        "description": "Resolve a request durably, or route through its live worker when worker_id is supplied.",
        "inputSchema": object_schema({
            "request_id": ID, "result": {}, "owner": ID, "expected_revision": NONNEGATIVE,
            "worker_id": ID, "operation_id": ID,
        }, ("request_id", "result")),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    },
    {
        "name": "run_pin",
        "description": "Pin a run indefinitely, or move an unpinned run to retained lifetime.",
        "inputSchema": object_schema({"run_id": ID, "pinned": BOOL}, ("run_id",)),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    },
    {
        "name": "run_triage",
        "description": "Mark a failed, blocked, or incomplete run as triaged so retention timing can begin.",
        "inputSchema": object_schema({
            "run_id": ID, "outcome": {"type": "string", "maxLength": 255},
            "note": {"type": "string", "maxLength": 8_000},
        }, ("run_id",)),
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
    {
        "name": "retention_expire",
        "description": "Preview expired temporary evidence. Purging requires dry_run=false and confirm_purge=true.",
        "inputSchema": object_schema({
            "now": {"type": "string", "maxLength": 100}, "dry_run": BOOL, "confirm_purge": BOOL,
        }),
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True},
    },
    {
        "name": "worker_call",
        "description": (
            "Call an allowlisted browser-worker command through Reverie's authenticated loopback RPC. "
            "operation_id is required for server-side deduplication; uncertain in-flight work is never replayed."
        ),
        "inputSchema": object_schema({
            "browser_session": ID, "operation_id": ID,
            "command": {"type": "string", "enum": sorted(COMMAND_SCHEMAS)},
            "arguments": {"type": "object"}, "epoch": NONNEGATIVE, "observation_id": ID,
        }, ("browser_session", "operation_id", "command")),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    },
    {
        "name": "worker_inspect",
        "description": "Return the raw rendered screen plus an optional native-pixel target crop as MCP images.",
        "inputSchema": object_schema({
            "browser_session": ID, "operation_id": ID, "ref": ID,
            "epoch": NONNEGATIVE, "observation_id": ID,
        }, ("browser_session", "operation_id")),
        "annotations": {"readOnlyHint": True, "idempotentHint": True},
    },
]


def validate(value, schema, path="arguments"):
    if not schema:
        return
    expected = schema.get("type")
    if isinstance(expected, list):
        types = expected
    elif expected:
        types = [expected]
    else:
        types = []
    matches = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if types and not any(matches[kind](value) for kind in types):
        raise ToolError(f"{path} must be {', '.join(types)}")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolError(f"{path} must be one of {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", len(value)):
            raise ToolError(f"{path} has an invalid length")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            raise ToolError(f"{path} is outside the allowed range")
    if isinstance(value, list):
        if len(value) > schema.get("maxItems", len(value)):
            raise ToolError(f"{path} has too many items")
        for index, item in enumerate(value):
            validate(item, schema.get("items", {}), f"{path}[{index}]")
    if isinstance(value, dict) and expected == "object":
        properties = schema.get("properties", {})
        missing = [name for name in schema.get("required", []) if name not in value]
        if missing:
            raise ToolError(f"{path} is missing {', '.join(missing)}")
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise ToolError(f"{path} has unsupported field(s): {', '.join(extras)}")
        for name, item in value.items():
            if name in properties:
                validate(item, properties[name], f"{path}.{name}")


def compact(value, depth=0):
    """Bound model-facing state and strip raw image fields from JSON/text results."""
    if depth > 8:
        return "[nested data omitted]"
    if isinstance(value, dict):
        return {str(key): compact(item, depth + 1) for key, item in list(value.items())[:200]
                if str(key).lower() not in DROP_OUTPUT_KEYS}
    if isinstance(value, list):
        return [compact(item, depth + 1) for item in value[:200]]
    if isinstance(value, str):
        return value if len(value) <= 8_000 else value[:8_000] + "…"
    return value


def tool_result(value, *, images=(), is_error=False):
    value = compact(value)
    text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    if len(text) > MAX_RESULT_TEXT:
        original = value
        value = {key: item for key, item in original.items() if isinstance(item, (str, int, float, bool, type(None)))}
        value["summary"] = "Large evidence was summarized; use a narrower page or inspect the referenced worker."
        if isinstance(original.get("session"), dict):
            value["session"] = {k: original["session"].get(k) for k in
                                ("id", "title", "environment", "revision", "state", "purpose", "lifetime")}
        for key in ("events", "runs", "requests"):
            if not isinstance(original.get(key), list):
                continue
            entries = []
            for entry in original[key]:
                brief = compact(entry)
                if key == "events":
                    brief = {k: entry.get(k) for k in ("id", "seq", "type", "run_id", "worker_id", "timestamp")}
                    payload = entry.get("payload") or {}
                    brief["payload"] = {k: item[:500] if isinstance(item, str) else item
                                        for k, item in payload.items() if isinstance(item, (str, int, float, bool))}
                    for record_key in ("run", "request", "command"):
                        record = payload.get(record_key)
                        if isinstance(record, dict):
                            brief["payload"][record_key] = {k: record.get(k) for k in
                                ("id", "operation_id", "name", "status", "result", "need", "title", "role")
                                if isinstance(record.get(k), (str, int, float, bool))}
                else:
                    brief = {k: entry.get(k) for k in
                             ("id", "browser_session", "worker_id", "title", "status", "result", "role",
                              "need", "assigned_to", "owner", "lifetime", "created_at", "expired_at")}
                    brief = {k: item[:500] if isinstance(item, str) else item for k, item in brief.items()}
                candidate = {**value, key: entries + [brief]}
                if len(json.dumps(candidate, ensure_ascii=False, default=str)) > MAX_RESULT_TEXT:
                    break
                entries.append(brief)
            value[key] = entries
            if key == "events" and len(entries) < len(original[key]):
                value["cursor"] = entries[-1]["seq"] if entries else original[key][0]["seq"] - 1
                value["truncated"] = True
            if key == "runs" and len(entries) < len(original[key]):
                value["runs_next"] = int(original.get("run_offset", 0)) + len(entries)
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    content = [{"type": "text", "text": text}]
    content.extend({"type": "image", "data": data, "mimeType": mime} for data, mime in images)
    result = {"content": content, "structuredContent": value}
    if is_error:
        result["isError"] = True
    return result


class MCPAdapter:
    def __init__(self, root=None, *, claude_channel=False):
        self.root = Path(root or project_root()).resolve()
        self.store = CoordinationStore(self.root)
        self.claude_channel = bool(claude_channel)
        self.initialized = False
        self.client_capabilities = {}
        self._write_lock = threading.Lock()
        self._output = None
        self._stop = threading.Event()
        self._channel_thread = None
        self._channel_cursors = {}

    def _write(self, message):
        if self._output is None:
            return
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"), default=str)
        with self._write_lock:
            self._output.write(encoded + "\n")
            self._output.flush()

    @staticmethod
    def _protocol_error(request_id, code, message, data=None):
        error = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}

    def _initialize(self, params):
        requested = params.get("protocolVersion")
        protocol = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
        self.client_capabilities = params.get("capabilities") or {}
        capabilities = {"tools": {"listChanged": False}}
        if self.claude_channel:
            capabilities["experimental"] = {"claude/channel": {}}
        return {
            "protocolVersion": protocol,
            "capabilities": capabilities,
            "serverInfo": {"name": "reverie", "version": __version__, "title": "Reverie QA"},
            "instructions": (
                "Coordinate logical QA sessions and call browser workers with stable operation IDs. "
                "Use session_events cursors for reconnects. Never retry a worker operation reported as running."
            ),
        }

    def handle(self, message):
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
            return self._protocol_error(message.get("id") if isinstance(message, dict) else None,
                                        -32600, "Invalid Request")
        request_id = message.get("id")
        method = message["method"]
        params = message.get("params") or {}
        notification = "id" not in message
        if method == "initialize":
            if notification or not isinstance(params, dict):
                return self._protocol_error(request_id, -32602, "Invalid initialize parameters")
            result = self._initialize(params)
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        if method == "notifications/initialized":
            self.initialized = True
            self._start_channel()
            return None
        if method == "notifications/cancelled":
            return None
        if method == "ping":
            return None if notification else {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if not self.initialized:
            return None if notification else self._protocol_error(request_id, -32002, "Server is not initialized")
        if method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            if not isinstance(params, dict) or not isinstance(params.get("name"), str):
                return self._protocol_error(request_id, -32602, "tools/call requires a tool name")
            name, arguments = params["name"], params.get("arguments") or {}
            if name not in {tool["name"] for tool in TOOLS}:
                return self._protocol_error(request_id, -32602, f"Unknown tool: {name}")
            if not isinstance(arguments, dict):
                return self._protocol_error(request_id, -32602, "Tool arguments must be an object")
            try:
                result = self.call_tool(name, arguments)
            except (ValueError, OSError, SystemExit) as error:
                result = tool_result({"error": str(error) or type(error).__name__}, is_error=True)
            except Exception as error:  # Keep the stdio server alive; never expose a traceback to the model.
                result = tool_result({"error": f"{type(error).__name__}: {error}"}, is_error=True)
        else:
            return None if notification else self._protocol_error(request_id, -32601, "Method not found")
        return None if notification else {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _rpc(self, browser_session, command, arguments, operation_id, *, epoch=None, observation_id=None):
        context = {"operation_id": operation_id}
        if epoch is not None:
            context["epoch"] = epoch
        if observation_id is not None:
            context["observation_id"] = observation_id
        return call(browser_session, command, arguments, **context)

    def _browser_for_worker(self, worker_id):
        worker = self.store.worker_control(worker_id)
        if worker.get("name"):
            return worker["name"]
        if worker.get("run_id"):
            run = next((item for item in self.store.list_runs(include_expired=True)
                        if item["id"] == worker["run_id"]), None)
            if run:
                return run["browser_session"]
        raise ToolError(f"worker {worker_id!r} has no browser session")

    def call_tool(self, name, arguments):
        definition = next(tool for tool in TOOLS if tool["name"] == name)
        validate(arguments, definition["inputSchema"])
        if name == "session_create":
            result = self.store.create_session(
                arguments["title"], environment=arguments.get("environment", ""),
                revision=arguments.get("source_revision", ""), purpose=arguments.get("purpose", "smoke"),
                temporary=arguments.get("temporary", True), session_id=arguments.get("session_id"),
            )
        elif name == "session_list":
            result = {"sessions": self.store.list_sessions(arguments.get("include_archived", False))}
        elif name == "session_snapshot":
            result = self.store.snapshot(arguments["session_id"], arguments.get("run_offset", 0),
                                         arguments.get("run_limit", 50))
        elif name == "session_events":
            result = self.store.events(arguments["session_id"], after=arguments.get("after", 0),
                                       limit=arguments.get("limit", 100))
            if types := arguments.get("types"):
                result["events"] = [event for event in result["events"] if event["type"] in types]
            result = compact(result)
        elif name == "request_create":
            result = self.store.create_request(
                arguments["session_id"], arguments["need"], assigned_to=arguments.get("assigned_to", "coordinator"),
                run_id=arguments.get("run_id"), request_id=arguments.get("request_id"),
            )
        elif name == "request_claim":
            result = self.store.claim_request(arguments["request_id"], arguments["owner"],
                                              expected_revision=arguments.get("expected_revision"))
        elif name == "request_resolve":
            if worker_id := arguments.get("worker_id"):
                operation_id = arguments.get("operation_id")
                if not operation_id:
                    raise ToolError("operation_id is required when resolving through a live worker")
                result = self._rpc(
                    self._browser_for_worker(worker_id), "request_resolve",
                    {key: arguments[key] for key in ("request_id", "result", "owner", "expected_revision")
                     if key in arguments}, operation_id,
                )
            else:
                result = self.store.resolve_request(
                    arguments["request_id"], arguments["result"], owner=arguments.get("owner"),
                    expected_revision=arguments.get("expected_revision"),
                )
        elif name == "run_pin":
            result = self.store.pin_run(arguments["run_id"], pinned=arguments.get("pinned", True))
        elif name == "run_triage":
            metadata = {key: arguments[key] for key in ("outcome", "note") if key in arguments}
            result = self.store.triage_run(arguments["run_id"], **metadata)
        elif name == "retention_expire":
            dry_run = arguments.get("dry_run", True)
            if not dry_run and not arguments.get("confirm_purge", False):
                raise ToolError("confirm_purge=true is required when dry_run=false")
            result = {"dry_run": dry_run, "candidates": self.store.expire_runs(
                now=arguments.get("now"), dry_run=dry_run)}
        elif name == "worker_call":
            command = arguments["command"]
            command_arguments = arguments.get("arguments") or {}
            validate(command_arguments, COMMAND_SCHEMAS[command], f"arguments for {command}")
            if command in {"goto", "open_tab"}:
                parsed = urlparse(command_arguments["url"])
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise ToolError("browser URLs must use http or https")
            result = self._rpc(arguments["browser_session"], command, command_arguments,
                               arguments["operation_id"], epoch=arguments.get("epoch"),
                               observation_id=arguments.get("observation_id"))
        elif name == "worker_inspect":
            raw = self._rpc(arguments["browser_session"], "inspect", {"ref": arguments.get("ref")},
                            arguments["operation_id"], epoch=arguments.get("epoch"),
                            observation_id=arguments.get("observation_id"))
            image = raw.get("crop") if isinstance(raw, dict) else None
            raw_frame = raw.pop("raw_frame", None) if isinstance(raw, dict) else None
            if not image:
                image, raw_frame = raw_frame, None
            if not image:
                raise ToolError("worker returned no target crop")
            try:
                base64.b64decode(image, validate=True)
            except (ValueError, TypeError) as error:
                raise ToolError("worker returned an invalid target crop") from error
            return tool_result(raw, images=tuple((value, "image/jpeg") for value in (raw_frame, image) if value))
        else:  # pragma: no cover - tools/list and dispatch share the same catalog.
            raise ToolError(f"Unknown tool: {name}")
        return tool_result(result)

    @staticmethod
    def _actionable(event):
        if event["type"] in ACTIONABLE_EVENTS:
            return True
        payload = event.get("payload") or {}
        if isinstance(payload.get("run"), dict) and payload["run"].get("result") in {"fail", "blocked", "incomplete"}:
            return True
        values = {str(payload.get(key, "")).lower() for key in ("status", "result", "needs")}
        return bool(values & {"fail", "failed", "blocked", "incomplete", "person", "admin", "review"})

    def _start_channel(self):
        if not self.claude_channel or self._channel_thread is not None:
            return
        for session in self.store.list_sessions():
            self._channel_cursors[session["id"]] = self.store.snapshot(session["id"])["cursor"]
        self._channel_thread = threading.Thread(target=self._channel_loop, daemon=True, name="reverie-mcp-channel")
        self._channel_thread.start()

    def _channel_loop(self):
        while not self._stop.wait(0.75):
            try:
                sessions = self.store.list_sessions()
                for session in sessions:
                    session_id = session["id"]
                    if session_id not in self._channel_cursors:
                        self._channel_cursors[session_id] = 0
                    batch = self.store.events(session_id, after=self._channel_cursors[session_id], limit=100)
                    self._channel_cursors[session_id] = batch["cursor"]
                    for event in batch["events"]:
                        if not self._actionable(event):
                            continue
                        payload = compact(event.get("payload") or {})
                        content = json.dumps({"type": event["type"], "payload": payload}, ensure_ascii=False,
                                             separators=(",", ":"))[:4_000]
                        self._write({
                            "jsonrpc": "2.0", "method": "notifications/claude/channel",
                            "params": {"content": content, "meta": {
                                "session_id": str(session_id), "event_type": str(event["type"]),
                                "cursor": str(event["seq"]),
                            }},
                        })
            except Exception:
                # Channel delivery is optional. Standard tool service remains available.
                continue

    def serve(self, input_stream=None, output_stream=None):
        input_stream = input_stream or sys.stdin
        self._output = output_stream or sys.stdout
        try:
            for line in input_stream:
                try:
                    message = json.loads(line)
                except (TypeError, ValueError):
                    self._write(self._protocol_error(None, -32700, "Parse error"))
                    continue
                response = self.handle(message)
                if response is not None:
                    self._write(response)
        finally:
            self._stop.set()
            if self._channel_thread is not None:
                self._channel_thread.join(timeout=1)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m reverie.control.mcp")
    parser.add_argument("--root", default=os.environ.get("REVERIE_PROJECT_ROOT") or ".")
    parser.add_argument("--claude-channel", action="store_true",
                        help="Advertise the experimental Claude Code channel capability and push actionable events")
    args = parser.parse_args(argv)
    MCPAdapter(args.root, claude_channel=args.claude_channel).serve()


if __name__ == "__main__":
    main()
