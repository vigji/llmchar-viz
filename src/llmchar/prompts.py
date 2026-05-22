"""Prompt rendering + the construct guard.

Every rendered experiment variant must (a) contain >=1 identification anchor
and (b) contain 0 forbidden (casual / detached-roleplay) tokens. This is the
hard guarantee the user asked for: wording varies, the construct does not."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .config import PROJECT_ROOT, PromptsConfig


def _collapse(text: str) -> str:
    """YAML block scalars keep hard-wrapped newlines; turn them into flowing
    prose (paragraph breaks preserved) so the model sees a natural prompt."""
    paras = [re.sub(r"\s+", " ", p).strip() for p in text.split("\n\n")]
    return "\n\n".join(p for p in paras if p)


def render_variant(prompts: PromptsConfig, variant_id: str) -> str:
    v = prompts.variant(variant_id)
    question = _collapse(v["question"])
    instructions = _collapse(prompts.response_instructions)
    if v.get("schema_first"):
        return f"{instructions}\n\n{question}"
    return f"{question}\n\n{instructions}"


def system_text(prompts: PromptsConfig, mode: str) -> str | None:
    if mode not in prompts.system_prompts:
        raise KeyError(f"unknown system_mode {mode!r}")
    return prompts.system_prompts[mode]


# --------------------------------------------------------------------------
# Phase-2 misalignment corner (config/misalign.yaml). Kept here (not in
# config.py's PromptsConfig) so the validated Phase-0/1 schema + construct guard
# are untouched; this is a plain dict loaded on demand.
# --------------------------------------------------------------------------

_TEMPLATE_TOKEN_RE = re.compile(r"\{\{.*?\}\}")


def load_misalign(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else PROJECT_ROOT / "config" / "misalign.yaml"
    with p.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def misalign_system_text(
    misalign: dict[str, Any],
    condition: str,
    *,
    model_name: str | None = None,
    vendor: str | None = None,
    render_templates: bool = True,
) -> str | None:
    """Resolve a system-condition key to its rendered system text.

    - `bare` -> "" (empty override). The runner decides per-backend whether an
      empty string means "send an empty system message" (local Ollama, to
      suppress the Le Chat auto-injection) or "send no system message at all"
      (OpenRouter peers).
    - `production_lechat` -> Le Chat verbatim with {{ currentDate }} /
      {{ yesterdayDate }} substituted from the pinned dates and any stray
      {{ ... }} stripped.
    - `production_std` -> {model}/{vendor} filled from the args.
    """
    sps = misalign["system_prompts"]
    if condition not in sps:
        raise KeyError(f"unknown misalign condition {condition!r}; have {list(sps)}")
    text = sps[condition]
    if text is None:
        return None
    if not render_templates:
        return text
    if condition == "production_lechat":
        text = text.replace("{{ currentDate }}", str(misalign.get("lechat_date", "")))
        text = text.replace("{{ yesterdayDate }}", str(misalign.get("lechat_yesterday", "")))
        text = _TEMPLATE_TOKEN_RE.sub("", text)  # defensive: drop any leftover token
    elif condition == "production_std":
        text = text.replace("{model}", model_name or "this assistant")
        text = text.replace("{vendor}", vendor or "its developer")
    return text.strip("\n")


def construct_violations(rendered: str, prompts: PromptsConfig) -> list[str]:
    """Returns a list of problems; empty == compliant. Used by tests and by
    `validate` (fail fast before spending money on an off-construct prompt)."""
    low = rendered.lower()
    problems: list[str] = []
    anchors = prompts.construct_guard["identification_anchors"]
    if not any(a.lower() in low for a in anchors):
        problems.append("no identification anchor present")
    for tok in prompts.construct_guard["forbidden_tokens"]:
        if tok.lower() in low:
            problems.append(f"forbidden casual-roleplay token present: {tok!r}")
    return problems


def check_all_variants(prompts: PromptsConfig) -> dict[str, list[str]]:
    """variant_id -> violations, over every experiment variant (not controls;
    the popularity baseline is deliberately NOT a self-identification prompt)."""
    out: dict[str, list[str]] = {}
    for vid in prompts.all_experiment_variant_ids():
        out[vid] = construct_violations(render_variant(prompts, vid), prompts)
    return out
