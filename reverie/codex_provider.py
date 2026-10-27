"""JSON decisions through a persistent, restricted Codex app-server."""

import json
import math
import os
import queue
import subprocess
import tempfile
import threading
import time

DEFAULT_MODEL = "gpt-6.1-terra"


class CodexError(RuntimeError):
    """A terminal Codex provider failure; callers must not retry a decision."""


def _error(value):
    # Inspect only for known categories; never expose arbitrary server text.
    text = str(value).lower()
    if any(x in text for x in ("usage_limit", "usagelimit", "usage limit", "quota", "rate limit", "ratelimit")):
        return CodexError("Codex quota or rate limit reached; the run stopped.")
    if any(x in text for x in ("unauthorized", "authentication", "not logged", "not signed", "401")):
        return CodexError("Codex is not signed in or its login expired; run codex login.")
    if any(x in text for x in ("model not found", "model_not_found", "unsupported model", "model unavailable")):
        return CodexError("The requested Codex model is unavailable; check the model name and access.")
    return CodexError("Codex app-server failed; the run stopped.")


class _Client:
    def __init__(self):
        self.process = None
        self._lifecycle = threading.Lock()
        self._closed = False
        self.inbox = queue.Queue()
        self.next_id = 0
        self.threads = {}
        self.mcp_config = {}
        self.temp = tempfile.TemporaryDirectory(prefix="reverie-codex-")

    def start(self, deadline):
        command = os.environ.get("REVERIE_CODEX_COMMAND", "codex")
        # Config values override inherited integrations and model tools. Sandbox and
        # approval restrictions are repeated on the thread itself.
        config = [
            'model_provider="openai"', 'mcp_servers={}', 'web_search="disabled"',
            'features.shell_tool=false', 'features.unified_exec=false',
            'features.apps=false', 'features.plugins=false', 'features.multi_agent=false',
            'features.multi_agent_v2=false', 'features.view_image=false',
            'features.image_generation=false', 'features.computer_use=false',
            'features.browser_use=false', 'features.in_app_browser=false',
            'features.hooks=false', 'features.js_repl=false', 'features.code_mode=false',
            'features.skill_search=false', 'features.memories=false',
            'features.request_permissions_tool=false', 'features.sleep_tool=false',
        ]
        args = [command, "app-server"]
        for option in config:
            args.extend(["-c", option])
        with self._lifecycle:
            if self._closed:
                raise CodexError("Codex request was stopped.")
            try:
                self.process = subprocess.Popen(args, cwd=self.temp.name, stdin=subprocess.PIPE,
                                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                                text=True, bufsize=1)
            except OSError:
                raise CodexError("Cannot start Codex; install it or set REVERIE_CODEX_COMMAND.") from None
            stream = self.process.stdout
        threading.Thread(target=self._read, args=(stream,), daemon=True).start()
        self.request("initialize", {"clientInfo": {"name": "reverie", "version": "1"}}, deadline)
        self.send({"method": "initialized", "params": {}})
        config_result = self.request("config/read", {"includeLayers": False}, deadline)
        servers = config_result.get("config", {}).get("mcp_servers", {})
        if not isinstance(servers, dict):
            raise CodexError("Codex integration configuration could not be isolated.")
        self.mcp_config = {name: {"enabled": False} for name in servers}
        account = self.request("account/read", {"refreshToken": False}, deadline)
        if not isinstance(account.get("account"), dict) or account["account"].get("type") != "chatgpt":
            raise CodexError("Codex is not signed in with ChatGPT; run codex login.")

    def _read(self, stream):
        try:
            for line in stream:
                try:
                    self.inbox.put(json.loads(line))
                except (ValueError, TypeError):
                    self.inbox.put(None)
                    return
        except (OSError, ValueError):
            pass  # The owner can close the pipe while this reader is stopping.
        finally:
            self.inbox.put(None)

    def send(self, message):
        process = self.process
        if self._closed or process is None:
            raise CodexError("Codex request was stopped.")
        try:
            process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except (OSError, ValueError):
            raise CodexError("Codex app-server exited unexpectedly; the run stopped.") from None

    def receive(self, deadline):
        if self._closed:
            raise CodexError("Codex request was stopped.")
        try:
            message = self.inbox.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            raise CodexError("Codex request timed out; the run stopped.") from None
        if self._closed:
            raise CodexError("Codex request was stopped.")
        if not isinstance(message, dict):
            raise CodexError("Codex app-server returned an invalid response or exited.")
        if "method" in message and "id" in message:
            # No approvals, tool calls, or interactive requests are permitted.
            raise CodexError("Codex requested a tool or approval; the run stopped.")
        if message.get("method") in ("item/started", "item/completed"):
            item = message.get("params", {}).get("item", {})
            if item.get("type") in {"commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall",
                                     "collabAgentToolCall", "webSearch", "imageView", "imageGeneration"}:
                raise CodexError("Codex attempted to use a tool; the run stopped.")
        return message

    def request(self, method, params, deadline):
        self.next_id += 1
        request_id = self.next_id
        self.send({"id": request_id, "method": method, "params": params})
        while True:
            message = self.receive(deadline)
            if message.get("id") == request_id:
                if "error" in message:
                    raise _error(message["error"])
                result = message.get("result")
                if not isinstance(result, dict):
                    raise CodexError("Codex app-server returned an invalid response.")
                return result

    def chat(self, system, context, model, reasoning_effort, images, role, deadline):
        key = (role, system, model)
        if key not in self.threads:
            result = self.request("thread/start", {
                "model": model, "modelProvider": "openai", "cwd": self.temp.name,
                "approvalPolicy": "never", "sandbox": "read-only", "ephemeral": True,
                "config": {"mcp_servers": self.mcp_config},
                "baseInstructions": "You are a JSON decision worker. Respond only with a JSON object. Do not use tools.",
                "developerInstructions": system,
            }, deadline)
            thread = result.get("thread", {})
            if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
                raise CodexError("Codex did not create a decision thread.")
            self.threads[key] = thread["id"]
        thread_id = self.threads[key]
        inputs = [{"type": "text", "text": json.dumps(context, ensure_ascii=False)}]
        for image in images:
            if not isinstance(image, str):
                raise CodexError("Codex image input must be a base64 image string.")
            url = image if image.startswith("data:image/") else "data:image/jpeg;base64," + image
            inputs.append({"type": "image", "url": url})
        params = {"threadId": thread_id, "input": inputs, "model": model}
        if reasoning_effort:
            params["effort"] = reasoning_effort
        result = self.request("turn/start", params, deadline)
        turn = result.get("turn", {})
        turn_id = turn.get("id") if isinstance(turn, dict) else None
        if not turn_id:
            raise CodexError("Codex did not start a decision turn.")
        answer = None
        usage = {}
        while True:
            message = self.receive(deadline)
            method, p = message.get("method"), message.get("params", {})
            if not isinstance(p, dict) or p.get("threadId") != thread_id:
                continue
            if method == "item/completed" and p.get("turnId") == turn_id:
                item = p.get("item", {})
                if item.get("type") == "agentMessage":
                    answer = item.get("text")
            elif method == "thread/tokenUsage/updated" and p.get("turnId") == turn_id:
                usage = p.get("tokenUsage", {})
            elif method == "turn/completed" and p.get("turn", {}).get("id") == turn_id:
                finished = p["turn"]
                if finished.get("status") != "completed":
                    raise _error(finished.get("error"))
                if answer is None:
                    for item in finished.get("items", []):
                        if item.get("type") == "agentMessage":
                            answer = item.get("text")
                break
        try:
            output = json.loads(answer, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (TypeError, ValueError):
            raise CodexError("Codex returned malformed JSON; the run stopped.") from None
        if not isinstance(output, dict):
            raise CodexError("Codex returned a non-object JSON response; the run stopped.")
        return output, usage

    def close(self):
        with self._lifecycle:
            if self._closed:
                return
            self._closed = True
            process, self.process = self.process, None
        # Wake a request even if the child is unresponsive or has never started.
        self.inbox.put(None)
        if process is not None:
            if process.poll() is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=2)
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()
        self.temp.cleanup()


