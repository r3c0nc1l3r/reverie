"""TypeSafe decisions (optional cloud backend) and the OpenAI-compatible text model helpers."""

import json
import math
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .questions import GOAL_PLAN, NEXT_ACTION, TARGET, TEXT_VALUE

CLIENT = httpx.Client(http2=True, timeout=25)
OPENROUTER_JEV_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_REMOTE_DECISION_MODEL = "typesafe/jev-1.13"


def remote_decision_model():
    return os.environ.get("REMOTE_DECISION_MODEL", DEFAULT_REMOTE_DECISION_MODEL)


def post_json(url, key, body, headers=None):
    for attempt in range(3):
        try:
            response = CLIENT.post(url, json=body, headers={"Authorization": f"Bearer {key}", **(headers or {})})
        except httpx.HTTPError:
            raise RuntimeError("Model connection failed; no action executed.") from None
        if response.status_code in {429, 529, 503} and attempt < 2:
            time.sleep(0.5 * 2**attempt)
            continue
        if response.is_error:
            raise RuntimeError(f"Model provider returned HTTP {response.status_code}{provider_error(response)}; "
                               "no action executed.")
        return response.json()
    raise RuntimeError("Model unavailable")


def provider_error(response):
    """The provider's own error message (such as insufficient credits), shortened, for the operator."""
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return ""
    return f": {' '.join(str(message).split())[:200]}" if message else ""


def validate_choice(answer, ids):
    """A choice answer must pick a listed option. The Decisions API marks `probabilities` and `confidence`
    optional; when one is missing, a pick without its probability counts as zero confidence (never certain)."""
    try:
        answer = dict(answer)
        if "probabilities" not in answer:
            answer["probabilities"] = {i: float(i == answer["choice"]) for i in ids}
            answer.setdefault("confidence", 0.0)
        answer.setdefault("confidence", answer["probabilities"].get(answer["choice"], 0.0))
        probabilities = answer["probabilities"]
        numbers = [*probabilities.values(), answer["confidence"]]
        valid = (
            answer["choice"] in ids
            and set(probabilities) == set(ids)
            and all(type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 1 for n in numbers)
            and abs(sum(probabilities.values()) - 1) < 0.02
            and probabilities[answer["choice"]] >= max(probabilities.values()) - 1e-6
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("Invalid TypeSafe response; no action executed.")
    return answer


def openrouter_key():
    """Use a dedicated key when set, or the existing OpenRouter text-helper key."""
    key = os.environ.get("OPENROUTER_API_KEY")
    text_base = os.environ.get("TEXT_MODEL_BASE_URL", "https://api.deepseek.com/v1")
    if not key and (urlparse(text_base).hostname or "").lower() == "openrouter.ai":
        key = os.environ.get("TEXT_MODEL_API_KEY")
    if not key:
        raise ValueError(
            "Jev needs OPENROUTER_API_KEY, or TEXT_MODEL_API_KEY with TEXT_MODEL_BASE_URL set to OpenRouter."
        )
    return key


def action_space(actions):
    """One index per observed element; each operation has its own valid target choices."""
    elements, indices, targets, controls = [], {}, {}, {}
    operations = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT"}
    for action in actions:
        kind = action["kind"]
        if kind not in operations:
            controls[action["id"].upper()] = action
            continue
        node = action["node"]
        if node not in indices:
            index = str(len(elements) + 1)
            indices[node] = index
            element = {k: action[k] for k in ("role", "value", "checked", "selected", "expanded") if k in action}
            element.update(index=index, label=action["label"].split(" → ")[0], operations=[])
            if kind == "select":
                element["value"] = action.get("current_value", "")
                element["options"] = []
            elements.append(element)
        index = indices[node]
        operation = operations[kind]
        group = targets.setdefault(operation, {})
        element = elements[int(index) - 1]
        if operation not in element["operations"]:
            element["operations"].append(operation)
        target = index
        if kind == "select":
            target = f"{index}:{len(element['options']) + 1}"
            element["options"].append({"index": target, "label": action["label"], "value": action["value"]})
        group[target] = action
    return elements, targets, controls


def choose(state, goal, history):
    elements, targets, controls = action_space(state["actions"])
    labels = {
        "CLICK": "Click an element, button, menu option, autocomplete suggestion, or calendar day.",
        "TYPE_TEXT": "Enter or replace text in an editable field. A small LLM will supply the value from the goal.",
        "SELECT": "Select an observed dropdown value.",
    }
    operations = {key: labels[key] for key in targets}
    operations.update({key: value["label"] for key, value in controls.items()})
    operations.update(DONE="Every requirement is visibly satisfied.", BLOCKED="No supported operation can progress.")
    questions = {
        "operation": {"type": "choice", "criteria": operations, "instructions": {"goal": goal, "rules": NEXT_ACTION}}
    }
    for operation, candidates in targets.items():
        questions[operation.lower() + "_target"] = {
            "type": "choice",
            "criteria": {
                index: {
                    "element": f"[{index}] {a['label']}",
                    "current_value": a.get("current_value", a.get("value", "")),
                    **{k: a[k] for k in ("role", "checked", "selected", "expanded") if k in a},
                }
                for index, a in candidates.items()
            },
            "instructions": {"goal": goal, "operation": operation, "rules": [NEXT_ACTION, TARGET]},
        }
    body = {
        "model": remote_decision_model(),
        "session_id": SESSION_ID,
        "state": {
            "page": {k: state[k] for k in ("url", "title", "text")},
            "elements": elements,
            "recent_actions": [
                {k: h.get(k) for k in ("action", "kind", "text", "page_changed")} for h in history[-10:]
            ],
        },
        "questions": questions,
    }
    started = time.perf_counter()
    result = post_json(OPENROUTER_JEV_ENDPOINT, openrouter_key(), body)
    operation_answer = validate_choice(result["answers"].get("operation", {}), operations)
    operation = operation_answer["choice"]
    target = None
    target_answer = None
    probabilities = {}
    if operation in targets:
        # Unused target heads cannot cause an action. Validate the head selected by the operation.
        target_answer = validate_choice(result["answers"].get(operation.lower() + "_target", {}), targets[operation])
        target = target_answer["choice"]
        choice = targets[operation][target]["id"]
        probabilities = {a["id"]: target_answer["probabilities"][index] for index, a in targets[operation].items()}
        action = targets[operation][target]
    else:
        choice = controls[operation]["id"] if operation in controls else operation
        probabilities[choice] = operation_answer["probabilities"][operation]
        action = controls.get(operation)
    return {
        "choice": choice,
        "operation": operation,
        "target": target,
        "action_node": action.get("node") if action else None,
        "action_kind": action.get("kind") if action else None,
        "action_value": action.get("value") if action else None,
        "action_label": action.get("label") if action else None,
        "confidence": operation_answer["confidence"],
        "probabilities": probabilities,
        "operation_probabilities": operation_answer["probabilities"],
        "target_probabilities": target_answer["probabilities"] if target_answer else {},
        "target_confidence": target_answer["confidence"] if target_answer else None,
        "raw_answers": result["answers"],
        "model": result["model"],
        "usage": result.get("usage", {}),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "request": body,
    }


def field_context(goal, action, page, history):
    return {
        "goal": goal,
        "field": {k: action.get(k) for k in ("label", "role", "value")},
        "page": {"title": page["title"], "text": page["text"][:6000]},
        "recent_actions": [{k: h.get(k) for k in ("action", "text")} for h in history[-6:]],
    }


def local_endpoint(base):
    return urlparse(base).hostname in {"localhost", "127.0.0.1", "::1"}


PROVIDERS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "opencode-go": "https://opencode.ai/zen/go/v1",
    "deepseek": "https://api.deepseek.com/v1",
}
OPENCODE_AUTH = Path.home() / ".local" / "share" / "opencode" / "auth.json"
# OpenCode Go routes and caches by conversation: it wants a client user agent and one session id per conversation.
SESSION_ID = os.environ.get("REVERIE_MODEL_SESSION") or uuid.uuid4().hex


