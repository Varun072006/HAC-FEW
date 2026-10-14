"""Provider-independent model gateway.

What exists: an Ollama adapter (local), an OpenAI-compatible adapter (any /chat/completions server;
optional, needs a base URL and key), and a scripted provider for tests and offline demos. All real
calls go through httpx with a hard timeout and bounded rate-limit handling.

Usage accounting is honest about provenance: tokens reported by the provider are `provider`;
when a provider reports none the gateway estimates from text length and says so (`estimated`).
Nothing here computes a cost: prices differ per deployment and are not guessed.

Not implemented (deliberately): response caching. A cache must be keyed by tenant, user authorization
and data freshness, and none of those boundaries exist yet, so a shared cache would be unsafe."""
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import httpx
from pydantic import BaseModel, ValidationError


# ------------------------------------------------------------------ types
@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    provider_reported_calls: int = 0
    estimated_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def source(self) -> str:
        if self.calls == 0:
            return "none"
        if self.estimated_calls == 0:
            return "provider"
        return "estimated" if self.provider_reported_calls == 0 else "mixed"

    def add(self, other: "Usage") -> None:
        for f in ("calls", "input_tokens", "output_tokens", "provider_reported_calls", "estimated_calls"):
            setattr(self, f, getattr(self, f) + getattr(other, f))

    def to_dict(self) -> dict:
        return {"calls": self.calls, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens, "source": self.source,
                "provider_reported_calls": self.provider_reported_calls, "estimated_calls": self.estimated_calls,
                "cost_usd": None}

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "Usage":
        d = d or {}
        return cls(*(int(d.get(k, 0) or 0) for k in ("calls", "input_tokens", "output_tokens",
                                                     "provider_reported_calls", "estimated_calls")))


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class ProviderError(Exception):
    """kind: unavailable | timeout | rate_limited | auth | bad_response | http_error | not_configured"""

    def __init__(self, kind: str, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.kind in ("unavailable", "timeout", "rate_limited")


class BudgetExceeded(Exception):
    pass


@dataclass
class ModelRequest:
    system: str
    messages: list[dict]                 # [{"role": "user"|"assistant", "content": str}]
    json_mode: bool = True
    max_output_tokens: int = 1024
    temperature: float = 0.0
    timeout_s: float = 60.0
    model: Optional[str] = None


@dataclass
class ModelResponse:
    text: str
    usage: Usage
    provider: str
    model: str
    latency_ms: int


# ------------------------------------------------------------------ providers
class Provider:
    name = "base"

    def complete(self, req: ModelRequest) -> ModelResponse:  # pragma: no cover - interface
        raise NotImplementedError

    def available(self) -> tuple[bool, str]:
        return True, "ok"


def _map_http_error(exc: Exception) -> ProviderError:
    if isinstance(exc, httpx.TimeoutException):
        return ProviderError("timeout", "Provider request timed out.")
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 429:
            try:
                ra = float(exc.response.headers.get("retry-after", ""))
            except ValueError:
                ra = None
            return ProviderError("rate_limited", "Provider rate limit reached.", retry_after=ra)
        if code in (401, 403):
            return ProviderError("auth", f"Provider rejected the credentials (HTTP {code}).")
        if code >= 500:
            return ProviderError("unavailable", f"Provider error (HTTP {code}).")
        return ProviderError("http_error", f"Provider returned HTTP {code}.")
    return ProviderError("unavailable", f"Provider unreachable: {type(exc).__name__}")


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, base_url: Optional[str] = None, transport: Optional[httpx.BaseTransport] = None):
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
        self._transport = transport

    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=timeout, transport=self._transport)

    def available(self) -> tuple[bool, str]:
        try:
            with self._client(2.0) as c:
                c.get("/api/tags").raise_for_status()
            return True, "reachable"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {self.base_url} not reachable"

    def complete(self, req: ModelRequest) -> ModelResponse:
        if not req.model:
            raise ProviderError("not_configured", "No model name configured for the ollama provider.")
        body = {"model": req.model, "stream": False,
                "messages": [{"role": "system", "content": req.system}, *req.messages],
                "options": {"temperature": req.temperature, "num_predict": req.max_output_tokens}}
        if req.json_mode:
            body["format"] = "json"
        t0 = time.perf_counter()
        try:
            with self._client(req.timeout_s) as c:
                r = c.post("/api/chat", json=body)
                r.raise_for_status()
                payload = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise _map_http_error(exc) if isinstance(exc, httpx.HTTPError) else ProviderError("bad_response", "Non-JSON reply.")
        text = (payload.get("message") or {}).get("content")
        if not isinstance(text, str):
            raise ProviderError("bad_response", "Provider reply had no message content.")
        return ModelResponse(text, _usage(req, text, payload.get("prompt_eval_count"), payload.get("eval_count")),
                             self.name, req.model, int((time.perf_counter() - t0) * 1000))


