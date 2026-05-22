"""Config loading: experiment.yaml, models.yaml, prompts.yaml, tiers.yaml.
Project root = nearest ancestor containing both pyproject.toml and config/."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


def find_project_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__)).resolve()
    for d in [here, *here.parents]:
        if (d / "pyproject.toml").is_file() and (d / "config").is_dir():
            return d
    # fallback: cwd
    return Path.cwd()


PROJECT_ROOT = find_project_root()


def _load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class ModelSpec(BaseModel):
    id: str
    family: str
    scale_tier: str
    reasoning: bool
    max_temperature: float
    reasoning_budget: dict[str, int]
    # active=false: excluded from NEW runs (e.g. too costly) but kept here so
    # already-paid-for cached data stays attributable and is still reported.
    active: bool = True

    @property
    def slug(self) -> str:
        return self.id.replace("/", "_")


class ModelsConfig(BaseModel):
    models: list[ModelSpec]
    panels: dict[str, dict[str, Any]]

    def by_id(self, model_id: str) -> ModelSpec:
        for m in self.models:
            if m.id == model_id:
                return m
        raise KeyError(model_id)

    def panel(self, name: str) -> list[ModelSpec]:
        """Panels only ever schedule ACTIVE models. Inactive models keep their
        metadata (and their paid cached data) but are never re-called."""
        if name not in self.panels:
            raise KeyError(f"unknown panel {name!r}; have {list(self.panels)}")
        rule = self.panels[name]
        active = [m for m in self.models if m.active]
        if rule.get("select") == "all":
            return active
        field, val = rule["select"], rule["equals"]
        return [m for m in active if getattr(m, field) == val]


class PromptsConfig(BaseModel):
    model_config = {"populate_by_name": True}

    schema_version: str
    prompt_version: str
    response_instructions: str
    construct_guard: dict[str, list[str]] = Field(alias="construct")
    system_prompts: dict[str, str | None]
    variants: list[dict[str, Any]]
    control_prompts: dict[str, dict[str, Any]]

    def variant(self, vid: str) -> dict[str, Any]:
        for v in self.variants:
            if v["id"] == vid:
                return v
        for cp in self.control_prompts.values():
            if cp["id"] == vid:
                return cp
        raise KeyError(vid)

    def all_experiment_variant_ids(self) -> list[str]:
        return [v["id"] for v in self.variants]


class ExperimentConfig(BaseModel):
    tier: str
    panel: str | None
    max_usd: float | None
    max_concurrency: int
    request_timeout_s: int
    max_retries: int
    max_tokens_floor: int
    seed: int | None
    paths: dict[str, str]


class Settings(BaseModel):
    openrouter_api_key: str | None = None
    http_referer: str | None = None
    x_title: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        _load_dotenv(PROJECT_ROOT / ".env")
        return cls(
            openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"),
            http_referer=os.environ.get("OPENROUTER_HTTP_REFERER"),
            x_title=os.environ.get("OPENROUTER_X_TITLE"),
        )


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


class Config(BaseModel):
    experiment: ExperimentConfig
    models: ModelsConfig
    prompts: PromptsConfig
    tiers: dict[str, Any]
    root: Path

    model_config = {"arbitrary_types_allowed": True}

    @property
    def data_dir(self) -> Path:
        return self.root / self.experiment.paths.get("data_dir", "data")


@lru_cache(maxsize=8)
def load_config(config_dir: str | None = None) -> Config:
    root = PROJECT_ROOT
    cdir = Path(config_dir) if config_dir else root / "config"

    exp = _load_yaml(cdir / "experiment.yaml")
    raw_models = _load_yaml(cdir / "models.yaml")
    prompts = _load_yaml(cdir / "prompts.yaml")
    tiers = _load_yaml(cdir / "tiers.yaml")

    defaults = raw_models.get("defaults", {})
    dmax = float(defaults.get("max_temperature", 2.0))
    dbudget = dict(defaults.get("reasoning_budget", {"low": 1500, "high": 6000}))
    models = [
        ModelSpec(
            id=m["id"],
            family=m["family"],
            scale_tier=m["scale_tier"],
            reasoning=bool(m["reasoning"]),
            max_temperature=float(m.get("max_temperature", dmax)),
            reasoning_budget=dict(m.get("reasoning_budget", dbudget)),
            active=bool(m.get("active", True)),
        )
        for m in raw_models["models"]
    ]

    return Config(
        experiment=ExperimentConfig(**exp),
        models=ModelsConfig(models=models, panels=raw_models["panels"]),
        prompts=PromptsConfig(**prompts),
        tiers=tiers,
        root=root,
    )
