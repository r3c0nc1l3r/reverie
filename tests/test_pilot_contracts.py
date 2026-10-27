"""Offline public contracts for pilot execution and display selection."""

import json
import socket
import sys

import pytest


def test_native_wayland_socket_is_accepted_without_x11(tmp_path):
    from reverie.control.display import resolve_display

    path = tmp_path / "wayland-test"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(path))
        env = {"XDG_RUNTIME_DIR": str(tmp_path), "WAYLAND_DISPLAY": path.name,
               "PATH": str(tmp_path)}
        resolved = resolve_display(env)
        assert resolved["WAYLAND_DISPLAY"] == path.name
        assert resolved["XDG_RUNTIME_DIR"] == str(tmp_path)
        assert "DISPLAY" not in resolved
    finally:
        server.close()


def test_invalid_explicit_display_is_not_replaced_by_wayland(tmp_path):
    from reverie.control.display import resolve_display

    path = tmp_path / "wayland-test"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(path))
        env = {"XDG_RUNTIME_DIR": str(tmp_path), "WAYLAND_DISPLAY": path.name,
               "REVERIE_DISPLAY": "not-a-display", "PATH": str(tmp_path)}
        with pytest.raises((ValueError, RuntimeError)):
            resolve_display(env)
    finally:
        server.close()


def test_codex_server_errors_are_sanitized(tmp_path, monkeypatch):
    from reverie import codex_provider

    executable = tmp_path / "fake-codex"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    if 'id' in request:\n"
        "        print(json.dumps({'id': request['id'], 'error': "
        "{'code': -32000, 'message': 'sensitive-marker-server-output'}}), flush=True)\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("REVERIE_CODEX_COMMAND", str(executable))
    monkeypatch.setenv("REVERIE_CODEX_TIMEOUT", "2")
    codex_provider.close()
    codex_provider.resume()
    try:
        with pytest.raises(codex_provider.CodexError) as exc:
            codex_provider.chat_json("system", "context")
        assert "sensitive-marker-server-output" not in str(exc.value)
    finally:
        codex_provider.close()
        codex_provider.resume()


def test_codex_server_timeout_stops_waiting(tmp_path, monkeypatch):
    from reverie import codex_provider

    executable = tmp_path / "fake-codex"
    executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
    executable.chmod(0o755)
    monkeypatch.setenv("REVERIE_CODEX_COMMAND", str(executable))
    monkeypatch.setenv("REVERIE_CODEX_TIMEOUT", "0.2")
    codex_provider.close()
    codex_provider.resume()
    try:
        with pytest.raises(codex_provider.CodexError, match="(?i)tim"):
            codex_provider.chat_json("system", "context")
    finally:
        codex_provider.close()
        codex_provider.resume()


def test_visual_action_requires_a_fresh_screenshot():
    import threading
    from types import SimpleNamespace
    from unittest.mock import Mock

    from reverie.control.session import SessionError
    from reverie.control.visual import visual_act

    browser = Mock()
    session = SimpleNamespace(lock=threading.RLock(), page={"marker": "current", "actions": []},
                              frame=None, browser=browser)
    with pytest.raises(SessionError, match="(?i)fresh screenshot"):
        visual_act(session, 10, 20)
    browser.assert_not_called()
    assert not browser.method_calls


def test_explicit_x11_takes_priority_over_available_wayland(tmp_path, monkeypatch):
    from reverie.control import display

    x11_root = tmp_path / "x11"
    x11_root.mkdir()
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    auth = tmp_path / "xauth"
    auth.write_text("synthetic")
    monkeypatch.setattr(display, "X11_SOCKET_ROOT", x11_root)
    monkeypatch.setattr(display, "PROC_ROOT", proc_root)
    x11 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    wayland = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        x11.bind(str(x11_root / "X99"))
        wayland.bind(str(tmp_path / "wayland-test"))
        resolved = display.resolve_display({
            "REVERIE_DISPLAY": ":99", "XAUTHORITY": str(auth),
            "XDG_RUNTIME_DIR": str(tmp_path), "WAYLAND_DISPLAY": "wayland-test",
            "PATH": str(tmp_path / "empty-path"),
        })
        assert resolved["DISPLAY"] == ":99"
        assert resolved["XAUTHORITY"] == str(auth)
    finally:
        x11.close()
        wayland.close()


def test_action_groups_keep_every_leaf_ordered_and_bounded():
    from reverie.actions import bounded

    actions = [{"id": f"e{n}", "kind": "click", "label": f"Action {n}", "node": n}
               for n in range(1, 484)]
    buckets = {}
    root = bounded(actions, buckets, 20)

    def leaves(page):
        assert len(page) <= 20
        flattened = []
        for action in page:
            if action["kind"] == "expand":
                flattened.extend(leaves(buckets[action["bucket"]]))
            else:
                flattened.append(action["id"])
        return flattened

    assert leaves(root) == [action["id"] for action in actions]
    small = actions[:5]
    assert bounded(small, {}, 20) == small