class OpenAICompatProvider(Provider):
    name = "openai_compatible"

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None,
                 transport: Optional[httpx.BaseTransport] = None):
        self.base_url = (base_url or os.getenv("HACFEW_OPENAI_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.getenv("HACFEW_OPENAI_API_KEY") or ""
        self._transport = transport

    def available(self) -> tuple[bool, str]:
        if not self.base_url:
            return False, "HACFEW_OPENAI_BASE_URL is not set"
        return True, "configured (not probed)"

    def complete(self, req: ModelRequest) -> ModelResponse:
        if not self.base_url:
            raise ProviderError("not_configured", "HACFEW_OPENAI_BASE_URL is not set.")
        if not req.model:
            raise ProviderError("not_configured", "No model name configured for the openai_compatible provider.")
        body: dict[str, Any] = {"model": req.model, "temperature": req.temperature, "max_tokens": req.max_output_tokens,
                                "messages": [{"role": "system", "content": req.system}, *req.messages]}
        if req.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        t0 = time.perf_counter()
        try:
            with httpx.Client(base_url=self.base_url, timeout=req.timeout_s, transport=self._transport,
                              headers=headers) as c:
                r = c.post("/chat/completions", json=body)
                r.raise_for_status()
                payload = r.json()
            text = payload["choices"][0]["message"]["content"]
        except httpx.HTTPError as exc:
            raise _map_http_error(exc)
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError("bad_response", "Provider reply did not match the chat-completions shape.")
        u = payload.get("usage") or {}
        return ModelResponse(text or "", _usage(req, text or "", u.get("prompt_tokens"), u.get("completion_tokens")),
                             self.name, req.model, int((time.perf_counter() - t0) * 1000))


class ScriptedProvider(Provider):
    """Deterministic provider for tests and offline demos. `script` is a list of replies (str, dict,
    or an exception to raise) consumed in order, or a callable(request, call_index) returning one."""
    name = "scripted"

    def __init__(self, script: Any = (), report_usage: bool = True):
        self.script, self.calls, self.requests, self.report_usage = script, 0, [], report_usage

    def complete(self, req: ModelRequest) -> ModelResponse:
        i = self.calls
        self.calls += 1
        self.requests.append(req)
        item = self.script(req, i) if callable(self.script) else (self.script[i] if i < len(self.script) else None)
        if item is None:
            raise ProviderError("unavailable", "Scripted provider ran out of replies.")
        if isinstance(item, Exception):
            raise item
        text = item if isinstance(item, str) else json.dumps(item)
        pt = estimate_tokens(req.system + "".join(m["content"] for m in req.messages)) if self.report_usage else None
        ct = estimate_tokens(text) if self.report_usage else None
        return ModelResponse(text, _usage(req, text, pt, ct), self.name, req.model or "scripted", 1)


def _usage(req: ModelRequest, text: str, prompt_tokens: Any, completion_tokens: Any) -> Usage:
    if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
        return Usage(1, prompt_tokens, completion_tokens, provider_reported_calls=1)
    pin = estimate_tokens(req.system + "".join(m["content"] for m in req.messages))
    return Usage(1, pin, estimate_tokens(text), estimated_calls=1)


# ------------------------------------------------------------------ gateway
_providers: dict[str, Provider] = {}


def register_provider(name: str, provider: Provider) -> None:
    _providers[name] = provider


def reset_providers() -> None:
    _providers.clear()


def get_provider(name: str) -> Provider:
    if name in _providers:
        return _providers[name]
    if name == "ollama":
        return OllamaProvider()
    if name == "openai_compatible":
        return OpenAICompatProvider()
    raise ProviderError("not_configured", f"Provider '{name}' is not configured.")


def provider_status() -> list[dict]:
    out = []
    for name in ("ollama", "openai_compatible"):
        ok, detail = get_provider(name).available()
        out.append({"provider": name, "available": ok, "detail": detail})
    out += [{"provider": n, "available": True, "detail": "registered in-process"} for n in _providers
            if n not in ("ollama", "openai_compatible")]
    return out


def select_model(cfg: dict, complexity: str = "medium") -> str:
    """Per-agent model configuration with tiering: small models for routine work, larger ones only
    when the task is marked high-complexity and the agent defines such a tier."""
    tiers = cfg.get("tiers") or {}
    tier = {"low": "small", "medium": "default", "high": "large"}.get(complexity, "default")
    return tiers.get(tier) or cfg.get("model") or tiers.get("small") or ""


class Gateway:
    """One gateway per task execution, so budgets and usage are scoped to that task."""

    def __init__(self, cfg: dict, complexity: str = "medium", max_total_tokens: int = 20000,
                 max_calls: int = 6, deadline: Optional[float] = None,
                 cancelled: Callable[[], bool] = lambda: False,
                 on_call: Optional[Callable[[dict], None]] = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.cfg, self.complexity = cfg, complexity
        self.max_total_tokens, self.max_calls, self.deadline = max_total_tokens, max_calls, deadline
        self.cancelled, self.on_call, self.sleep = cancelled, on_call, sleep
        self.usage = Usage()
        self.last_error: Optional[ProviderError] = None

    def _check_budget(self, req: ModelRequest) -> None:
        if self.usage.calls >= self.max_calls:
            raise BudgetExceeded(f"Model call budget of {self.max_calls} exhausted.")
        projected = self.usage.total_tokens + estimate_tokens(req.system + "".join(m["content"] for m in req.messages))
        if projected > self.max_total_tokens:
            raise BudgetExceeded(f"Token budget of {self.max_total_tokens} would be exceeded "
                                 f"(used {self.usage.total_tokens}, request needs about "
                                 f"{projected - self.usage.total_tokens}).")

    def _call(self, provider_name: str, model: str, req: ModelRequest) -> ModelResponse:
        provider = get_provider(provider_name)
        attempts = 0
        while True:
            if self.cancelled():
                raise ProviderError("unavailable", "Cancelled.")
            remaining = (self.deadline - time.monotonic()) if self.deadline else req.timeout_s
            if remaining <= 0:
                raise ProviderError("timeout", "Task deadline reached before the model call.")
            call = ModelRequest(req.system, req.messages, req.json_mode, req.max_output_tokens, req.temperature,
                                min(req.timeout_s, remaining), model)
            try:
                return provider.complete(call)
            except ProviderError as exc:
                attempts += 1
                if exc.kind == "rate_limited" and attempts <= 2:
                    self.sleep(min(exc.retry_after if exc.retry_after is not None else 0.5 * attempts, 5.0))
                    continue
                raise

    def complete(self, req: ModelRequest) -> ModelResponse:
        self._check_budget(req)
        primary = (self.cfg.get("provider") or "deterministic", select_model(self.cfg, self.complexity))
        fb = self.cfg.get("fallback")
        chain = [primary] + ([(fb["provider"], fb.get("model") or "")] if fb else [])
        last: Optional[ProviderError] = None
        for provider_name, model in chain:
            try:
                resp = self._call(provider_name, model, req)
            except ProviderError as exc:
                last = self.last_error = exc
                if self.on_call:
                    self.on_call({"provider": provider_name, "model": model, "ok": False, "error_kind": exc.kind})
                if exc.kind in ("auth", "http_error", "bad_response") and len(chain) == 1:
                    raise
                continue
            self.usage.add(resp.usage)
            if self.on_call:
                self.on_call({"provider": resp.provider, "model": resp.model, "ok": True, "latency_ms": resp.latency_ms,
                              "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens,
                              "usage_source": resp.usage.source, "fallback": (provider_name, model) != primary})
            return resp
        raise last or ProviderError("unavailable", "No provider available.")

    def complete_structured(self, req: ModelRequest, model_cls: type[BaseModel], max_repairs: int = 1) -> BaseModel:
        """Ask for JSON, validate it against a pydantic model; on a malformed reply allow a bounded
        number of repair attempts that quote only the validation error, never the unvalidated content."""
        messages = list(req.messages)
        last_error = "unknown"
        for attempt in range(max_repairs + 1):
            resp = self.complete(ModelRequest(req.system, messages, True, req.max_output_tokens, req.temperature,
                                              req.timeout_s, req.model))
            try:
                return model_cls.model_validate_json(_extract_json(resp.text))
            except (ValidationError, ValueError) as exc:
                last_error = _short(exc)
                messages = messages + [{"role": "assistant", "content": resp.text[:2000]},
                                       {"role": "user", "content": "That reply was not valid. Reply with ONLY a JSON "
                                                                   f"object that satisfies the schema. Problem: {last_error}"}]
        raise ProviderError("bad_response", f"Model output failed validation after {max_repairs + 1} attempt(s): {last_error}")


def _extract_json(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("\n") + 1:] if "\n" in t else t
        t = t.rsplit("```", 1)[0] if "```" in t else t
    start, end = t.find("{"), t.rfind("}")
    return t[start:end + 1] if start != -1 and end > start else t


def _short(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
    return str(exc)[:300]
