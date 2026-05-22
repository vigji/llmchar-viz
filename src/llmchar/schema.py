"""Pydantic data model. Permissive on purpose: raw model output is normalized
in parse.py, not rejected by validators, so non-compliance becomes a recorded
*result* (parse_status) rather than a crash."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RealOrFictional(str, Enum):
    real = "real"
    fictional = "fictional"
    unsure = "unsure"


class ParseStatus(str, Enum):
    ok = "ok"            # clean JSON, 5 well-formed picks
    repaired = "repaired"  # JSON recovered (extraction/json5/clamp/rerank)
    fallback = "fallback"  # salvaged from prose
    refused = "refused"    # model declined / disclaimed a self
    failed = "failed"      # nothing usable


class Kind(str, Enum):
    experiment = "experiment"
    control = "control"   # popularity baseline


class Pick(BaseModel):
    model_config = ConfigDict(extra="ignore")
    rank: int = Field(ge=1, le=20)
    name: str
    real_or_fictional: RealOrFictional = RealOrFictional.unsure
    domain: str = ""
    explanation: str = ""


class PicksResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    picks: list[Pick] = Field(default_factory=list)
    refused: bool = False
    refusal_reason: str | None = None

    def is_well_formed(self) -> bool:
        """Exactly 5 picks, ranks a contiguous unique 1..5, every name nonempty."""
        if self.refused or len(self.picks) != 5:
            return False
        ranks = sorted(p.rank for p in self.picks)
        if ranks != [1, 2, 3, 4, 5]:
            return False
        return all(p.name.strip() for p in self.picks)


class CallSpec(BaseModel):
    """The experimental coordinates of one API call. These fields (plus the
    rendered prompt/system text and code versions) form the cache key."""

    model_config = ConfigDict(frozen=True)
    model_id: str
    variant_id: str            # v1..v8 or "pop1" (control)
    system_mode: str           # "none" | "minimal"
    temperature: float
    reasoning: str             # "off" | "low" | "high"
    rep: int
    kind: Kind = Kind.experiment

    def sort_key(self) -> tuple:
        return (
            self.model_id,
            self.kind.value,
            self.variant_id,
            self.system_mode,
            self.temperature,
            self.reasoning,
            self.rep,
        )


class CallRecord(BaseModel):
    """One JSON file in data/raw/. The system of record."""

    model_config = ConfigDict(extra="ignore")
    cache_key: str
    spec: CallSpec
    model_family: str
    scale_tier: str

    prompt_text: str
    system_text: str | None = None
    request: dict[str, Any] = Field(default_factory=dict)
    response: dict[str, Any] | None = None

    parsed: PicksResponse | None = None
    parse_status: ParseStatus = ParseStatus.failed

    error: str | None = None
    usage: dict[str, Any] | None = None
    cost_projected_usd: float | None = None
    cost_actual_usd: float | None = None
    latency_s: float | None = None
    reasoning_returned_tokens: int = 0

    attempt_count: int = 0
    # cross-run count of consecutive transient (empty/transport) failures for
    # this cell. Drives the circuit-breaker in cache.is_terminal so a provably
    # dead cell stops being re-issued (and re-billed) on every run.
    empty_attempts: int = 0
    registry_snapshot: dict[str, Any] | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
