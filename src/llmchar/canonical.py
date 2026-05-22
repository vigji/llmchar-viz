"""Character-name canonicalization: deterministic first, auditable always.
alias-exact -> known-canonical-exact -> fuzzy (rapidfuzz) -> `new` (kept as
its own canonical AND flagged for human review; never silently merged). An
optional LLM judge can resolve only the queued `new` cases but is off by
default and never called implicitly."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process

_HONORIFICS = {
    "dr", "mr", "mrs", "ms", "miss", "sir", "dame", "lord", "lady", "madam",
    "madame", "captain", "capt", "cmdr", "commander", "lieutenant", "lt",
    "professor", "prof", "st", "saint", "king", "queen", "emperor", "empress",
    "president", "general", "colonel", "sergeant", "the",
}
_FUZZY_THRESHOLD = 90.0


@dataclass
class CanonResult:
    raw: str
    normalized: str
    canonical: str
    method: str          # alias | canonical_exact | fuzzy | new
    score: float = 100.0


def normalize_name(name: str, *, drop_parentheticals: bool = False) -> str:
    """Deterministic surface flattener. Brackets are NOT dropped by default —
    a parenthetical is sometimes pure gloss ("Data (Star Trek)") but sometimes
    the only disambiguator ("The Librarian (Discworld)" vs "(Library of
    Babel)"), and the normalizer can't tell which, so it must not silently
    discard it. `drop_parentheticals=True` is used only for the paren-stripped
    resolution fallback in Canonicalizer.canonicalize."""
    s = unicodedata.normalize("NFKC", name).strip().casefold()
    if drop_parentheticals:
        s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[\"'`’.,;:!?*_/\\\[\]{}()]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    tokens = [t for t in s.split(" ") if t]
    while tokens and tokens[0] in _HONORIFICS:
        tokens.pop(0)
    return " ".join(tokens)


class Canonicalizer:
    def __init__(self, canonical_dir: str | Path):
        d = Path(canonical_dir)
        aliases_doc = yaml.safe_load((d / "aliases.yaml").read_text()) or {}
        self.aliases: dict[str, str] = {
            normalize_name(k): v for k, v in (aliases_doc.get("aliases", {}) or {}).items()
        }
        self.characters: dict[str, dict] = yaml.safe_load((d / "characters.yaml").read_text()) or {}
        # normalized canonical surface -> canonical display name
        self._canon_index = {normalize_name(c): c for c in self.characters}
        self._fuzzy_universe = list(self._canon_index) + list(self.aliases)
        self._audit: dict[str, CanonResult] = {}

    def _resolve(self, surface: str) -> tuple[str, str, float] | None:
        """One pass of the deterministic ladder on a normalized surface.
        Returns (canonical, method, score) or None if nothing matched."""
        if not surface:
            return None
        if surface in self.aliases:
            return (self.aliases[surface], "alias", 100.0)
        if surface in self._canon_index:
            return (self._canon_index[surface], "canonical_exact", 100.0)
        match = process.extractOne(surface, self._fuzzy_universe, scorer=fuzz.token_sort_ratio)
        if match and match[1] >= _FUZZY_THRESHOLD:
            key = match[0]
            canon = self.aliases.get(key) or self._canon_index.get(key, key)
            return (canon, "fuzzy", float(match[1]))
        return None

    def canonicalize(self, name: str) -> CanonResult:
        raw = name.strip()
        if raw in self._audit:
            return self._audit[raw]
        norm = normalize_name(raw)  # brackets KEPT — the faithful recorded surface
        res: CanonResult
        if not norm:
            res = CanonResult(raw, norm, raw.strip() or "(blank)", "new", 0.0)
        else:
            hit = self._resolve(norm)
            if hit is None:
                # paren-stripped fallback: recovers redundant glosses
                # ("Data (Star Trek)" -> Data) WITHOUT an alias, while a
                # genuine disambiguator only resolves here if it has an
                # explicit alias (which fires above, before this fallback).
                head = normalize_name(raw, drop_parentheticals=True)
                hit = self._resolve(head) if head and head != norm else None
            if hit is not None:
                canon, method, score = hit
                res = CanonResult(raw, norm, canon, method, score)
            else:
                res = CanonResult(raw, norm, _title(norm), "new", 0.0)
        self._audit[raw] = res
        return res

    def attributes(self, canonical: str) -> dict:
        return dict(self.characters.get(canonical, {}))

    def audit_map(self) -> dict[str, dict]:
        return {
            k: {"canonical": v.canonical, "method": v.method, "score": v.score, "normalized": v.normalized}
            for k, v in sorted(self._audit.items())
        }

    @property
    def unresolved(self) -> list[str]:
        return sorted(r.raw for r in self._audit.values() if r.method == "new")


def _title(s: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in s.split(" ") if w)
