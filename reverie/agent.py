"""The complete agent loop. Typed choices, observable state, bounded execution."""

import base64
import time
from pathlib import Path

from .browser import Browser, StalePage
from .laya import LayaPolicy, laya
from .model import action_space, choose, field_context, field_text
from .questions import MAX_STEPS


class Agent:
    def __init__(
        self,
        url,
        goals,
        *,
        record_dir=None,
        screenshots=False,
        observation_mode=None,
        decision_engine=None,
        browser=None,
    ):
        task = goals.strip() if isinstance(goals, str) else "\n".join(goals).strip()
        if not task:
            raise ValueError("Supply a task")
        plan = [task]
        self.pending_text = None
        # Hosted Jev decisions by default; local Laya (laya.cpp or MLX) when chosen.
        decision_engine = decision_engine or "jev"
        if decision_engine not in {"laya", "jev"}:
            raise ValueError("Decision engine must be laya or jev")
        self.policy = LayaPolicy(task) if decision_engine == "laya" else None
        if self.policy:
            laya()  # Load and warm the local model before the task clock starts.
        # A caller-owned browser (the agent-control session) stays open when this run closes.
        self.owns_browser = browser is None
        self.browser = browser or Browser(url)
        self.record_dir = Path(record_dir) if record_dir else None
        self.observation_mode = observation_mode or ("either" if screenshots else "dom")
        if self.observation_mode not in {"image", "dom", "either"}:
            raise ValueError("Observation mode must be image, dom, or either")
        self.screenshots = self.observation_mode != "dom" or bool(record_dir)
        self.screenshot_fallback = self.observation_mode == "either" and not record_dir
        try:
            page = self.browser.observe(
                screenshot=self.screenshots,
                screenshot_fallback=self.screenshot_fallback,
            )
        except Exception:
            self.close()
            raise
        self.state = dict(
            browser=self.browser,
            goal="\n".join(plan),
            page=page,
            decision=None,
            history=[],
            status="ready",
            plan=plan,
            plan_index=0,
            decisions=[],
            text_calls=[],
            elapsed_ms=0,
            started_at=None,
            record=bool(self.record_dir),
            observation_mode=self.observation_mode,
            decision_engine=decision_engine,
            stale_choice=None,
            stale_retries=0,
        )
        if self.record_dir and page.get("screenshot") and not page.get("screenshot_stale"):
            self.record_dir.mkdir(parents=True, exist_ok=True)
            (self.record_dir / "000000.jpg").write_bytes(base64.b64decode(page["screenshot"]))

    def snapshot(self):
        return {
            **{k: v for k, v in self.state.items() if k != "browser"},
            "elements": action_space(self.state["page"]["actions"])[0],
        }

    def command(self, name, body=None):
        body = body or {}
        state = self.state
        if name == "tick":
            try:
                self.command("predict", {})
                decision = state["decision"]
                return self.command("act", {"fingerprint": state["page"]["fingerprint"]})
            except StalePage:
                signature = (
                    decision.get("action_node"),
                    decision.get("action_kind"),
                    decision.get("action_value"),
                    decision.get("choice"),
                )
                state["stale_retries"] = state["stale_retries"] + 1 if state["stale_choice"] == signature else 1
                state["stale_choice"] = signature
                state["decision"] = None
                state["status"] = "blocked" if state["stale_retries"] >= 3 else "ready"
                state["page"] = state["browser"].observe(
                    screenshot=self.screenshots,
                    screenshot_fallback=self.screenshot_fallback,
                )
                state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
                return self.snapshot()
        elif name == "abort":
            if state["status"] not in {"done", "blocked", "aborted"}:
                state["decision"] = None
                state["status"] = "aborted"
                if state["started_at"] is not None:
                    state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
        elif name == "predict":
            if not state["browser"]:
                raise ValueError("Start a demo first")
            if state["started_at"] is None:
                state["started_at"] = time.perf_counter()
            if not state["browser"].fresh(state["page"]):
                state["page"] = state["browser"].observe(
                    screenshot=self.screenshots,
                    screenshot_fallback=self.screenshot_fallback,
                )
            state["decision"] = None
            if state["status"] in {"done", "blocked", "aborted"}:
                raise ValueError("This run has stopped. Start a fresh demo.")
            if len(state["decisions"]) >= MAX_STEPS * 2:
                raise ValueError("Reached the demo's model-call budget")
            policy = getattr(self, "policy", None)
            if policy:
                planned = policy.plan is not None
                state["decision"] = policy.choose(state["page"], state["history"])
                if not planned:
                    state["goal_plan"] = policy.plan
                    state["text_calls"].append({**policy.plan_meta, "field": "goal plan", "value": policy.plan})
            else:
                state["decision"] = choose(state["page"], state["goal"], state["history"])
            state["decisions"].append(
                {
                    **state["decision"],
                    "fingerprint": state["page"]["fingerprint"],
                    "elapsed_ms": round((time.perf_counter() - state["started_at"]) * 1000),
                }
            )
            state["status"] = "predicted"
        elif name == "act":
            decision, page = state["decision"], state["page"]
            if not decision or body.get("fingerprint") != page["fingerprint"]:
                raise ValueError("Observe and choose before acting")
            # Consume once, before any mutation or model call. A retry cannot double-click.
            state["decision"] = None
            selected = decision["choice"]
            if selected in {"DONE", "BLOCKED"}:
                if not state["browser"].fresh(page):
                    state["status"] = "ready"
                    raise StalePage("Page changed since the decision. Choose again.")
                state["status"] = "done" if selected == "DONE" else "blocked"
                state["plan_index"] = int(selected == "DONE")
                state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
                return self.snapshot()
            if decision.get("action_node") is not None:
                action = next(
                    (
                        a
                        for a in page["actions"]
                        if a.get("node") == decision["action_node"]
                        and a["kind"] == decision["action_kind"]
                        and a.get("value") == decision.get("action_value")
                    ),
                    None,
                )
            else:
                action = next((a for a in page["actions"] if a["id"] == selected), None)
            if action is None:
                raise StalePage("Chosen action changed before execution. Observe again.")
            if not state["browser"].fresh(page, action):
                refreshed = state["browser"].observe(
                    screenshot=self.screenshots,
                    screenshot_fallback=self.screenshot_fallback,
                )
                matches = [
                    candidate
                    for candidate in refreshed["actions"]
                    if candidate.get("kind") == decision.get("action_kind", action["kind"])
                    and candidate.get("label") == decision.get("action_label", action["label"])
                    and candidate.get("value") == decision.get("action_value", action.get("value"))
                ]
                if refreshed["url"] != page["url"] or len(matches) != 1:
                    raise StalePage("Chosen action changed before execution. Observe again.")
                page = refreshed
                state["page"] = page
                action = matches[0]
            if len(state["history"]) >= MAX_STEPS:
                state["status"] = "blocked"
                raise ValueError(f"Stopped at the {MAX_STEPS}-action demo budget")
            text, helper = None, None
            if action["kind"] == "fill" and decision.get("text") is not None:
                # The goal plan already holds this value; no per-field text call.
                text, helper = decision["text"], {"model": "goal plan", "latency_ms": 0}
            elif action["kind"] == "fill":
                if not state["browser"].fresh(page):
                    raise StalePage("Page changed before text generation. Choose again.")
                context = field_context(state["goal"], action, page, state["history"])
                if self.pending_text and self.pending_text[0] == context:
                    _, text, helper = self.pending_text
                else:
                    text, helper = field_text(context)
                    self.pending_text = (context, text, helper)
                    state["text_calls"].append({**helper, "field": action["label"], "value": text})
            # Browser.act checks freshness immediately before input, including after text generation.
            state["browser"].act(action, page, text=text)
            state["stale_choice"] = None
            state["stale_retries"] = 0
            self.pending_text = None
            state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
            # Record execution before observing. A stale post-action observation must not erase the action.
            state["history"].append(
                {
                    "step": len(state["history"]) + 1,
                    "action": action["label"],
                    "kind": action["kind"],
                    "choice": selected,
                    "probability": decision["probabilities"][selected],
                    "confidence": decision["confidence"],
                    "latency_ms": decision["latency_ms"],
                    "text": text,
                    "text_helper": helper["model"] if helper else None,
                    "text_latency_ms": helper["latency_ms"] if helper else 0,
                    "operation": decision["operation"],
                    "target": decision["target"],
                    "page_changed": None,
                    "url": page["url"],
                    "usage": decision["usage"],
                    "executed_ms": round((time.perf_counter() - state["started_at"]) * 1000),
                    "elapsed_ms": state["elapsed_ms"],
                }
            )
            state["page"] = state["browser"].observe(
                screenshot=self.screenshots,
                screenshot_fallback=self.screenshot_fallback,
            )
            state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
            state["history"][-1].update(
                page_changed=state["page"]["fingerprint"] != page["fingerprint"],
                url=state["page"]["url"],
                elapsed_ms=state["elapsed_ms"],
            )
            if state["record"] and state["page"].get("screenshot") and not state["page"].get("screenshot_stale"):
                (self.record_dir / f"{state['elapsed_ms']:06d}.jpg").write_bytes(
                    base64.b64decode(state["page"]["screenshot"])
                )
            repeated = state["history"][-3:]
            state["status"] = (
                "blocked"
                if len(repeated) == 3 and all(h["page_changed"] is False for h in repeated)
                else "ready"
            )
        else:
            raise ValueError("Unknown command")
        return self.snapshot()

    def run(self):
        while self.state["status"] not in {"done", "blocked", "aborted"}:
            yield self.command("tick")

    def close(self):
        if self.owns_browser:
            self.browser.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
