"""Async OpenRouter client: retries, reasoning mapping, fidelity probe, cost.

provider.allow_fallbacks is pinned False so repetitions never silently mix
backends/quantizations (a real hidden confound). `usage.include` is requested
so we get authoritative cost + reasoning-token counts back."""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

BASE_URL = "https://openrouter.ai/api/v1"


def map_reasoning(level: str, budget: dict[str, int] | None = None) -> dict | None:
    # "off": omit the param entirely. {"enabled": false} is rejected by some
    # providers (-> spurious error + a misleading reasoning_dropped label).
    # Reasoning-default models may still think; the token budget covers that.
    if level == "off":
        return None
    if level in ("low", "high"):
        return {"effort": level}
    raise ValueError(f"bad reasoning level {level!r}")


@dataclass
class ChatResult:
    text: str
    reasoning_text: str
    raw: dict[str, Any]
    usage: dict[str, Any]
    reasoning_tokens: int
    cost: float | None
    latency_s: float
    attempts: int
    reasoning_dropped: bool = False


@dataclass
class ModelInfo:
    id: str
    prompt_price: float
    completion_price: float
    context_length: int
    supported_parameters: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def supports_reasoning(self) -> bool:
        return any(p in self.supported_parameters for p in ("reasoning", "include_reasoning"))


class OpenRouterError(RuntimeError):
    pass


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        max_concurrency: int = 6,
        timeout_s: int = 120,
        max_retries: int = 5,
        http_referer: str | None = None,
        x_title: str | None = None,
    ):
        if not api_key:
            raise OpenRouterError("OPENROUTER_API_KEY is not set")
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if http_referer:
            headers["HTTP-Referer"] = http_referer
        if x_title:
            headers["X-Title"] = x_title
        self._client = httpx.AsyncClient(headers=headers, timeout=timeout_s)
        self._sem = asyncio.Semaphore(max_concurrency)

    async def __aenter__(self) -> OpenRouterClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_models(self) -> dict[str, ModelInfo]:
        r = await self._client.get(f"{self.base_url}/models")
        r.raise_for_status()
        out: dict[str, ModelInfo] = {}
        for m in r.json().get("data", []):
            pr = m.get("pricing", {}) or {}
            out[m["id"]] = ModelInfo(
                id=m["id"],
                prompt_price=float(pr.get("prompt", 0) or 0),
                completion_price=float(pr.get("completion", 0) or 0),
                context_length=int(m.get("context_length", 0) or 0),
                supported_parameters=list(m.get("supported_parameters", []) or []),
                raw=m,
            )
        return out

    async def _post_chat(self, body: dict) -> httpx.Response:
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                r = await self._client.post(f"{self.base_url}/chat/completions", json=body)
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last_exc = e
            else:
                if r.status_code < 400:
                    r._llm_attempts = attempt  # type: ignore[attr-defined]
                    return r
                if r.status_code == 429 or r.status_code >= 500:
                    last_exc = OpenRouterError(f"HTTP {r.status_code}: {r.text[:300]}")
                    ra = r.headers.get("Retry-After")
                    if ra:
                        try:
                            delay = max(delay, float(ra))
                        except ValueError:
                            pass
                else:
                    raise OpenRouterError(f"HTTP {r.status_code}: {r.text[:500]}")
            if attempt < self.max_retries:
                await asyncio.sleep(delay + random.uniform(0, delay * 0.3))
                delay = min(delay * 2, 30.0)
        raise OpenRouterError(f"exhausted retries: {last_exc}")

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float,
        reasoning: dict | None,
        max_tokens: int,
    ) -> ChatResult:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "top_p": 1.0,
            "max_tokens": max_tokens,
            "provider": {"allow_fallbacks": False},
            "usage": {"include": True},
        }
        if reasoning is not None:
            body["reasoning"] = reasoning

        async def _attempt() -> tuple[dict, int, bool]:
            dropped = False
            try:
                resp = await self._post_chat(body)
            except OpenRouterError as e:
                if reasoning is not None and "reasoning" in str(e).lower():
                    body.pop("reasoning", None)
                    resp = await self._post_chat(body)
                    dropped = True
                else:
                    raise
            return resp.json(), getattr(resp, "_llm_attempts", 1), dropped

        def _content(d: dict) -> str:
            m = (d.get("choices") or [{}])[0].get("message", {}) or {}
            c = m.get("content")
            if isinstance(c, list):  # some providers return content parts
                c = "".join(p.get("text", "") for p in c if isinstance(p, dict))
            return c or ""

        # An HTTP-200 with empty content is common with rate-limited upstreams
        # (and pinned providers can't fall back). Retry it a couple of times
        # before giving up — this does not relax the no-fallback control.
        async with self._sem:
            t0 = time.monotonic()
            total_attempts = 0
            reasoning_dropped = False
            data: dict = {}
            for empty_try in range(3):
                data, att, drop = await _attempt()
                total_attempts += att
                reasoning_dropped = reasoning_dropped or drop
                if _content(data).strip():
                    break
                if empty_try < 2:
                    await asyncio.sleep(2.0 * (empty_try + 1) + random.uniform(0, 1))
            latency = time.monotonic() - t0

        content = _content(data)
        msg = (data.get("choices") or [{}])[0].get("message", {}) or {}
        usage = data.get("usage", {}) or {}
        details = usage.get("completion_tokens_details", {}) or {}
        rtok = int(details.get("reasoning_tokens", usage.get("reasoning_tokens", 0)) or 0)
        cost = usage.get("cost")
        return ChatResult(
            text=content,
            reasoning_text=msg.get("reasoning") or "",
            raw=data,
            usage=usage,
            reasoning_tokens=rtok,
            cost=float(cost) if cost is not None else None,
            latency_s=latency,
            attempts=total_attempts,
            reasoning_dropped=reasoning_dropped,
        )

    async def probe_reasoning(self, model: str) -> tuple[bool, int]:
        """One cheap high-effort probe. Returns (effective, reasoning_tokens).
        Effective == provider actually spent reasoning tokens."""
        try:
            res = await self.chat(
                model=model,
                messages=[{"role": "user", "content": "Reply with the single word: ok"}],
                temperature=0.0,
                reasoning={"effort": "high"},
                max_tokens=64,
            )
        except OpenRouterError:
            return False, 0
        return (res.reasoning_tokens > 0 and not res.reasoning_dropped), res.reasoning_tokens
