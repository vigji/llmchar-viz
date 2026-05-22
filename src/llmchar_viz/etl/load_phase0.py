"""Loader for phase0 single-character self-id (data/phase0/raw/{0b,0b5}).

Ministral-8B only, asked to name ONE fictional character, under S0/S1/S2
(= bare / Le Chat production / minimal). ~1/3 of records over-answered with a
ranked list; we take the rank-1 pick so phase0 stays one-pick-per-response.
Single-name task -> no explanation text (it does not feed the explanation map).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from llmchar.parse import parse_response

from .common import PickIn, RespIn, map_condition


def _system_and_prompt(messages: list[dict]) -> tuple[str | None, str]:
    system = None
    prompt = ""
    for m in messages or []:
        if m.get("role") == "system":
            system = m.get("content")
        elif m.get("role") == "user":
            prompt = m.get("content", "")
    return system, prompt


def load(data_root: Path, *, subdir: str = "phase0/raw") -> Iterator[RespIn]:
    files = sorted((data_root / subdir).glob("*/*.json"))
    for fp in files:
        rec = json.loads(fp.read_text())
        text = rec.get("response_text") or ""

        name = (rec.get("raw_name") or "").strip()
        if not name:
            parsed, _ = parse_response(text)
            if parsed and parsed.picks:
                name = parsed.picks[0].name.strip()

        refused = 1 if rec.get("refused") else 0
        picks = [] if (refused or not name) else [PickIn(rank=1, raw_name=name)]

        condition, detail = map_condition(system_id=rec.get("system_id"))
        system_text, prompt = _system_and_prompt(rec.get("messages", []))
        yield RespIn(
            source_key=rec.get("key", fp.stem),
            model_id=rec.get("model_id", "mistralai/ministral-8b-2512"),
            experiment="phase0_selfid_single",
            condition=condition,
            condition_detail=detail,
            variant=rec.get("paraphrase_id", rec.get("template", "")),
            temperature=_f(rec.get("temperature")),
            reasoning=None,
            rep=rec.get("rep"),
            kind="experiment",
            system_text=system_text,
            prompt_text=prompt,
            response_content=text,
            parse_status="refused" if refused else ("ok" if name else "failed"),
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
