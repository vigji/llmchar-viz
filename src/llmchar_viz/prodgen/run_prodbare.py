"""Prod-vs-bare runs on the base 5-character self-identification task.

Asks the SAME `v1` question under two conditions for three models:
  * bare       -> no system message
  * production -> the vendor's real deployed system prompt (config/prod_prompts.yaml)

Models / access:
  * mistralai/ministral-8b-2512  via Mistral La Plateforme direct  (FREE)
  * anthropic/claude-haiku-4.5   via OpenRouter                    (paid)
  * x-ai/grok-4.3                via OpenRouter                    (paid)

Writes base-schema CallRecord JSON under data/prodbare/<slug>/ so the existing
base loader ingests them as experiment=prodbare_selfid_open. Resumable (skips
existing files) and cost-capped on OpenRouter spend.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

from llmchar.config import PROJECT_ROOT, Settings, load_config
from llmchar.prompts import render_variant

VARIANT = "v1"
TEMPERATURE = 0.7
REPS = 40
MAX_TOKENS = 800
COST_CAP_USD = 4.0          # generous: estimate ~$0.5; ~8x margin
OUTROOT = PROJECT_ROOT / "data" / "prodbare"

OR_URL = "https://openrouter.ai/api/v1/chat/completions"
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"

# (model_id, family, scale_tier, access, mistral_platform_id_or_None)
MODELS = [
    ("mistralai/ministral-8b-2512", "mistral", "tiny", "mistral_direct", "ministral-8b-2512"),
    ("anthropic/claude-haiku-4.5", "claude", "small", "openrouter", None),
    ("x-ai/grok-4.3", "grok", "flagship", "openrouter", None),
]


def _key(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode())
    return h.hexdigest()


def _load_prod_prompts() -> dict:
    doc = yaml.safe_load((PROJECT_ROOT / "config" / "prod_prompts.yaml").read_text())
    return doc


def _record(model_id, family, scale_tier, system_mode, system_text, prompt_text,
            resp_json, cost, latency, rep) -> dict:
    return {
        "cache_key": _key(model_id, VARIANT, system_mode, TEMPERATURE, rep),
        "spec": {
            "model_id": model_id, "variant_id": VARIANT, "system_mode": system_mode,
            "temperature": TEMPERATURE, "reasoning": "off", "rep": rep, "kind": "experiment",
        },
        "model_family": family, "scale_tier": scale_tier,
        "prompt_text": prompt_text, "system_text": system_text,
        "response": resp_json,
        "parsed": None, "parse_status": "failed",
        "cost_actual_usd": cost, "latency_s": latency,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    Settings.from_env()
    or_key = os.environ.get("OPENROUTER_API_KEY")
    mistral_key = os.environ.get("MISTRAL_API_KEY")
    cfg = load_config()
    user_text = render_variant(cfg.prompts, VARIANT)
    prod = _load_prod_prompts()
    sys_prompts = prod["system_prompts"]
    model_prompt = prod["model_prompt"]

    or_headers = {"Authorization": f"Bearer {or_key}", "Content-Type": "application/json"}
    if cfg_ref := os.environ.get("OPENROUTER_HTTP_REFERER"):
        or_headers["HTTP-Referer"] = cfg_ref
    if cfg_title := os.environ.get("OPENROUTER_X_TITLE"):
        or_headers["X-Title"] = cfg_title
    mistral_headers = {"Authorization": f"Bearer {mistral_key}", "Content-Type": "application/json"}

    spent = 0.0
    made = 0
    skipped = 0
    with httpx.Client(timeout=180) as client:
        for model_id, family, scale_tier, access, plat_id in MODELS:
            slug = model_id.replace("/", "_")
            outdir = OUTROOT / slug
            outdir.mkdir(parents=True, exist_ok=True)
            prod_key = model_prompt[model_id]
            prod_text = sys_prompts[prod_key].strip()

            for system_mode, system_text in [("none", None), (prod_key, prod_text)]:
                for rep in range(REPS):
                    fpath = outdir / f"{_key(model_id, VARIANT, system_mode, TEMPERATURE, rep)}.json"
                    if fpath.is_file():
                        skipped += 1
                        continue

                    messages = []
                    if system_text:
                        messages.append({"role": "system", "content": system_text})
                    messages.append({"role": "user", "content": user_text})

                    if access == "openrouter":
                        if spent >= COST_CAP_USD:
                            print(f"[CAP] OpenRouter spend ${spent:.3f} >= ${COST_CAP_USD}; "
                                  f"skipping {model_id} {system_mode}", flush=True)
                            continue
                        body = {"model": model_id, "messages": messages,
                                "temperature": TEMPERATURE, "top_p": 1.0,
                                "max_tokens": MAX_TOKENS,
                                "provider": {"allow_fallbacks": False},
                                "usage": {"include": True}}
                        url, headers = OR_URL, or_headers
                    else:
                        body = {"model": plat_id, "messages": messages,
                                "temperature": TEMPERATURE, "top_p": 1.0,
                                "max_tokens": MAX_TOKENS}
                        url, headers = MISTRAL_URL, mistral_headers

                    t0 = time.time()
                    try:
                        r = client.post(url, headers=headers, json=body)
                        r.raise_for_status()
                        rj = r.json()
                    except Exception as e:
                        print(f"  err {model_id} {system_mode} rep={rep}: {str(e)[:160]}", flush=True)
                        time.sleep(2.0)
                        continue
                    latency = time.time() - t0
                    cost = float((rj.get("usage") or {}).get("cost") or 0.0)
                    spent += cost
                    rec = _record(model_id, family, scale_tier, system_mode,
                                  system_text, user_text, rj, cost, latency, rep)
                    fpath.write_text(json.dumps(rec, indent=2))
                    made += 1
                    if made % 10 == 0:
                        print(f"  ... {made} made, OpenRouter ${spent:.3f}", flush=True)

            print(f"[done] {model_id}: made so far={made}, spent=${spent:.3f}", flush=True)

    print(f"\nPROD-BARE COMPLETE: made={made}, skipped(existing)={skipped}, "
          f"OpenRouter spend=${spent:.4f} (cap ${COST_CAP_USD})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
