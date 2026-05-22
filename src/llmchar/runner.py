"""Resumable async orchestration. data/raw is the system of record, so a run
only issues calls for cache misses; re-running after an interruption (or a tier
upgrade) is safe and cheap. Honors the soft max_usd ceiling and the hard
THOROUGH budget gate."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from .cache import SCHEMA_VERSION, Cache, cache_key, request_fingerprint
from .config import Config, Settings
from .openrouter import OpenRouterClient, map_reasoning
from .parse import PARSER_VERSION, parse_response
from .prompts import render_variant, system_text
from .schema import CallRecord, CallSpec


def load_validate_snapshot(cfg: Config) -> dict:
    p = cfg.data_dir / "derived" / "validate.json"
    if p.is_file():
        return json.loads(p.read_text())
    return {}


def _effective_maps(cfg: Config, snap: dict) -> tuple[dict[str, bool], dict[str, float], dict]:
    models = snap.get("models", {})
    reasoning_eff = {k: bool(v.get("reasoning_effective")) for k, v in models.items()}
    max_temp = {k: float(v["max_temperature"]) for k, v in models.items() if v.get("max_temperature")}
    pricing = {
        k: (float(v.get("prompt_price", 0)), float(v.get("completion_price", 0)))
        for k, v in models.items()
    }
    return reasoning_eff, max_temp, pricing


def build_messages(cfg: Config, spec: CallSpec) -> tuple[list[dict], str, str | None]:
    prompt = render_variant(cfg.prompts, spec.variant_id)
    sysmsg = system_text(cfg.prompts, spec.system_mode)
    messages: list[dict] = []
    if sysmsg:
        messages.append({"role": "system", "content": sysmsg})
    messages.append({"role": "user", "content": prompt})
    return messages, prompt, sysmsg


def key_for(cfg: Config, spec: CallSpec) -> tuple[str, str, str | None, dict | None, int]:
    _, prompt, sysmsg = build_messages(cfg, spec)
    max_tokens = cfg.experiment.max_tokens_floor
    rparam = map_reasoning(spec.reasoning)
    rfp = request_fingerprint(max_tokens, rparam)
    k = cache_key(
        spec,
        prompt_text=prompt,
        system_text=sysmsg,
        schema_version=SCHEMA_VERSION,
        parser_version=PARSER_VERSION,
        req_fingerprint=rfp,
    )
    return k, prompt, sysmsg, rparam, max_tokens


def new_run_dir(cfg: Config) -> tuple[str, Path]:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    rd = cfg.data_dir / "runs" / run_id
    rd.mkdir(parents=True, exist_ok=True)
    (cfg.data_dir / "runs" / "latest.txt").write_text(run_id)
    return run_id, rd


async def run_tier(
    cfg: Config,
    tier_name: str,
    specs: list[CallSpec],
    *,
    confirm_budget: bool = False,
    progress_cb=None,
) -> dict:
    tier = cfg.tiers[tier_name]
    if tier.get("gated") and not confirm_budget:
        return {"status": "gated", "reason": "THOROUGH requires --confirm-budget", "calls": len(specs)}

    settings = Settings.from_env()
    cache = Cache(cfg.data_dir)
    run_id, rd = new_run_dir(cfg)

    # plan: split hits / misses
    planned = [(s, *key_for(cfg, s)) for s in specs]
    misses = [
        (s, k, p, sy, rp, mt)
        for (s, k, p, sy, rp, mt) in planned
        if not cache.is_terminal(s.model_id, k)  # retries transient transport failures
    ]
    hits = len(planned) - len(misses)

    (rd / "call_plan.jsonl").write_text(
        "".join(json.dumps({"spec": s.model_dump(mode="json"), "cache_key": k}) + "\n" for s, k, *_ in planned)
    )
    manifest = {
        "run_id": run_id,
        "tier": tier_name,
        "total": len(planned),
        "cache_hits": hits,
        "to_run": len(misses),
        "parser_version": PARSER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "started_at": datetime.now(UTC).isoformat(),
    }
    (rd / "manifest.json").write_text(json.dumps(manifest, indent=2))

    if not misses:
        return {"status": "complete", "run_id": run_id, "cache_hits": hits, "ran": 0, "spent_usd": 0.0}

    snap = load_validate_snapshot(cfg)
    _, _, pricing = _effective_maps(cfg, snap)
    ceiling = cfg.experiment.max_usd
    spent_run = 0.0
    base_spent = cache.total_actual_cost()
    prog = (rd / "progress.jsonl").open("a")
    done = {"n": 0, "errors": 0, "aborted": False}
    lock = asyncio.Lock()

    async with OpenRouterClient(
        settings.openrouter_api_key or "",
        max_concurrency=cfg.experiment.max_concurrency,
        timeout_s=cfg.experiment.request_timeout_s,
        max_retries=cfg.experiment.max_retries,
        http_referer=settings.http_referer,
        x_title=settings.x_title,
    ) as client:

        async def one(item):
            nonlocal spent_run
            s, k, prompt, sysmsg, rparam, mt = item
            if done["aborted"]:
                return
            async with lock:
                if ceiling is not None and (base_spent + spent_run) >= ceiling:
                    done["aborted"] = True
                    return
            messages, _, _ = build_messages(cfg, s)
            mspec = cfg.models.by_id(s.model_id)
            rec = CallRecord(
                cache_key=k,
                spec=s,
                model_family=mspec.family,
                scale_tier=mspec.scale_tier,
                prompt_text=prompt,
                system_text=sysmsg,
                request={"model": s.model_id, "temperature": s.temperature, "reasoning": rparam, "max_tokens": mt},
            )
            try:
                res = await client.chat(
                    model=s.model_id,
                    messages=messages,
                    temperature=s.temperature,
                    reasoning=rparam,
                    max_tokens=mt,
                )
                parsed, status = parse_response(res.text)
                pp, pc = pricing.get(s.model_id, (0.0, 0.0))
                computed = (
                    res.usage.get("prompt_tokens", 0) * pp
                    + res.usage.get("completion_tokens", 0) * pc
                )
                rec.response = res.raw
                rec.parsed = parsed
                rec.parse_status = status
                rec.usage = res.usage
                rec.cost_actual_usd = res.cost if res.cost is not None else round(computed, 6)
                rec.latency_s = res.latency_s
                rec.reasoning_returned_tokens = res.reasoning_tokens
                rec.attempt_count = res.attempts
                if parsed is None and not res.text.strip():
                    # empty 200 from a (pinned) rate-limited upstream: a soft
                    # failure, not a model answer -> transient, retried later.
                    rec.error = "empty_response_from_provider"
                elif res.reasoning_dropped:
                    rec.error = "reasoning_dropped_by_provider"
            except Exception as e:  # noqa: BLE001 — transport/None => recorded 'failed'
                rec.parse_status = rec.parse_status  # failed
                rec.error = f"{type(e).__name__}: {e}"
            cache.store(rec)
            async with lock:
                spent_run += rec.cost_actual_usd or 0.0
                done["n"] += 1
                if rec.error and rec.parsed is None:
                    done["errors"] += 1
                prog.write(json.dumps({
                    "i": done["n"], "model": s.model_id, "variant": s.variant_id,
                    "status": rec.parse_status.value, "cost": rec.cost_actual_usd,
                    "err": rec.error,
                }) + "\n")
                prog.flush()
                if progress_cb:
                    progress_cb(done["n"], len(misses), base_spent + spent_run)

        # interleave models so we don't hammer one provider
        ordered = sorted(misses, key=lambda it: (it[0].rep, it[0].model_id, it[0].variant_id))
        await asyncio.gather(*(one(it) for it in ordered))

    prog.close()
    status = "aborted_max_usd" if done["aborted"] else "complete"
    summary = {
        "status": status,
        "run_id": run_id,
        "cache_hits": hits,
        "ran": done["n"],
        "errors": done["errors"],
        "spent_usd": round(spent_run, 4),
        "cumulative_usd": round(base_spent + spent_run, 4),
    }
    (rd / "manifest.json").write_text(json.dumps({**manifest, **summary}, indent=2))
    return summary
