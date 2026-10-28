"""Public coordination and integration contracts, exercised without a browser."""

import json
import subprocess
import sys

import pytest

from reverie.control.coordination import CoordinationConflict, CoordinationStore


def test_requests_use_revision_to_prevent_double_claim(tmp_path):
    store = CoordinationStore(tmp_path)
    store.create_session("Investigation", session_id="qa")
    store.create_request("qa", "Review the warning", request_id="r1")
    revision = store.get_session("qa")["revision"]
    store.claim_request("r1", "alice", expected_revision=revision)
    with pytest.raises(CoordinationConflict):
        store.claim_request("r1", "bob", expected_revision=revision)


def test_snapshot_paginates_attempts_without_losing_earlier_runs(tmp_path):
    store = CoordinationStore(tmp_path)
    store.create_session("Investigation", session_id="qa")
    for number in range(5):
        store.register_run("qa", f"run-{number}", "admin")

    first = store.snapshot("qa", run_limit=2)
    assert first["run_total"] == 5
    assert len(first["runs"]) == 2
    second = store.snapshot("qa", run_offset=first["runs_next"], run_limit=2)
    third = store.snapshot("qa", run_offset=second["runs_next"], run_limit=2)
    ids = [run["run_id"] for page in (first, second, third) for run in page["runs"]]
    assert set(ids) == {f"run-{number}" for number in range(5)}
    assert len(ids) == len(set(ids))


def _mcp_exchange(root, messages):
    process = subprocess.run(
        [sys.executable, "-m", "reverie.control.mcp", "--root", str(root)],
        input="".join(json.dumps(message) + "\n" for message in messages),
        capture_output=True, text=True, timeout=15, check=True,
    )
    return [json.loads(line) for line in process.stdout.splitlines() if line.strip()]


def test_mcp_restricts_worker_calls_and_requires_operation_id(tmp_path):
    messages = [
        {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "contract-test", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "worker_call", "arguments": {"browser_session": "worker", "command": "act"}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "worker_call", "arguments": {"browser_session": "worker", "command": "stop",
                                                    "operation_id": "op-stop"}}},
    ]
    responses = {message["id"]: message for message in _mcp_exchange(tmp_path, messages)}
    tools = {tool["name"]: tool for tool in responses[1]["result"]["tools"]}
    assert "worker_call" in tools and "worker_inspect" in tools
    assert "operation_id" in tools["worker_call"]["inputSchema"]["required"]
    for forbidden in ("shell", "execute", "reload", "stop", "secret"):
        assert forbidden not in tools
    assert responses[2]["result"]["isError"]
    assert responses[3]["result"]["isError"]


def test_event_history_survives_reopen_in_order(tmp_path):
    store = CoordinationStore(tmp_path)
    store.create_session("Investigation", session_id="qa")
    store.append_event("qa", "note", {"message": "first-marker"})
    store.append_event("qa", "note", {"message": "second-marker"})
    before = store.events("qa")
    after = CoordinationStore(tmp_path).events("qa")
    assert after == before
    assert [event["payload"]["message"] for event in after["events"]
            if event["type"] == "note"] == ["first-marker", "second-marker"]


def test_takeover_fences_a_command_from_the_previous_epoch(tmp_path):
    store = CoordinationStore(tmp_path)
    store.create_session("Investigation", session_id="qa")
    store.register_run("qa", "run-1", "admin")
    store.register_worker("qa", "worker-1", "run-1", "incarnation-1")
    control = store.worker_control("worker-1")
    epoch = control["epoch"]
    store.transfer_control("worker-1", control["owner"], epoch, "human", override=True)
    assert store.worker_control("worker-1")["epoch"] > epoch
    with pytest.raises(CoordinationConflict):
        store.begin_command(
            "qa", "stale-operation", "act", arguments={"ref": "e1"},
            worker_id="worker-1", owner=control["owner"], epoch=epoch,
            incarnation="incarnation-1",
        )


def test_viewer_rejects_duplicate_or_stale_revisions():
    from reverie.control.live import newer_revision

    assert newer_revision({"revision": 11}, 10) == 11
    assert newer_revision({"revision": 10}, 10) is None
    assert newer_revision({"revision": 9}, 10) is None


