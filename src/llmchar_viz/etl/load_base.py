"""Loader for the base open-vocab sweep (data/raw/) and the new prod-vs-bare
runs (data/prodbare/), which share the CallRecord JSON schema.

The cached records have `parsed: null` (the parser version was bumped after the
run), so we re-parse `response.choices[0].message.content` with the ported
`parse_response` — zero new API calls, deterministic.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from llmchar.parse import parse_response

from .common import PickIn, RespIn, map_condition


def _content(rec: dict) -> str | None:
    resp = rec.get("response") or {}
    choices = resp.get("choices") or []
    if not choices:
        return None
    return (choices[0].get("message") or {}).get("content")


def load(data_root: Path, *, subdir: str = "raw",
         experiment: str = "base_selfid_open") -> Iterator[RespIn]:
    files = sorted((data_root / subdir).glob("*/*.json"))
    for fp in files:
        if "_archive" in fp.parts:
            continue
        try:
            rec = json.loads(fp.read_text())
        except (json.JSONDecodeError, OSError):
            continue  # skip partial/corrupt file (e.g. a concurrent write)
        spec = rec.get("spec", {})
        # pop1 / kind=control is a POPULARITY baseline (name famous characters), NOT
        # self-identification — exclude entirely so it never mixes with the picks.
        if spec.get("kind") == "control" or spec.get("variant_id") == "pop1":
            continue
        content = _content(rec)
        parsed, status = parse_response(content)

        picks: list[PickIn] = []
        refused = 0
        if parsed is not None:
            if parsed.refused:
                refused = 1
            for p in parsed.picks:
                picks.append(PickIn(
                    rank=p.rank,
                    raw_name=p.name,
                    real_or_fictional=p.real_or_fictional.value,
                    domain=p.domain,
                    explanation=p.explanation,
                ))

        condition, detail = map_condition(system_mode=spec.get("system_mode"))
        yield RespIn(
            source_key=rec.get("cache_key", fp.stem),
            model_id=spec.get("model_id", "unknown"),
            experiment=experiment,
            condition=condition,
            condition_detail=detail,
            variant=spec.get("variant_id", ""),
            temperature=_f(spec.get("temperature")),
            reasoning=spec.get("reasoning"),
            rep=spec.get("rep"),
            kind=spec.get("kind", "experiment"),
            system_text=rec.get("system_text"),
            prompt_text=rec.get("prompt_text", ""),
            response_content=content,
            parse_status=status.value,
            refused=refused,
            cost_usd=rec.get("cost_actual_usd"),
            latency_s=rec.get("latency_s"),
            timestamp=rec.get("timestamp"),
            picks=picks,
        )


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
