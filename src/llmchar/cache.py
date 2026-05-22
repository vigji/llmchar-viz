"""Content-addressed store. data/raw/<model_slug>/<sha>.json is BOTH the cache
and the system of record: analysis never calls the API, and reruns / tier
upgrades only fill misses. The cache key includes the rendered prompt/system
text and the schema+parser+request versions, so editing a variant or fixing
the parser invalidates only the affected cells — never the whole corpus."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from .schema import CallRecord, CallSpec

SCHEMA_VERSION = "1"

# A cell that comes back transient-empty on this many separate stored
# occasions is treated as persistently dead -> terminal, so it is no longer
# re-issued (and re-billed) on every run. A prior transient record already
# counts as one occasion, so a genuine one-off blip still gets a free retry
# (count 1 < limit) while a chronically-empty cell quarantines on its 2nd hit.
EMPTY_FAILURE_LIMIT = 2


def _is_transient_failure(rec: CallRecord) -> bool:
    """Nothing parsed AND an error set => transport/empty failure (retryable).
    A parse-failure WITH content has error=None and is terminal elsewhere."""
    return rec.parsed is None and rec.error is not None


def request_fingerprint(max_tokens: int, reasoning_param: dict | None) -> str:
    """Stable description of request-shaping params (NOT sampling draw). Kept
    deterministic across runs so the cache survives re-invocation."""
    payload = {
        "top_p": 1.0,
        "allow_fallbacks": False,
        "max_tokens": max_tokens,
        "reasoning": reasoning_param or {},
        "v": 1,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def cache_key(
    spec: CallSpec,
    *,
    prompt_text: str,
    system_text: str | None,
    schema_version: str,
    parser_version: str,
    req_fingerprint: str,
) -> str:
    h = hashlib.sha256()
    key_obj = {
        "model_id": spec.model_id,
        "variant_id": spec.variant_id,
        "system_mode": spec.system_mode,
        "temperature": spec.temperature,
        "reasoning": spec.reasoning,
        "rep": spec.rep,
        "kind": spec.kind.value,
        "prompt_sha": hashlib.sha256(prompt_text.encode()).hexdigest(),
        "system_sha": hashlib.sha256((system_text or "").encode()).hexdigest(),
        "schema_version": schema_version,
        "parser_version": parser_version,
        "request_fingerprint": req_fingerprint,
    }
    h.update(json.dumps(key_obj, sort_keys=True, separators=(",", ":")).encode())
    return h.hexdigest()


class Cache:
    def __init__(self, data_dir: Path):
        self.raw_dir = Path(data_dir) / "raw"

    def _path(self, model_id: str, key: str) -> Path:
        return self.raw_dir / model_id.replace("/", "_") / f"{key}.json"

    def has(self, model_id: str, key: str) -> bool:
        return self._path(model_id, key).is_file()

    def load(self, model_id: str, key: str) -> CallRecord | None:
        p = self._path(model_id, key)
        if not p.is_file():
            return None
        try:
            return CallRecord.model_validate_json(p.read_text())
        except Exception:
            return None

    def _archive(self, model_id: str, key: str, old: CallRecord) -> None:
        """Never lose a paid response. Before any overwrite, if the existing
        record cost money or carried a provider response, snapshot it under
        data/raw/_archive/ (timestamped, never deleted)."""
        if not (old.response or (old.cost_actual_usd or 0) > 0):
            return  # nothing paid -> safe to replace silently
        adir = self.raw_dir / "_archive" / model_id.replace("/", "_")
        adir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        (adir / f"{key}__{stamp}.json").write_text(old.model_dump_json(indent=2))

    def store(self, record: CallRecord) -> Path:
        p = self._path(record.spec.model_id, record.cache_key)
        p.parent.mkdir(parents=True, exist_ok=True)
        prior = self.load(record.spec.model_id, record.cache_key) if p.is_file() else None
        if prior is not None:
            self._archive(record.spec.model_id, record.cache_key, prior)
        # Carry the transient-failure tally across runs. A prior transient
        # record is itself evidence of one failed occasion, so a chronically
        # dead cell reaches EMPTY_FAILURE_LIMIT (and quarantines) fast instead
        # of bleeding a paid call on every future run.
        if _is_transient_failure(record):
            base = prior.empty_attempts if prior is not None else 0
            if prior is not None and _is_transient_failure(prior):
                base = max(base, 1)
            record.empty_attempts = base + 1
        data = record.model_dump_json(indent=2)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return p

    def is_terminal(self, model_id: str, key: str) -> bool:
        """A cell is DONE only if it produced a persistent result. A transport
        failure (error set, nothing parsed) is transient -> a re-run retries
        it, UNTIL it has been empty for EMPTY_FAILURE_LIMIT separate runs, at
        which point it is quarantined as terminal so it stops being re-billed.
        A genuine parse-failure with content present is terminal (only a
        parser_version bump, which changes the key, would re-derive it)."""
        rec = self.load(model_id, key)
        if rec is None:
            return False
        if rec.parsed is not None:
            return True
        if rec.error is None:
            return True  # parse-failed-with-content => terminal
        # transient failure: retry until it has been provably dead for
        # EMPTY_FAILURE_LIMIT separate runs, then quarantine (stop re-billing).
        return rec.empty_attempts >= EMPTY_FAILURE_LIMIT

    def iter_records(self) -> Iterator[CallRecord]:
        if not self.raw_dir.is_dir():
            return
        for p in sorted(self.raw_dir.rglob("*.json")):
            if "_archive" in p.parts:  # archived supersedes are NOT live records
                continue
            try:
                yield CallRecord.model_validate_json(p.read_text())
            except Exception:
                continue

    def total_actual_cost(self) -> float:
        return sum((r.cost_actual_usd or 0.0) for r in self.iter_records())
