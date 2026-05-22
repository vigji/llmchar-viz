"""Tier -> list[CallSpec]. THE single source of truth for what gets called and
how many calls. tests/test_matrix.py pins the counts so the design can't drift.

- grid   design: full cross variants x temps x reasoning x reps.
- sparse design: per (model,variant): `reasoning_at_reference` cells at the
  reference temperature, plus each `extra_temperature` at reasoning=off; every
  cell repeated `reps` times. Plus optional system-prompt-contrast cell and a
  popularity-baseline control, both per model.

reasoning levels low/high are dropped for a model unless reasoning is
*effective* for it; temperatures above a model's max are dropped (never
imputed)."""

from __future__ import annotations

from collections.abc import Mapping

from .config import Config, ModelSpec
from .schema import CallSpec, Kind


def _reasoning_effective(models, override: Mapping[str, bool] | None) -> dict[str, bool]:
    eff = {m.id: m.reasoning for m in models}
    if override:
        eff.update(override)
    return eff


def _max_temp(models, override: Mapping[str, float] | None) -> dict[str, float]:
    mt = {m.id: m.max_temperature for m in models}
    if override:
        mt.update(override)
    return mt


def _panel(cfg: Config, tier: dict, panel_override: str | None) -> list[ModelSpec]:
    name = panel_override or tier["default_panel"]
    return cfg.models.panel(name)


def expand(
    cfg: Config,
    tier_name: str,
    *,
    panel_override: str | None = None,
    reasoning_effective: Mapping[str, bool] | None = None,
    max_temperature: Mapping[str, float] | None = None,
) -> list[CallSpec]:
    if tier_name not in cfg.tiers:
        raise KeyError(f"unknown tier {tier_name!r}; have {list(cfg.tiers)}")
    tier = cfg.tiers[tier_name]
    design = tier["design"]
    panel = _panel(cfg, tier, panel_override)
    eff = _reasoning_effective(panel, reasoning_effective)
    mt = _max_temp(panel, max_temperature)
    system_mode = tier.get("system_modes", ["none"])[0]

    specs: list[CallSpec] = []

    def emit(mid, vid, smode, temp, reasoning, reps, kind):
        for rep in range(reps):
            specs.append(
                CallSpec(
                    model_id=mid,
                    variant_id=vid,
                    system_mode=smode,
                    temperature=float(temp),
                    reasoning=reasoning,
                    rep=rep,
                    kind=kind,
                )
            )

    if design["type"] == "grid":
        for m in panel:
            for vid in design["variants"]:
                for temp in design["temperatures"]:
                    if temp > mt[m.id]:
                        continue
                    for r in design["reasoning"]:
                        if r != "off" and not eff[m.id]:
                            continue
                        emit(m.id, vid, system_mode, temp, r, design["reps"], Kind.experiment)

    elif design["type"] == "sparse":
        tref = float(design["reference_temperature"])
        extra = [float(t) for t in design["extra_temperatures"]]
        if tref in extra:
            raise ValueError("reference_temperature must not also be in extra_temperatures")
        reps = design["reps"]
        for m in panel:
            for vid in design["variants"]:
                if tref <= mt[m.id]:
                    for r in design["reasoning_at_reference"]:
                        if r != "off" and not eff[m.id]:
                            continue
                        emit(m.id, vid, system_mode, tref, r, reps, Kind.experiment)
                for t in extra:
                    if t > mt[m.id]:
                        continue
                    emit(m.id, vid, system_mode, t, "off", reps, Kind.experiment)
    else:
        raise ValueError(f"unknown design.type {design['type']!r}")

    # system-prompt-contrast cell (distinct system_mode => distinct cache key)
    sc = tier.get("system_contrast")
    if sc:
        for m in panel:
            r = sc["reasoning"]
            if r != "off" and not eff[m.id]:
                continue
            if float(sc["temperature"]) <= mt[m.id]:
                emit(
                    m.id,
                    sc["variant"],
                    sc["system_mode"],
                    sc["temperature"],
                    r,
                    sc["reps"],
                    Kind.experiment,
                )

    # popularity-baseline control
    ctrl = tier.get("control")
    if ctrl:
        pid = cfg.prompts.control_prompts[ctrl["prompt"]]["id"]
        for m in panel:
            emit(m.id, pid, "none", ctrl["temperature"], ctrl["reasoning"], ctrl["reps"], Kind.control)

    specs.sort(key=lambda s: s.sort_key())
    return specs