_turn_lock = threading.Lock()
_state_lock = threading.Lock()
_client = None
_generation = 0
_shutdown = False


def close():
    """Interrupt ongoing decisions and stop the app-server owned by this process."""
    global _client, _generation
    with _state_lock:
        _generation += 1
        client, _client = _client, None
    if client:
        client.close()


def shutdown():
    """Block new requests and interrupt any request already in progress."""
    global _client, _generation, _shutdown
    with _state_lock:
        _shutdown = True
        _generation += 1
        client, _client = _client, None
    if client:
        client.close()


def resume():
    """Permit requests for an explicitly started new session or run."""
    global _shutdown
    with _state_lock:
        _shutdown = False


def chat_json(system, context, model=DEFAULT_MODEL, max_tokens=1024, reasoning_effort=None, images=(), role="pilot"):
    """Return a JSON object and latency metadata using the signed-in Codex CLI."""
    global _client
    del max_tokens  # The app-server protocol does not expose a per-turn output-token limit.
    try:
        timeout = float(os.environ.get("REVERIE_CODEX_TIMEOUT", "120"))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError()
    except ValueError:
        raise CodexError("REVERIE_CODEX_TIMEOUT must be a positive number of seconds.") from None
    started = time.monotonic()
    deadline = started + timeout
    with _state_lock:
        if _shutdown:
            raise CodexError("Codex provider is shut down.")
        generation = _generation
    if not _turn_lock.acquire(timeout=timeout):
        raise CodexError("Codex request timed out waiting for another decision.")
    try:
        with _state_lock:
            if _shutdown or generation != _generation:
                raise CodexError("Codex request was stopped.")
            new_client = _client is None
            if new_client:
                _client = _Client()
            client = _client
        try:
            if new_client:
                client.start(deadline)
            output, usage = client.chat(system, context, model or DEFAULT_MODEL, reasoning_effort, images, role, deadline)
            with _state_lock:
                if generation != _generation:
                    raise CodexError("Codex request was stopped.")
        except Exception:
            with _state_lock:
                if _client is client:
                    _client = None
            client.close()
            raise
    finally:
        _turn_lock.release()
    return output, {"model": model or DEFAULT_MODEL, "latency_ms": round((time.monotonic() - started) * 1000),
                    "usage": usage}