def provider_headers(provider):
    if provider != "opencode-go":
        return {}
    from . import __version__

    return {"User-Agent": f"reverie/{__version__}", "x-opencode-session": SESSION_ID}


def opencode_go_key():
    """The OpenCode Go key: $OPENCODE_GO_API_KEY, else the one OpenCode stores in its auth.json."""
    key = os.environ.get("OPENCODE_GO_API_KEY")
    if key:
        return key
    path = Path(os.environ.get("OPENCODE_AUTH_FILE") or OPENCODE_AUTH)
    try:
        entry = json.loads(path.read_text()).get("opencode-go") or {}
    except (OSError, ValueError, AttributeError):
        return None
    return entry.get("key") if isinstance(entry, dict) else None


def endpoint(role="text"):
    """(base URL, API key, provider) for one model role.

    The text model reads TEXT_MODEL_PROVIDER, TEXT_MODEL_BASE_URL and TEXT_MODEL_API_KEY. The pilot reads
    LAYA_AGENT_PILOT_PROVIDER, LAYA_AGENT_PILOT_BASE_URL and LAYA_AGENT_PILOT_API_KEY, and falls back to the
    text model's settings for any it does not set. A provider (openrouter, opencode-go, deepseek) gives the
    base URL; opencode-go and openrouter also find their own key (OpenCode's auth.json, $OPENROUTER_API_KEY).
    An explicit base URL or key always wins."""
    prefixes = ["LAYA_AGENT_PILOT_", "TEXT_MODEL_"] if role == "pilot" else ["TEXT_MODEL_"]

    def first(name):
        for prefix in prefixes:
            value = os.environ.get(prefix + name)
            if value:
                return value
        return None

    provider = (first("PROVIDER") or "").strip().lower() or None
    if provider and provider not in PROVIDERS:
        raise ValueError(f"Unknown model provider {provider!r}; use one of {', '.join(sorted(PROVIDERS))}.")
    base = (first("BASE_URL") or PROVIDERS.get(provider) or PROVIDERS["deepseek"]).rstrip("/")
    key = first("API_KEY")
    if not provider:
        host = (urlparse(base).hostname or "").lower()
        provider = next((name for name, url in PROVIDERS.items() if urlparse(url).hostname == host), None)
    if not key and provider == "opencode-go":
        key = opencode_go_key()
    if not key and provider == "openrouter":
        key = os.environ.get("OPENROUTER_API_KEY")
    return base, key, provider


