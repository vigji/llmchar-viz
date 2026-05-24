"""Finish the canonicalization so no character-name merge work remains.

The source seed `characters.yaml` lists only ~35 hand-picked characters, so most
model picks land as `new` (their own canonical) — these are mostly *legitimate*
characters missing from the seed (Lincoln, Aristotle, Camus), not duplicates.
We:
  (a) fuzzy-cluster the `new` surfaces and merge near-identical variants
      (e.g. "Arjuna" / "Arjuna from the Bhagavad Gita") into one canonical,
      writing alias entries (the only real dedup);
  (b) promote any `new` canonical seen >= MIN_PROMOTE times to an official
      `characters.yaml` entry with a back-filled real/fictional label, so it is
      no longer flagged `new`.
The augmented characters.yaml + aliases.yaml are written into the viz repo and
committed, making the final canonicalization reproducible and offline.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import yaml
from rapidfuzz import fuzz

from llmchar.canonical import Canonicalizer, normalize_name

MIN_PROMOTE = 3
FUZZY_MERGE = 92.0


def collect(resp_rows) -> tuple[Counter, dict[str, Counter]]:
    """Tally raw pick names and the model-stated real/fictional votes."""
    counts: Counter = Counter()
    rf_votes: dict[str, Counter] = defaultdict(Counter)
    for r in resp_rows:
        for p in r.picks:
            nm = p.raw_name.strip()
            if not nm:
                continue
            counts[nm] += 1
            rf_votes[nm][p.real_or_fictional] += 1
    return counts, rf_votes


def augment(canonical_dir: Path, counts: Counter, rf_votes: dict[str, Counter],
            *, min_promote: int = MIN_PROMOTE, fuzzy_merge: float = FUZZY_MERGE):
    """Return (characters_dict, aliases_dict, stats)."""
    canon = Canonicalizer(canonical_dir)
    characters: dict[str, dict] = dict(canon.characters)
    aliases: dict[str, str] = _load_aliases_raw(canonical_dir)

    # 1) resolve every distinct raw name with the seed ladder; tally NEW canonicals.
    new_counts: Counter = Counter()             # new canonical -> total picks
    new_rf: dict[str, Counter] = defaultdict(Counter)
    for raw, n in counts.items():
        res = canon.canonicalize(raw)
        if res.method == "new":
            new_counts[res.canonical] += n
            new_rf[res.canonical].update({k: v for k, v in rf_votes[raw].items()})
    n_new_initial = len(new_counts)

    # 2) greedy fuzzy-cluster NEW canonicals; merge variants into one representative.
    reps: list[str] = []
    merged_into: dict[str, str] = {}
    for cand in sorted(new_counts, key=lambda c: -new_counts[c]):
        match = next((rep for rep in reps
                      if fuzz.token_sort_ratio(cand, rep) >= fuzzy_merge), None)
        if match is None:
            reps.append(cand)
        else:
            merged_into[cand] = match
            aliases[normalize_name(cand)] = match
    n_merged = len(merged_into)

    # fold merged counts/votes into their representative
    for variant, rep in merged_into.items():
        new_counts[rep] += new_counts.get(variant, 0)
        new_rf[rep].update(new_rf.get(variant, Counter()))

    # 3) promote frequent representatives to official characters.yaml entries.
    n_promoted = 0
    for rep in reps:
        if rep in characters or new_counts[rep] < min_promote:
            continue
        votes = new_rf.get(rep, Counter())
        rf = votes.most_common(1)[0][0] if votes else "unsure"
        if rf not in ("real", "fictional"):
            rf = "unsure"
        characters[rep] = {"real_or_fictional": rf, "domain": "", "era": "", "gender": ""}
        n_promoted += 1

    # 4) reconcile case/display variants: collapse character displays that share a
    #    normalized form, and repoint alias values at the kept display. Fixes splits
    #    like "Marvin the Paranoid Android" vs "Marvin The Paranoid Android".
    char_by_norm: dict[str, str] = {}
    n_reconciled = 0
    for k in list(characters):
        nk = normalize_name(k)
        if nk in char_by_norm:
            aliases[nk] = char_by_norm[nk]
            characters.pop(k, None)
            n_reconciled += 1
        else:
            char_by_norm[nk] = k
    for k, v in list(aliases.items()):
        nv = normalize_name(v)
        if nv in char_by_norm and char_by_norm[nv] != v:
            aliases[k] = char_by_norm[nv]

    residual = sum(1 for rep in reps if rep not in characters)
    stats = {
        "distinct_raw_names": len(counts),
        "new_canonicals_initial": n_new_initial,
        "fuzzy_merged": n_merged,
        "display_reconciled": n_reconciled,
        "promoted_to_seed": n_promoted,
        "residual_new_singletons": residual,
    }
    return characters, aliases, stats


def write_canon(out_dir: Path, characters: dict, aliases: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "characters.yaml").write_text(
        yaml.safe_dump(characters, sort_keys=True, allow_unicode=True))
    (out_dir / "aliases.yaml").write_text(
        yaml.safe_dump({"aliases": dict(sorted(aliases.items()))},
                       sort_keys=False, allow_unicode=True))


def _load_aliases_raw(canonical_dir: Path) -> dict[str, str]:
    doc = yaml.safe_load((canonical_dir / "aliases.yaml").read_text()) or {}
    return {normalize_name(k): v for k, v in (doc.get("aliases", {}) or {}).items()}
