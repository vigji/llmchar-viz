"""Common intermediate rows emitted by every source loader.

Loaders stay pure: they extract raw picks only. Canonicalization (joining a raw
name to a `characters` row) happens later in build.py, after the augmented
aliases have been written — so the loaders carry no canonicalizer dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PickIn:
    rank: int
    raw_name: str
    real_or_fictional: str = "unsure"  # what the model said
    domain: str = ""
    explanation: str = ""


@dataclass
class RespIn:
    source_key: str
    model_id: str
    experiment: str
    condition: str               # bare | minimal | production
    condition_detail: str        # none | production_lechat | production_std | prod_*
    variant: str
    temperature: float | None
    reasoning: str | None
    rep: int | None
    kind: str
    system_text: str | None
    prompt_text: str
    response_content: str | None
    parse_status: str
    refused: int
    cost_usd: float | None
    latency_s: float | None
    timestamp: str | None
    persona: str | None = None
    picks: list[PickIn] = field(default_factory=list)


# system-mode / system-id  ->  (condition, condition_detail)
def map_condition(*, system_mode: str | None = None,
                  system_id: str | None = None,
                  system_condition: str | None = None,
                  production_variant: str | None = None) -> tuple[str, str]:
    if system_id is not None:  # phase0
        return {"S0": ("bare", "none"),
                "S1": ("production", "production_lechat"),
                "S2": ("minimal", "none")}[system_id]
    if system_condition is not None:  # phase2
        if system_condition == "production":
            return ("production", production_variant or "production")
        return (system_condition, "none")  # bare | minimal
    # base + prodbare use system_mode
    sm = system_mode or "none"
    if sm == "none":
        return ("bare", "none")
    if sm == "minimal":
        return ("minimal", "none")
    if sm.startswith("prod"):
        return ("production", sm)  # prod_mistral | prod_claude | prod_grok
    return (sm, "none")
