"""Session integration for durable coordination. Browser work stays in the observed-action executor."""

import functools
import hashlib
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

from .coordination import CoordinationStore
from .project import project_root, spec_id


class ControlError(ValueError):
    pass


def browser_operation(method):
    """Wait outside browser locks; recheck ownership immediately before an operation."""
    @functools.wraps(method)
    def wrapped(self, *args, **kwargs):
        if not getattr(self, "coordination", None):
            return method(self, *args, **kwargs)
        local = self._command_local
        depth = getattr(local, "depth", 0)
        if depth == 0:
            self._narration_boundary()
        local.depth = depth + 1
        try:
            with self.lock:
                self._validate_control()
                return method(self, *args, **kwargs)
        finally:
            local.depth = depth
    return wrapped


def browser_read(method):
    @functools.wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return wrapped


class CoordinatedSession:
    def init_coordination(self, testing_session_id=None, root=None, follow_along=False, padding_ms=350):
        self.coordination = CoordinationStore(root or project_root())
        if testing_session_id:
            group = self.coordination.get_session(testing_session_id)
            if not group:
                raise ControlError(f"Unknown testing session {testing_session_id}")
        else:
            import json

            active = self.coordination.root / ".reverie" / "active-session.json"
            try:
                selected = json.loads(active.read_text()).get("session_id")
                group = self.coordination.get_session(selected) if selected else None
            except (OSError, ValueError, TypeError):
                group = None
            if group and group.get("state") == "archived":
                group = None
            group = group or self.coordination.create_session(self.goal or "Smoke testing", environment="local")
            active.write_text(json.dumps({"session_id": group["id"]}))
        self.testing_session_id = group["id"]
        self.worker_id = uuid.uuid4().hex
        self.incarnation = uuid.uuid4().hex
        self.run_id = None
        self.plan_index = -1
        self._command_local = threading.local()
        self._pause_requested = False
        self.follow_along = bool(follow_along)
        self.padding_ms = max(0, min(5000, int(padding_ms)))
        self.visual_mode = "primary"
        self.manual_steps = False
        self.scope_revision = 0
        self.observation = {"id": None, "visual_available": False}
        self.coordination.register_worker(self.testing_session_id, self.worker_id, None, self.incarnation,
                                          {"name": self.name, "artifact_dir": str(self.trail_dir)})
        self.narrator.on_event = lambda state: self.log("narration", **state)

    def _shared_event(self, record):
        if not getattr(self, "coordination", None):
            return
        event = self.coordination.append_event(self.testing_session_id, record["event"], record,
                                               run_id=self.run_id, worker_id=self.worker_id)
        self._shared_revision = event["seq"]
        if self.run_id and record["event"] not in {"caption", "frame", "frame_before", "suggest", "narration"}:
            self._sync_shared_run()

    def _register_shared_run(self):
        if not getattr(self, "coordination", None):
            return
        if self.run_id:
            self.coordination.update_run(self.run_id, active=False, ended=datetime.now(UTC).isoformat())
        self.plan_index += 1
        self.run_id = f"{self.trail_dir.name}~{self.plan_index}"
        test = self.test or {}
        self.coordination.register_run(
            self.testing_session_id, self.run_id, self.name, worker_id=self.worker_id,
            artifact_dir=str(self.trail_dir), title=test.get("title"),
            test_id=spec_id(test.get("source"), test.get("title")), source=test.get("source"),
            role=test.get("role", "unspecified"), purpose=test.get("purpose", "smoke"), status="running", result="running", active=True,
            steps=test.get("steps", []), started=self.started)
        self.coordination.bind_worker_run(self.worker_id, self.run_id)

    def _sync_shared_run(self, ended=None):
        if not getattr(self, "coordination", None) or not self.run_id:
            return
        test = self.test or {}
        self.coordination.update_run(
            self.run_id, title=test.get("title"), test_id=spec_id(test.get("source"), test.get("title")),
            role=test.get("role", "unspecified"), source=test.get("source"), steps=test.get("steps", []),
            status=test.get("result", "running"), result=test.get("result", "running"),
            active=not bool(ended), ended=ended,
            visual_available=(self.observation or {}).get("visual_available", False),
            diagnosis=next((st.get("diagnosis") for st in test.get("steps", []) if st.get("diagnosis")), None),
            findings=[finding for st in test.get("steps", []) for finding in st.get("findings", [])])

    def _observation_ready(self, visual_available):
        if not getattr(self, "coordination", None):
            return
        frame_id = hashlib.sha256((self.frame or "").encode()).hexdigest()[:20] if visual_available else None
        self.observation = {"id": uuid.uuid4().hex, "frame_id": frame_id,
                            "captured_at": datetime.now(UTC).isoformat(),
                            "visual_available": bool(visual_available), "scope_revision": self.scope_revision,
                            "url": (self.page or {}).get("url"), "worker_id": self.worker_id,
                            "incarnation": self.incarnation}
        if visual_available:
            import base64
            import io

            from PIL import Image

            try:
                image = Image.open(io.BytesIO(base64.b64decode(self.frame)))
                self.observation.update(width=image.width, height=image.height)
            except (ValueError, OSError):
                self.observation["visual_available"] = False
            self.observation["file"] = self.save_frame("observation")
        self.log("observation", **self.observation)

    def shared_summary(self):
        if not getattr(self, "coordination", None):
            return {}
        control = self.coordination.worker_control(self.worker_id)
        narration = self.narrator.state(self.padding_ms)
        narration.update(mode="step" if self.manual_steps else "follow" if self.follow_along else "fast",
                         padding_ms=self.padding_ms, muted=self.narrator.muted)
        return {"testing_session_id": self.testing_session_id, "session_id": self.testing_session_id,
                "run_id": self.run_id, "worker_id": self.worker_id, "incarnation": self.incarnation,
                "revision": self.coordination.get_session(self.testing_session_id)["revision"],
                "observation": self.observation,
                "controls": {**control, "paused": self._pause_requested,
                             "pause_requested": self._pause_requested}, "narration": narration}

    def _narration_boundary(self):
        actor = getattr(self._command_local, "actor", None) or "coordinator"
        if self._pause_requested and actor == "pilot":
            raise ControlError("Execution is paused; resume the pilot or take control")
        if self.follow_along:
            ready = self.narrator.boundary(padding_ms=self.padding_ms,
                                           cancelled=lambda: self._pause_requested and actor == "pilot")
            if not ready:
                raise ControlError("Execution paused while narration was finishing")

    def _validate_control(self):
        control = self.coordination.worker_control(self.worker_id)
        local = self._command_local
        pilot = getattr(self, "pilot_thread", None) is threading.current_thread()
        actor = "pilot" if pilot else (getattr(local, "actor", None) or "coordinator")
        if self._pause_requested and actor == "pilot":
            raise ControlError("Pilot paused at the operation boundary")
        if control.get("owner") != actor:
            raise ControlError(f"Worker is controlled by {control.get('owner')}; request control before acting")
        if actor == "pilot" and not self.observation.get("visual_available"):
            raise ControlError("Visual observation unavailable; capture a fresh screen before acting")
        epoch = getattr(local, "epoch", None)
        if epoch is not None and epoch != control.get("epoch"):
            raise ControlError("Control ownership changed; obtain fresh state before acting")
        scope = getattr(local, "scope_revision", None)
        if scope is not None and scope != self.scope_revision:
            raise ControlError("Instructions changed; observe and choose again")
        observation_id = getattr(local, "observation_id", None)
        if observation_id and observation_id != self.observation.get("id"):
            raise ControlError("Observation is stale; observe again before acting")

    @contextmanager
    def command_context(self, actor="coordinator", epoch=None, observation_id=None):
        local = self._command_local
        previous = {k: getattr(local, k, None) for k in ("actor", "epoch", "observation_id", "scope_revision")}
        local.actor = actor
        local.epoch = previous["epoch"] if epoch is None and previous["actor"] == actor else epoch
        local.observation_id = observation_id
        local.scope_revision = self.scope_revision
        try:
            yield
        finally:
            for key, value in previous.items():
                setattr(local, key, value)

    def cmd_state(self):
        self.reconcile_requests()
        snapshot = self.coordination.snapshot(self.testing_session_id)
        return {**snapshot, "worker": self.watch_state()}

    def cmd_changes(self, after=0, limit=200, timeout=0):
        deadline = time.monotonic() + min(30, max(0, timeout))
        while True:
            batch = self.coordination.events(self.testing_session_id, after=after, limit=min(500, limit))
            if batch["events"] or time.monotonic() >= deadline:
                return batch
            time.sleep(0.05)

    def cmd_pilot_pause(self):
        # Publish the request without waiting on an action lock, model, or player process.
        self._pause_requested = True
        self.pilot_stop_requested = True
        self.log("pause_requested", actor="human")
        return {"pause_requested": True, **self.summary()}

    def cmd_take_control(self, owner="human", expected_epoch=None):
        self._pause_requested = True
        self.pilot_stop_requested = True
        with self.lock:
            current = self.coordination.worker_control(self.worker_id)
            control = self.coordination.transfer_control(self.worker_id, current["owner"],
                                                        current["epoch"] if expected_epoch is None else expected_epoch,
                                                        owner, override=True)
            self.pending = None
            self.scope_revision += 1
        return {"control": control, **self.summary()}

    def cmd_release_control(self, expected_epoch=None):
        with self.lock:
            current = self.coordination.worker_control(self.worker_id)
            control = self.coordination.transfer_control(self.worker_id, current["owner"],
                                                        current["epoch"] if expected_epoch is None else expected_epoch,
                                                        "coordinator")
            self._pause_requested = False
            self.pending = None
            self.scope_revision += 1
            self.observe()
        return {"control": control, **self.summary()}

    def _request_in_session(self, request_id):
        if not any(r["id"] == request_id for r in self.coordination.list_requests(self.testing_session_id)):
            raise ControlError("Request does not belong to this testing session")

    def cmd_request_claim(self, request_id, owner="coordinator", expected_revision=None):
        self._request_in_session(request_id)
        return {"request": self.coordination.claim_request(request_id, owner, expected_revision=expected_revision)}

    def cmd_request_resolve(self, request_id, result=None, owner=None, expected_revision=None):
        self._request_in_session(request_id)
        resolved = self.coordination.resolve_request(request_id, result or {}, owner=owner,
                                                    expected_revision=expected_revision)
        cp = next((c for c in self.checkpoints if c.get("request_id") == request_id), None)
        if cp and cp["status"] == "pending":
            data = result if isinstance(result, dict) else {"note": str(result)}
            self.resolve_checkpoint(cp["id"], data.get("status", "done"), note=data.get("note", ""))
        prompt = self.prompt
        if prompt and prompt.get("request_id") == request_id:
            data = result if isinstance(result, dict) else {"text": str(result)}
            self.reply(data.get("choice", "Continue"), data.get("text", ""))
        return {"request": resolved, **self.summary()}

    def cmd_run_pin(self, pinned=True):
        return {"run": self.coordination.pin_run(self.run_id, pinned=pinned)}

    def cmd_run_triage(self):
        return {"run": self.coordination.triage_run(self.run_id)}

    def cmd_inspect(self, ref=None):
        """Return real pixels at native size and read-only loading diagnostics for ambiguous targets."""
        import base64
        import io

        from PIL import Image

        with self.lock:
            self.observe()
            if not self.observation.get("visual_available"):
                raise ControlError("Screenshot capture failed; inspection is unavailable")
            result = {"observation": dict(self.observation), "ref": ref, "crop": None, "raw_frame": self.frame}
            if ref:
                action = self.resolve(ref=ref)
                rect = action.get("rect")
                if rect:
                    image = Image.open(io.BytesIO(base64.b64decode(self.frame))).convert("RGB")
                    # Screenshot and DOM coordinates share the configured device-scale viewport.
                    pad = 48
                    left, top = max(0, rect["x"] - pad), max(0, rect["y"] - pad)
                    right = min(image.width, rect["x"] + rect["w"] + pad)
                    bottom = min(image.height, rect["y"] + rect["h"] + pad)
                    if right > left and bottom > top:
                        output = io.BytesIO()
                        image.crop((left, top, right, bottom)).save(output, format="JPEG", quality=95)
                        result["crop"] = base64.b64encode(output.getvalue()).decode()
                        result["crop_file"] = f"crop-{self.observation['id']}.jpg"
                        (self.trail_dir / "frames").mkdir(exist_ok=True)
                        (self.trail_dir / "frames" / result["crop_file"]).write_bytes(output.getvalue())
                        self.observation["target_crop"] = result["crop"]
            try:
                result["readiness"] = self.browser.evaluate("""(() => ({
                    ready:document.readyState, fonts:document.fonts.status,
                    images:[...document.images].filter(i=>!i.complete||!i.naturalWidth).slice(0,20)
                      .map(i=>({alt:i.alt,complete:i.complete,broken:i.complete&&!i.naturalWidth})),
                    busy:[...document.querySelectorAll('[aria-busy="true"],[role="progressbar"]')].length
                }))()""")
            except (RuntimeError, TimeoutError):
                result["readiness"] = {"unavailable": True}
            self.log("inspection", ref=ref, observation_id=self.observation["id"],
                     readiness=result.get("readiness"), frame=self.observation.get("file"),
                     crop_file=result.get("crop_file"))
            return result

    def reconcile_requests(self):
        if not getattr(self, "coordination", None):
            return
        requests = {r["id"]: r for r in self.coordination.list_requests(self.testing_session_id)}
        for cp in list(self.checkpoints):
            request = requests.get(cp.get("request_id"))
            if cp.get("status") == "pending" and request and request["status"] == "resolved":
                result = request.get("result") or {}
                if not isinstance(result, dict):
                    result = {"note": str(result)}
                self.resolve_checkpoint(cp["id"], result.get("status", "done"), note=result.get("note", ""))
        request = requests.get((self.prompt or {}).get("request_id"))
        if request and request["status"] == "resolved" and not self.external_reply:
            result = request.get("result") or {}
            if not isinstance(result, dict):
                result = {"text": str(result)}
            self.reply(result.get("choice", "Continue"), result.get("text", ""))