def test_wayland_discovery_finds_owned_runtime_socket_without_environment_name(tmp_path):
    from reverie.control.display import resolve_display

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(tmp_path / "wayland-1"))
        resolved = resolve_display({"XDG_RUNTIME_DIR": str(tmp_path), "PATH": str(tmp_path / "empty")})
        assert resolved["WAYLAND_DISPLAY"] == "wayland-1"
        assert resolved["XDG_RUNTIME_DIR"] == str(tmp_path)
        assert "DISPLAY" not in resolved
    finally:
        server.close()


def _fake_codex_server(tmp_path, mode):
    executable = tmp_path / "fake-codex"
    transcript = tmp_path / "requests.jsonl"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"transcript = {str(transcript)!r}\n"
        f"mode = {mode!r}\n"
        "def send(value):\n"
        "    print(json.dumps(value), flush=True)\n"
        "for line in sys.stdin:\n"
        "    message = json.loads(line)\n"
        "    with open(transcript, 'a') as stream:\n"
        "        stream.write(json.dumps(message) + '\\n')\n"
        "    method = message.get('method')\n"
        "    if 'id' not in message or not method:\n"
        "        continue\n"
        "    if method == 'initialize':\n"
        "        result = {'userAgent': 'fake', 'platformFamily': 'unix', 'platformOs': 'linux'}\n"
        "    elif method == 'account/read':\n"
        "        result = {'account': {'type': 'chatgpt', 'email': 'demo@example.test', "
        "'planType': 'plus'}, 'requiresOpenaiAuth': True}\n"
        "    elif method == 'thread/start':\n"
        "        result = {'thread': {'id': 't'}}\n"
        "    elif method == 'turn/start':\n"
        "        result = {'turn': {'id': 'u', 'status': 'inProgress'}}\n"
        "    else:\n"
        "        result = {'config': {}, 'data': [], 'nextCursor': None}\n"
        "    send({'id': message['id'], 'result': result})\n"
        "    if method == 'turn/start':\n"
        "        if mode == 'approval':\n"
        "            send({'id': 'approve', 'method': 'item/commandExecution/requestApproval', "
        "'params': {'threadId': 't', 'turnId': 'u', 'itemId': 'command'}})\n"
        "        else:\n"
        "            send({'method': 'item/completed', 'params': {'threadId': 't', 'turnId': 'u', "
        "'item': {'id': 'a', 'type': 'agentMessage', 'text': '{\\\"op\\\":\\\"wait\\\"}'}}})\n"
        "            send({'method': 'turn/completed', 'params': {'threadId': 't', "
        "'turn': {'id': 'u', 'status': 'completed'}}})\n"
    )
    executable.chmod(0o755)
    return executable, transcript


def test_codex_valid_turn_returns_json_and_passes_image(tmp_path, monkeypatch):
    from reverie import codex_provider

    executable, transcript = _fake_codex_server(tmp_path, "success")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("REVERIE_CODEX_COMMAND", str(executable))
    monkeypatch.setenv("REVERIE_CODEX_TIMEOUT", "3")
    codex_provider.close()
    codex_provider.resume()
    try:
        decision, metadata = codex_provider.chat_json("system", "context", images=("aGVsbG8=",))
        assert decision == {"op": "wait"}
        assert isinstance(metadata, dict)
        messages = [json.loads(line) for line in transcript.read_text().splitlines()]
        turns = [message for message in messages if message.get("method") == "turn/start"]
        assert len(turns) == 1
        assert "aGVsbG8=" in json.dumps(turns[0]["params"])
    finally:
        codex_provider.close()
        codex_provider.resume()


def test_codex_refuses_server_approval_request_without_retry(tmp_path, monkeypatch):
    from reverie import codex_provider

    executable, transcript = _fake_codex_server(tmp_path, "approval")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("REVERIE_CODEX_COMMAND", str(executable))
    monkeypatch.setenv("REVERIE_CODEX_TIMEOUT", "3")
    codex_provider.close()
    codex_provider.resume()
    try:
        with pytest.raises(codex_provider.CodexError, match="requested a tool or approval; the run stopped"):
            codex_provider.chat_json("system", "context")
    finally:
        codex_provider.close()
        codex_provider.resume()
    messages = [json.loads(line) for line in transcript.read_text().splitlines()]
    assert sum(message.get("method") == "turn/start" for message in messages) == 1
    replies = [message for message in messages if message.get("id") == "approve"]
    assert all(message.get("result", {}).get("decision") not in ("accept", "acceptForSession")
               for message in replies)
