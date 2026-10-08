"""Runtime adapters for local Laya typed decisions."""

import atexit
import importlib.util
import os
import platform
import ssl
import sys
from typing import Protocol

import httpx

DEFAULT_LOCAL_DECISION_MODEL = "aac6fef/laya-typed-decisions-mlx"
DEFAULT_HTTP_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_HTTP_TIMEOUT = 30.0


class DecisionBackend(Protocol):
    """The transport-independent interface used by the browser policy."""

    model_name: str

    def system_one(self, state, questions): ...


class LayaMlxBackend:
    def __init__(self, model_name: str):
        try:
            import laya_mlx
        except (ImportError, OSError) as error:
            raise RuntimeError(
                "LAYA_BACKEND=mlx requires the optional MLX dependencies on Apple Silicon. "
                "Install them with `uv sync --extra mlx` or set LAYA_BACKEND=http."
            ) from error

        print("Laya decision backend: MLX", flush=True)
        print(f"Laya model: {model_name}", flush=True)
        self.model_name = model_name
        self._model = laya_mlx.load(model_name)
        self._model.system_one(
            "Warm up.",
            {"q": {"type": "choice", "instructions": "Warm up.", "criteria": ["a", "b"]}},
        )

    def system_one(self, state, questions):
        return self._model.system_one(state, questions)


class LayaHttpBackend:
    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.model_name = "laya-typed-decisions"
        self._reported_model = False
        ca_file = os.environ.get("LAYA_TLS_CA")
        try:
            verify = ssl.create_default_context(cafile=ca_file) if ca_file else True
        except OSError as error:
            raise RuntimeError(f"Unable to load the Laya TLS CA file at {ca_file}.") from error
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, verify=verify)
        atexit.register(self._client.close)

        print("Laya decision backend: HTTP", flush=True)
        print(f"Laya endpoint: {self.base_url}", flush=True)
        self._check_health()
        self.system_one(
            "Warm up.",
            {"q": {"type": "choice", "instructions": "Warm up.", "criteria": ["a", "b"]}},
        )

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as error:
            raise RuntimeError(
                f"Local Laya service at {self.base_url} timed out after {self.timeout:g} seconds. "
                "No browser action was executed."
            ) from error
        except httpx.HTTPError as error:
            raise RuntimeError(
                f"Unable to reach local Laya service at {self.base_url}. "
                "Start laya.cpp or change LAYA_BASE_URL."
            ) from error

        if response.status_code == 422:
            raise RuntimeError(f"Laya rejected the decision request (HTTP 422): {self._error_detail(response)}")
        if response.status_code == 503:
            raise RuntimeError(
                f"Local Laya service at {self.base_url} is unavailable or overloaded (HTTP 503). "
                "No browser action was executed."
            )
        if response.is_error:
            raise RuntimeError(
                f"Local Laya service at {self.base_url} returned HTTP {response.status_code}: "
                f"{self._error_detail(response)}"
            )
        return response

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
            detail = payload.get("error", payload) if isinstance(payload, dict) else payload
            if isinstance(detail, dict):
                detail = detail.get("message", detail)
            return str(detail)[:500]
        except ValueError:
            return response.text[:500] or "empty response"

    def _check_health(self):
        response = self._request("GET", "/health")
        try:
            health = response.json()
        except ValueError as error:
            raise RuntimeError(f"Laya health endpoint at {self.base_url} returned malformed JSON.") from error
        if not isinstance(health, dict) or health.get("status") != "ok":
            raise RuntimeError(f"Laya service at {self.base_url} is not ready: {health!r}")
        if isinstance(health.get("model"), str):
            self.model_name = health["model"]
        print("Laya service: ready", flush=True)

    def system_one(self, state, questions):
        response = self._request("POST", "/v1/systemone", json={"state": state, "questions": questions})
        try:
            result = response.json()
            answers = result["answers"]
            input_tokens = result["usage"]["input_tokens"]
            if (
                not isinstance(answers, dict)
                or isinstance(input_tokens, bool)
                or not isinstance(input_tokens, (int, float))
            ):
                raise TypeError
        except (ValueError, KeyError, TypeError) as error:
            raise RuntimeError(
                f"Local Laya service at {self.base_url} returned a malformed decision response; "
                "no browser action was executed."
            ) from error

        if isinstance(result.get("model"), str):
            self.model_name = result["model"]
        if not self._reported_model:
            print(f"Laya model: {self.model_name}", flush=True)
            self._reported_model = True
        return result


def _auto_backend() -> str:
    mlx_compatible = sys.platform == "darwin" and platform.machine() == "arm64"
    return "mlx" if mlx_compatible and importlib.util.find_spec("laya_mlx") else "http"


def create_backend() -> DecisionBackend:
    backend = os.environ.get("LAYA_BACKEND", "auto").strip().lower()
    if backend == "auto":
        backend = _auto_backend()
    if backend == "mlx":
        model = os.environ.get("LOCAL_DECISION_MODEL", DEFAULT_LOCAL_DECISION_MODEL)
        return LayaMlxBackend(model)
    if backend == "http":
        try:
            timeout = float(os.environ.get("LAYA_HTTP_TIMEOUT", str(DEFAULT_HTTP_TIMEOUT)))
        except ValueError as error:
            raise ValueError("LAYA_HTTP_TIMEOUT must be a number of seconds.") from error
        if timeout <= 0:
            raise ValueError("LAYA_HTTP_TIMEOUT must be greater than zero.")
        return LayaHttpBackend(os.environ.get("LAYA_BASE_URL", DEFAULT_HTTP_BASE_URL), timeout)
    raise ValueError("LAYA_BACKEND must be one of: auto, http, mlx.")


def configured_backend_label() -> str:
    backend = os.environ.get("LAYA_BACKEND", "auto").strip().lower()
    backend = _auto_backend() if backend == "auto" else backend
    if backend == "http":
        return f"Laya HTTP ({os.environ.get('LAYA_BASE_URL', DEFAULT_HTTP_BASE_URL)})"
    model = os.environ.get("LOCAL_DECISION_MODEL", DEFAULT_LOCAL_DECISION_MODEL)
    return model.split("/")[-1]