def test_operation_id_replays_saved_result_and_rejects_changed_arguments(tmp_path):
    store = CoordinationStore(tmp_path)
    store.create_session("Investigation", session_id="qa")
    store.begin_command("qa", "operation-1", "inspect", arguments={"ref": "e1"})
    store.finish_command("qa", "operation-1", result={"marker": "saved-result"})
    replay = store.begin_command("qa", "operation-1", "inspect", arguments={"ref": "e1"})
    assert replay["result"] == {"marker": "saved-result"}
    with pytest.raises(CoordinationConflict):
        store.begin_command("qa", "operation-1", "inspect", arguments={"ref": "e2"})


def test_worker_cannot_be_bound_to_a_different_testing_session(tmp_path):
    store = CoordinationStore(tmp_path)
    store.create_session("First", session_id="first")
    store.create_session("Second", session_id="second")
    store.register_run("first", "run-1", "admin")
    store.register_worker("first", "worker-1", "run-1", "incarnation-1")
    control = store.worker_control("worker-1")
    with pytest.raises(CoordinationConflict):
        store.begin_command(
            "second", "cross-session", "inspect", arguments={}, worker_id="worker-1",
            owner=control["owner"], epoch=control["epoch"], incarnation="incarnation-1",
        )


def test_unfinished_operation_is_not_reserved_twice(tmp_path):
    store = CoordinationStore(tmp_path)
    store.create_session("Investigation", session_id="qa")
    first = store.begin_command("qa", "operation-1", "inspect", arguments={"ref": "e1"})
    replay = CoordinationStore(tmp_path).begin_command(
        "qa", "operation-1", "inspect", arguments={"ref": "e1"})
    assert first["status"] == "new"
    assert replay["status"] == "running"


def test_viewer_coalesces_frames_preserves_events_and_resyncs_overflow():
    import asyncio

    from reverie.control.live import ViewerBuffer

    async def exercise():
        viewer = ViewerBuffer(event_limit=2)
        await viewer.put_live("run-1", {"type": "frame", "sequence": 1})
        await viewer.put_live("run-1", {"type": "frame", "sequence": 2})
        await viewer.put_event({"type": "event", "sequence": 3})
        assert (await viewer.get())["sequence"] == 3
        assert (await viewer.get())["sequence"] == 2
        await viewer.put_event({"type": "event", "sequence": 4})
        await viewer.put_event({"type": "event", "sequence": 5})
        await viewer.put_event({"type": "event", "sequence": 6})
        assert await viewer.get() == {"type": "resync_required", "reason": "slow_viewer"}
        await viewer.close()
    asyncio.run(exercise())


def test_narration_boundary_waits_for_completion_and_remaining_padding():
    import threading
    import time

    from reverie.control.narrator import Narrator, SpeechTicket

    narrator = Narrator(voice="off")
    ticket = SpeechTicket(id=1, text="test")
    finished = threading.Event()
    outcome = []

    def wait():
        outcome.append(narrator.boundary(ticket, padding_ms=350, timeout=3))
        finished.set()

    thread = threading.Thread(target=wait)
    thread.start()
    assert not finished.wait(0.05)
    ticket.state = "completed"
    ticket.ended = time.monotonic() - 0.25
    ticket.done.set()
    assert not finished.wait(0.04)
    assert finished.wait(1)
    thread.join()
    assert outcome == [True]
    narrator.close()


def test_retention_previews_then_removes_only_due_evidence_and_keeps_result(tmp_path):
    store = CoordinationStore(tmp_path)
    store.create_session("Investigation", session_id="qa")
    for run_id, result, active in (("passed", "pass", False), ("failed", "fail", False),
                                   ("active", "pass", True)):
        artifact = tmp_path / ".reverie" / "runs" / run_id
        artifact.mkdir(parents=True)
        (artifact / "trail.jsonl").write_text("evidence")
        store.register_run("qa", run_id, "admin", artifact_dir=str(artifact),
                           status="complete", result=result, active=active,
                           completed_at="2026-10-01T00:00:00+00:00")

    now = "2026-10-27T00:00:00+00:00"
    store.expire_runs(now=now)
    assert all((tmp_path / ".reverie" / "runs" / run_id / "trail.jsonl").exists()
               for run_id in ("passed", "failed", "active"))
    store.expire_runs(now=now, dry_run=False)
    assert not (tmp_path / ".reverie" / "runs" / "passed" / "trail.jsonl").exists()
    assert (tmp_path / ".reverie" / "runs" / "failed" / "trail.jsonl").exists()
    assert (tmp_path / ".reverie" / "runs" / "active" / "trail.jsonl").exists()
    passed = next(run for run in store.list_runs("qa", include_expired=True)
                  if run["run_id"] == "passed")
    assert passed["result"] == "pass"
    assert passed["expired_at"] or passed["purged_at"]


