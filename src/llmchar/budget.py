"""Pre-run cost/token projector. Multiplies the exact call matrix by measured
input tokens and conservative output/reasoning estimates against live pricing.
THOROUGH is hard-gated on this; PILOT/BALANCED print and proceed."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .config import Config
from .openrouter import ModelInfo
from .prompts import render_variant, system_text
from .schema import CallSpec

BASE_OUTPUT_TOKENS = 240  # ~5 short JSON picks + envelope
SAFETY_BAND = 1.3


def _default_token_counter() -> Callable[[str], int]:
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return lambda s: len(enc.encode(s))
    except Exception:
        return lambda s: max(1, len(s) // 4)


def _price(pricing, model_id: str) -> tuple[float, float]:
    p = pricing.get(model_id)
    if p is None:
        return (0.0, 0.0)
    if isinstance(p, ModelInfo):
        return (p.prompt_price, p.completion_price)
    if isinstance(p, (tuple, list)):
        return (float(p[0]), float(p[1]))
    if isinstance(p, dict):
        return (float(p.get("prompt", 0)), float(p.get("completion", 0)))
    return (0.0, 0.0)


@dataclass
class ModelBudget:
    model_id: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class BudgetReport:
    tier: str
    panel: str
    per_model: list[ModelBudget] = field(default_factory=list)
    total_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_reasoning_tokens: int = 0
    cost_raw_usd: float = 0.0
    cost_banded_usd: float = 0.0
    gated: bool = False
    missing_prices: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "panel": self.panel,
            "gated": self.gated,
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_reasoning_tokens": self.total_reasoning_tokens,
            "cost_raw_usd": round(self.cost_raw_usd, 4),
            "cost_banded_usd": round(self.cost_banded_usd, 4),
            "safety_band": SAFETY_BAND,
            "missing_prices": self.missing_prices,
            "per_model": [vars(m) for m in self.per_model],
        }


def project(
    cfg: Config,
    tier_name: str,
    specs: list[CallSpec],
    pricing: dict,
    *,
    panel: str = "",
    token_counter: Callable[[str], int] | None = None,
) -> BudgetReport:
    tc = token_counter or _default_token_counter()
    in_cache: dict[tuple[str, str], int] = {}

    def input_tokens(spec: CallSpec) -> int:
        key = (spec.variant_id, spec.system_mode)
        if key not in in_cache:
            prompt = render_variant(cfg.prompts, spec.variant_id)
            sysmsg = system_text(cfg.prompts, spec.system_mode) or ""
            in_cache[key] = tc(prompt) + tc(sysmsg)
        return in_cache[key]

    rep = BudgetReport(
        tier=tier_name,
        panel=panel,
        gated=bool(cfg.tiers.get(tier_name, {}).get("gated", False)),
    )
    acc: dict[str, ModelBudget] = {}
    missing: set[str] = set()

    for s in specs:
        mb = acc.setdefault(s.model_id, ModelBudget(model_id=s.model_id))
        try:
            budget = cfg.models.by_id(s.model_id).reasoning_budget
        except KeyError:
            budget = {"low": 1500, "high": 6000}
        rtok = 0 if s.reasoning == "off" else int(budget.get(s.reasoning, 0))
        itok = input_tokens(s)
        otok = BASE_OUTPUT_TOKENS + rtok

        pp, pc = _price(pricing, s.model_id)
        if (pp, pc) == (0.0, 0.0):
            missing.add(s.model_id)
        mb.calls += 1
        mb.input_tokens += itok
        mb.output_tokens += otok
        mb.reasoning_tokens += rtok
        mb.cost_usd += itok * pp + otok * pc

    rep.per_model = sorted(acc.values(), key=lambda m: -m.cost_usd)
    rep.total_calls = sum(m.calls for m in rep.per_model)
    rep.total_input_tokens = sum(m.input_tokens for m in rep.per_model)
    rep.total_output_tokens = sum(m.output_tokens for m in rep.per_model)
    rep.total_reasoning_tokens = sum(m.reasoning_tokens for m in rep.per_model)
    rep.cost_raw_usd = sum(m.cost_usd for m in rep.per_model)
    rep.cost_banded_usd = rep.cost_raw_usd * SAFETY_BAND
    rep.missing_prices = sorted(missing)
    return rep
