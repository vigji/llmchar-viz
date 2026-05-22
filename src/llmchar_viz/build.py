"""Build the single-file llmchar.db end-to-end (offline).

  raw JSON  ->  ETL  ->  dedup/canonicalization  ->  tables
            ->  embeddings (explanation + character/wiki)  ->  aggregates  ->  FTS

Run: `uv run --extra embed llmchar-viz-build`  (or `make db`).
Use --no-embed to skip the local embedding step (faster; leaves coords NULL).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from llmchar.canonical import Canonicalizer
from llmchar.config import PROJECT_ROOT, load_config

from . import db
from .canon import build_aliases
from .embed import behavior
from .etl import load_base, load_phase0, load_phase2

VENDOR = {"openai": "OpenAI", "claude": "Anthropic", "gemini": "Google",
          "deepseek": "DeepSeek", "grok": "xAI", "mistral": "Mistral AI",
          "qwen": "Alibaba", "kimi": "Moonshot"}
PICK_EXPERIMENTS = ("base_selfid_open", "phase0_selfid_single", "prodbare_selfid_open")


def _family(model_id: str, cfg) -> tuple[str, str]:
    try:
        m = cfg.models.by_id(model_id)
        return m.family, m.scale_tier
    except Exception:
        return model_id.split("/")[0], "unknown"


def load_all_rows(data: Path):
    rows = list(load_base.load(data, subdir="raw", experiment="base_selfid_open"))
    if (data / "prodbare").is_dir():
        rows += list(load_base.load(data, subdir="prodbare",
                                    experiment="prodbare_selfid_open"))
    rows += list(load_phase0.load(data, subdir="phase0/raw"))
    rows += list(load_phase2.load(data, subdir="phase2/raw"))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(PROJECT_ROOT / "llmchar.db"))
    ap.add_argument("--data", default=str(PROJECT_ROOT / "data"))
    ap.add_argument("--no-embed", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    data = Path(args.data)
    dbpath = Path(args.db)
    seed_dir = PROJECT_ROOT / "data" / "canonical"

    print("[1/8] loading raw rows...", flush=True)
    rows = load_all_rows(data)
    src_counts = Counter(r.experiment for r in rows)
    print(f"      {len(rows)} responses: {dict(src_counts)}", flush=True)

    print("[2/8] dedup / canonicalization...", flush=True)
    counts, rf_votes = build_aliases.collect(rows)
    characters, aliases, dedup_stats = build_aliases.augment(seed_dir, counts, rf_votes)
    build_aliases.write_canon(seed_dir, characters, aliases)
    print(f"      {dedup_stats}", flush=True)
    canon = Canonicalizer(seed_dir)

    # canonicalize once to gather per-character votes + counts
    char_votes: dict[str, Counter] = defaultdict(Counter)
    char_count: Counter = Counter()
    for r in rows:
        for p in r.picks:
            res = canon.canonicalize(p.raw_name)
            char_votes[res.canonical][p.real_or_fictional] += 1
            char_count[res.canonical] += 1

    print("[3/8] writing core tables...", flush=True)
    if dbpath.exists():
        dbpath.unlink()
    conn = db.connect(dbpath)
    db.create_schema(conn)

    # models
    for mid in sorted({r.model_id for r in rows}):
        fam, tier = _family(mid, cfg)
        conn.execute("INSERT OR IGNORE INTO models VALUES (?,?,?,?,?,?)",
                     (mid, fam, VENDOR.get(fam, fam.title()), tier,
                      mid.split("/")[-1], "openrouter"))

    # characters (union of seed/promoted + any picked canonical)
    for c in sorted(set(canon.characters) | set(char_count)):
        attrs = canon.attributes(c)
        rf = attrs.get("real_or_fictional")
        if rf not in ("real", "fictional"):
            v = char_votes.get(c)
            rf = v.most_common(1)[0][0] if v else "unsure"
            if rf not in ("real", "fictional"):
                rf = "unsure"
        conn.execute(
            "INSERT OR IGNORE INTO characters (canonical, real_or_fictional, domain, era, gender, axis, pick_count) "
            "VALUES (?,?,?,?,?,?,?)",
            (c, rf, attrs.get("domain", ""), attrs.get("era", ""),
             attrs.get("gender", ""), attrs.get("axis"), char_count.get(c, 0)))

    # intern repetitive prompt/system texts into the texts table
    text_ids: dict[str, int] = {}

    def intern(t: str | None) -> int | None:
        if not t:
            return None
        if t not in text_ids:
            tid = len(text_ids) + 1
            text_ids[t] = tid
            conn.execute("INSERT INTO texts VALUES (?,?)", (tid, t))
        return text_ids[t]

    # responses + picks
    rid = 0
    pid = 0
    for r in rows:
        rid += 1
        conn.execute(
            "INSERT INTO responses (response_id, source_key, model_id, experiment, condition, "
            "condition_detail, variant, temperature, reasoning, rep, kind, persona, system_text_id, "
            "prompt_text_id, response_content, parse_status, refused, n_picks, cost_usd, latency_s, timestamp) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, r.source_key, r.model_id, r.experiment, r.condition, r.condition_detail,
             r.variant, r.temperature, r.reasoning, r.rep, r.kind, r.persona, intern(r.system_text),
             intern(r.prompt_text), r.response_content, r.parse_status, r.refused, len(r.picks),
             r.cost_usd, r.latency_s, r.timestamp))
        for p in r.picks:
            pid += 1
            res = canon.canonicalize(p.raw_name)
            conn.execute(
                "INSERT INTO picks (pick_id, response_id, rank, raw_name, canonical, canon_method, "
                "canon_score, model_real_or_fictional, domain, explanation) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pid, rid, p.rank, p.raw_name, res.canonical, res.method, res.score,
                 p.real_or_fictional, p.domain, p.explanation))
    conn.commit()
    print(f"      {rid} responses, {pid} picks, "
          f"{conn.execute('SELECT COUNT(*) FROM characters').fetchone()[0]} characters", flush=True)

    if not args.no_embed:
        print("[4/8] embeddings (downloads MiniLM on first run)...", flush=True)
        from sentence_transformers import SentenceTransformer

        from .embed import characters as char_embed
        from .embed import explanations as expl_embed
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        char_embed.run(conn, model, PROJECT_ROOT / "data" / "wiki_cache.json",
                       PROJECT_ROOT / "vectors_characters.npz")
        expl_embed.run(conn, model, PROJECT_ROOT / "vectors_explanations.npz")
    else:
        print("[4/8] embeddings SKIPPED (--no-embed)", flush=True)

    print("[5/8] behavioral similarity...", flush=True)
    behavior.run(conn)

    print("[6/8] aggregates (pick_freq_by_condition)...", flush=True)
    placeholders = ",".join("?" * len(PICK_EXPERIMENTS))
    conn.execute(f"""
        INSERT INTO pick_freq_by_condition
        SELECT num.model_id, num.canonical, num.condition, num.experiment,
               den.n_responses, num.n_picks,
               CAST(num.n_picks AS REAL)/den.n_responses
        FROM (
            SELECT model_id, condition, experiment, COUNT(*) n_responses
            FROM responses WHERE experiment IN ({placeholders})
            GROUP BY model_id, condition, experiment
        ) den
        JOIN (
            SELECT r.model_id, r.condition, r.experiment, p.canonical,
                   COUNT(DISTINCT r.response_id) n_picks
            FROM responses r JOIN picks p ON p.response_id=r.response_id
            WHERE r.experiment IN ({placeholders})
            GROUP BY r.model_id, r.condition, r.experiment, p.canonical
        ) num USING (model_id, condition, experiment)
    """, PICK_EXPERIMENTS * 2)
    conn.commit()

    print("[7/8] (search uses portable LIKE queries — no FTS module needed)", flush=True)

    print("[8/8] indexes, meta, VACUUM...", flush=True)
    db.create_indexes(conn)
    meta = {
        "build_utc": datetime.now(UTC).isoformat(),
        "source_counts": json.dumps(dict(src_counts)),
        "dedup_stats": json.dumps(dedup_stats),
        "n_models": str(conn.execute("SELECT COUNT(*) FROM models").fetchone()[0]),
        "n_characters": str(conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0]),
        "n_responses": str(rid),
        "n_picks": str(pid),
        "embed_model": "none" if args.no_embed else "all-MiniLM-L6-v2",
        "schema_version": "1",
    }
    conn.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)", list(meta.items()))
    conn.commit()
    conn.execute("VACUUM")
    conn.commit()
    conn.close()

    size_mb = dbpath.stat().st_size / 1e6
    print(f"\nDONE -> {dbpath}  ({size_mb:.1f} MB)", flush=True)
    if size_mb > 50:
        print("  WARNING: DB exceeds 50 MB — drop response_content/FTS or strip text.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
