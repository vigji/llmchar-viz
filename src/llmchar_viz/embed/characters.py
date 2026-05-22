"""Character / Wikipedia embedding space.

Fetch a short Wikipedia summary per canonical character (cached to a committed
JSON so rebuilds are offline), embed it locally, cluster + project to 2D, and
place each model as the pick-weighted centroid of the characters it names.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import httpx
import numpy as np

UA = "llmchar-viz/0.1 (research; https://github.com/vigji/llmchar)"
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
OPENSEARCH = "https://en.wikipedia.org/w/api.php"


def _opensearch(client: httpx.Client, name: str) -> str | None:
    try:
        r = client.get(OPENSEARCH, params={"action": "opensearch", "search": name,
                                           "limit": 1, "namespace": 0, "format": "json"})
        r.raise_for_status()
        hits = r.json()
        return hits[1][0] if hits and hits[1] else None
    except Exception:
        return None


def _summary(client: httpx.Client, title: str) -> dict | None:
    try:
        r = client.get(SUMMARY.format(title=title.replace(" ", "_")))
        if r.status_code != 200:
            return None
        j = r.json()
        if j.get("type") == "disambiguation":
            return None
        return j
    except Exception:
        return None


def fetch_wiki(canonicals: list[str], cache_path: Path) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    if cache_path.is_file():
        cache = json.loads(cache_path.read_text())
    todo = [c for c in canonicals if c not in cache]
    if todo:
        with httpx.Client(timeout=30, headers={"User-Agent": UA},
                          follow_redirects=True) as client:
            for i, name in enumerate(todo):
                doc = _summary(client, name)
                if doc is None:
                    alt = _opensearch(client, name)
                    if alt:
                        doc = _summary(client, alt)
                cache[name] = {
                    "title": (doc or {}).get("title"),
                    "summary": (doc or {}).get("extract"),
                    "url": ((doc or {}).get("content_urls", {}) or {}).get("desktop", {}).get("page"),
                } if doc else {"title": None, "summary": None, "url": None}
                if (i + 1) % 50 == 0:
                    print(f"    wiki {i+1}/{len(todo)}", flush=True)
                    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=0))
                time.sleep(0.05)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=0))
    return cache


def run(conn: sqlite3.Connection, model, cache_path: Path, npz_path: Path) -> None:
    import hdbscan
    import umap

    canonicals = [r[0] for r in conn.execute("SELECT canonical FROM characters").fetchall()]
    wiki = fetch_wiki(canonicals, cache_path)

    # write wiki fields back
    for name, doc in wiki.items():
        conn.execute("UPDATE characters SET wiki_title=?, wiki_url=?, wiki_summary=? WHERE canonical=?",
                     (doc.get("title"), doc.get("url"), doc.get("summary"), name))
    conn.commit()

    have = [(n, wiki[n]["summary"]) for n in canonicals
            if wiki.get(n, {}).get("summary")]
    if len(have) < 5:
        print("    too few wiki summaries; skipping character embedding", flush=True)
        return
    names = [n for n, _ in have]
    texts = [s for _, s in have]
    vecs = model.encode(texts, batch_size=64, show_progress_bar=False,
                        normalize_embeddings=True)
    vecs = np.asarray(vecs, dtype=np.float32)

    xy = umap.UMAP(n_neighbors=min(15, len(names) - 1), min_dist=0.1,
                   metric="cosine", random_state=42).fit_transform(vecs)
    # cluster on the 2D layout: HDBSCAN on 384-dim is all-noise for ~600 sparse
    # points; on the UMAP coords it recovers the visible semantic neighborhoods.
    labels = hdbscan.HDBSCAN(min_cluster_size=8, min_samples=1).fit_predict(xy)

    coord = {}
    for n, (x, y), cl in zip(names, xy, labels):
        coord[n] = (float(x), float(y), int(cl))
        conn.execute("UPDATE characters SET char_umap_x=?, char_umap_y=?, char_cluster_id=? WHERE canonical=?",
                     (float(x), float(y), int(cl), n))
    conn.commit()
    np.savez_compressed(npz_path, names=np.array(names), vecs=vecs)

    # pick-weighted model centroids in character space
    rows = conn.execute("""
        SELECT r.model_id, p.canonical
        FROM picks p JOIN responses r ON p.response_id=r.response_id
        WHERE p.canonical IN (SELECT canonical FROM characters WHERE char_umap_x IS NOT NULL)
    """).fetchall()
    agg: dict[str, list] = {}
    for model_id, canon in rows:
        if canon in coord:
            agg.setdefault(model_id, []).append(coord[canon][:2])
    for model_id, pts in agg.items():
        arr = np.asarray(pts)
        conn.execute("INSERT OR REPLACE INTO model_centroids VALUES (?,?,?,?,?,?)",
                     (model_id, "character", "all", float(arr[:, 0].mean()),
                      float(arr[:, 1].mean()), len(pts)))
    conn.commit()
    print(f"    character space: {len(names)} chars embedded, "
          f"{len(set(labels))} clusters, {len(agg)} model centroids", flush=True)