def test_retention_preserves_shared_and_outside_evidence(tmp_path):
    store = CoordinationStore(tmp_path)
    store.create_session("Investigation", session_id="qa")
    shared = tmp_path / ".reverie" / "runs" / "shared"
    shared.mkdir(parents=True)
    (shared / "trail.jsonl").write_text("shared")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "trail.jsonl").write_text("outside")
    for run_id, artifact, result in (("pass", shared, "pass"), ("fail", shared, "fail"),
                                      ("outside", outside, "pass")):
        store.register_run("qa", run_id, "admin", artifact_dir=str(artifact),
                           status="complete", result=result, active=False,
                           completed_at="2026-10-01T00:00:00+00:00")
    store.expire_runs(now="2026-10-27T00:00:00+00:00", dry_run=False)
    assert (shared / "trail.jsonl").read_text() == "shared"
    assert (outside / "trail.jsonl").read_text() == "outside"


def test_retention_does_not_follow_artifact_symlink(tmp_path):
    store = CoordinationStore(tmp_path)
    store.create_session("Investigation", session_id="qa")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "trail.jsonl").write_text("evidence")
    run_dir = tmp_path / ".reverie" / "runs"
    run_dir.mkdir(parents=True)
    link = run_dir / "linked"
    link.symlink_to(outside, target_is_directory=True)
    store.register_run("qa", "linked", "admin", artifact_dir=str(link),
                       status="complete", result="pass", active=False,
                       completed_at="2026-10-01T00:00:00+00:00")
    store.expire_runs(now="2026-10-27T00:00:00+00:00", dry_run=False)
    assert (outside / "trail.jsonl").read_text() == "evidence"


def test_snapshot_cursor_is_its_own_session_event_watermark(tmp_path):
    store = CoordinationStore(tmp_path)
    store.create_session("First", session_id="first")
    store.create_session("Second", session_id="second")
    before = store.events("first")["cursor"]
    for i in range(12):
        store.append_event("second", "noise", {"number": i})
    assert store.events("first")["cursor"] == before
    store.append_event("first", "note", {"message": "watermark"})
    snapshot = store.snapshot("first")
    page = store.events("first")
    assert snapshot["cursor"] == page["cursor"]
    assert store.events("first", after=snapshot["cursor"])["events"] == []
    store.append_event("first", "note", {"message": "after snapshot"})
    events = store.events("first", after=snapshot["cursor"])["events"]
    assert [event["payload"]["message"] for event in events] == ["after snapshot"]


def test_operation_replay_is_bound_to_worker_and_control_identity(tmp_path):
    store = CoordinationStore(tmp_path)
    store.create_session("Investigation", session_id="qa")
    for suffix in ("1", "2"):
        store.register_run("qa", "run-" + suffix, "browser-" + suffix)
        store.register_worker("qa", "worker-" + suffix, "run-" + suffix, "inc-" + suffix)
    first = store.worker_control("worker-1")
    second = store.worker_control("worker-2")
    context = {"worker_id": "worker-1", "owner": first["owner"],
               "epoch": first["epoch"], "incarnation": "inc-1"}
    store.begin_command("qa", "op", "inspect", arguments={}, **context)
    store.finish_command("qa", "op", result={"marker": "result"})
    assert store.begin_command("qa", "op", "inspect", arguments={}, **context)["result"] == {"marker": "result"}
    changed = [
        {"worker_id": "worker-2", "owner": second["owner"], "epoch": second["epoch"], "incarnation": "inc-2"},
        {**context, "owner": "different-owner"},
        {**context, "epoch": first["epoch"] + 1},
        {**context, "incarnation": "different-incarnation"},
    ]
    for altered in changed:
        with pytest.raises(CoordinationConflict):
            store.begin_command("qa", "op", "inspect", arguments={}, **altered)