def reasoning_options(base, provider, reasoning_effort):
    no_reasoning = os.environ.get("TEXT_MODEL_REASONING") == "none" and reasoning_effort is None
    if local_endpoint(base):
        # Ollama, LM Studio and mlx_lm speak the plain OpenAI dialect.
        return {"reasoning_effort": "none"} if no_reasoning else {}
    if provider == "deepseek":
        return {"thinking": {"type": "disabled"}}
    effort = reasoning_effort or os.environ.get("TEXT_MODEL_EFFORT", "low")
    if provider == "openrouter" or provider is None:
        return {"reasoning": {"enabled": False}} if no_reasoning else {"reasoning": {"effort": effort}}
    # Other OpenAI-compatible gateways (OpenCode Go and similar) take the OpenAI field.
    return {} if no_reasoning else {"reasoning_effort": effort}


def chat_json(system, context, model=None, max_tokens=1024, reasoning_effort=None, images=(), role="text"):
    """One JSON-mode call to an OpenAI-compatible model. Local servers need no key.
    `model` overrides TEXT_MODEL for one call; `role="pilot"` uses the pilot's endpoint (see `endpoint`)."""
    base, key, provider = endpoint(role)
    if not key and not local_endpoint(base):
        raise ValueError("The text model needs TEXT_MODEL_API_KEY (or LAYA_AGENT_PILOT_API_KEY, or an opencode-go "
                         "key); no text is hardcoded or guessed by the executor.")
    model = model or os.environ.get("TEXT_MODEL", "deepseek-chat")
    reasoning = reasoning_options(base, provider, reasoning_effort)
    started = time.perf_counter()
    result = post_json(
        base + "/chat/completions",
        key or "local",
        {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            **reasoning,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": (
                [{"type": "text", "text": json.dumps(context)}]
                + [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}} for image in images]
            ) if images else json.dumps(context)}],
        },
        headers=provider_headers(provider),
    )
    choices = result.get("choices") if isinstance(result, dict) else None
    if not choices:  # Provider error bodies (rate limit, upstream failure) arrive without choices.
        raise ValueError(f"The text model returned no choices: {str(result)[:200]}")
    content = choices[0]["message"].get("content")
    if not content:  # Reasoning models can spend the whole budget thinking and return no answer.
        raise ValueError("The text model returned no content; nothing executed.")
    output = json.loads(content)
    return output, {
        "model": model,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "usage": result.get("usage", {}),
    }


def field_text(context):
    try:
        output, meta = chat_json(TEXT_VALUE, context)
        value = output["text"]
        if set(output) != {"text"} or not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError()
    except (ValueError, KeyError, TypeError) as error:
        if "TEXT_MODEL_API_KEY" in str(error):
            raise
        raise ValueError("Text helper returned no valid field value; nothing typed.") from None
    return value, meta


def plan_goal(goal, fields=(), attempts=3):
    """Once per task: the values the goal states, the item to open, and the visible finish condition.
    `fields` are the observed field labels, so requirements can name the field that sets them. No site plan."""
    context = {"goal": goal, "fields_on_page": list(fields)[:40]}
    for attempt in range(attempts):
        try:
            return parse_plan(*chat_json(GOAL_PLAN, context))
        except ValueError as error:
            if "TEXT_MODEL_API_KEY" in str(error) or attempt == attempts - 1:
                raise


def parse_plan(output, meta):
    try:
        requirements = [
            {"what": r["what"].strip(), "value": r["value"].strip()}
            for r in output["requirements"]
            if isinstance(r.get("what"), str) and isinstance(r.get("value"), str) and r["value"].strip()
        ]
        finish, item = output["finish"], output.get("open")
        if not isinstance(finish, str) or not finish.strip() or len(requirements) > 12:
            raise ValueError()
        item = item.strip() if isinstance(item, str) and item.strip() else None
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("Goal planner returned no valid plan; no action executed.") from None
    return {"requirements": requirements, "open": item, "finish": finish.strip()}, meta
