"""Loader for phase2 dark-persona / latent-values probes (data/phase2/raw/conf).

Free-text answers (no character picks) across bare/minimal/production for
Ministral 3B/8B/14B + peers. Kept for full-text search and the per-condition
refusal signal; contributes responses but no picks.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from llmchar.parse import is_refusal_text

from .common import RespIn, map_condition


def load(data_root: Path, *, subdir: str = "phase2/raw") -> Iterator[RespIn]:
    files = sorted((data_root / subdir).glob("**/*.json"))
    for fp in files:
        rec = json.loads(fp.read_text())
        text = rec.get("response_text") or ""
        condition, detail = map_condition(
            system_condition=rec.get("system_condition"),
            production_variant=rec.get("production_variant"),
        )
        yield RespIn(
            source_key=rec.get("key", fp.stem),
            model_id=rec.get("model_id", "unknown"),
            experiment="phase2_darkpersona",
            condition=condition,
            condition_detail=detail,
            variant=rec.get("item_id") or rec.get("question_id", ""),
            temperature=_f(rec.get("temperature")),
            reasoning=None,
            rep=rec.get("rep"),
            kind="experiment",
            persona=rec.get("persona_id"),
            system_text=rec.get("system_text"),
            prompt_text=rec.get("probe_text", ""),
            response_content=text,
            parse_status="refused" if is_refusal_text(text) else "ok",
            refused=1 if is_refusal_text(text) else 0,
            cost_usd=rec.get("cost_actual_usd"),
            latency_s=rec.get("latency_s"),
            timestamp=rec.get("timestamp"),
            picks=[],
        )


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