def test_websocket_resync_does_not_drop_event_during_snapshot(tmp_path, monkeypatch):
    import asyncio
    import threading

    from aiohttp.test_utils import TestClient, TestServer

    from reverie.control.dashboard import create_app

    store = CoordinationStore(tmp_path)
    store.create_session("Investigation", session_id="qa")
    store.create_session("Other", session_id="other")
    for i in range(5):
        store.append_event("other", "noise", {"number": i})
    freeze = threading.Event()
    captured = threading.Event()
    observed = threading.Event()
    release = threading.Event()
    original_snapshot = CoordinationStore.snapshot
    original_events = CoordinationStore.events

    def snapshot(self, session_id, *args, **kwargs):
        value = original_snapshot(self, session_id, *args, **kwargs)
        if session_id == "qa" and freeze.is_set():
            freeze.clear()
            captured.set()
            if not release.wait(5):
                raise TimeoutError("test snapshot was not released")
        return value

    def events(self, session_id, *args, **kwargs):
        value = original_events(self, session_id, *args, **kwargs)
        if session_id == "qa" and any("updated-title" in json.dumps(event.get("payload", {}))
                                      for event in value["events"]):
            observed.set()
        return value

    monkeypatch.setattr(CoordinationStore, "snapshot", snapshot)
    monkeypatch.setattr(CoordinationStore, "events", events)

    async def exercise():
        app = create_app([tmp_path], token="synthetic-token", project_root=tmp_path,
                         poll_interval=0.01, viewer_event_limit=2)
        async with TestClient(TestServer(app)) as client:
            ws = await client.ws_connect("/api/ws?session=qa&after=0",
                                         headers={"X-Laya-Agent-Token": "synthetic-token"})
            first = await asyncio.wait_for(ws.receive_json(), 3)
            assert first["type"] == "snapshot"
            freeze.set()
            await ws.send_json({"type": "resync"})
            try:
                assert await asyncio.to_thread(captured.wait, 3)
                store.update_session("qa", title="updated-title")
                updated_cursor = original_events(store, "qa")["cursor"]
                await asyncio.to_thread(observed.wait, 0.25)
            finally:
                release.set()
            snapshot_cursor = None
            title = None
            client_cursor = None
            for _ in range(12):
                message = await asyncio.wait_for(ws.receive_json(), 3)
                if message["type"] == "snapshot":
                    snapshot_cursor = message["cursor"]
                    client_cursor = snapshot_cursor
                    title = message["data"]["session"]["title"]
                elif message["type"] == "event" and snapshot_cursor is not None:
                    if message["cursor"] > snapshot_cursor:
                        client_cursor = message["cursor"]
                        payload = message["event"].get("payload", {})
                        if "updated-title" in json.dumps(payload):
                            title = "updated-title"
                if title == "updated-title":
                    break
            assert title == "updated-title"
            assert client_cursor >= updated_cursor
            await ws.close()

    asyncio.run(exercise())


def test_omitted_worker_epoch_is_bound_and_replay_fenced_after_takeover(tmp_path):
    store = CoordinationStore(tmp_path)
    store.create_session("Investigation", session_id="qa")
    store.register_run("qa", "run-1", "admin")
    store.register_worker("qa", "worker-1", "run-1", "inc-1")
    original = store.worker_control("worker-1")
    context = {"worker_id": "worker-1", "owner": original["owner"]}
    store.begin_command("qa", "op", "inspect", arguments={}, **context)
    store.finish_command("qa", "op", result={"marker": "result"})
    assert store.begin_command("qa", "op", "inspect", arguments={}, **context)["result"] == {"marker": "result"}

    store.transfer_control("worker-1", original["owner"], original["epoch"], "human", override=True)
    human = store.worker_control("worker-1")
    store.transfer_control("worker-1", "human", human["epoch"], original["owner"], override=True)
    with pytest.raises(CoordinationConflict):
        store.begin_command("qa", "op", "inspect", arguments={}, **context)
    with pytest.raises(CoordinationConflict):
        store.begin_command("qa", "op", "inspect", arguments={},
                            epoch=original["epoch"], incarnation="inc-1", **context)
