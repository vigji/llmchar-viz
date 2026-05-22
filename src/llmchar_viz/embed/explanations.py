"""Explanation embedding space.

Embed each pick's free-text rationale ("...because I identify with their...")
locally, cluster + project to 2D, and place each model as the centroid of its
explanations. Captures how models *talk about* their self-identification.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np


def run(conn: sqlite3.Connection, model, npz_path: Path, min_chars: int = 8) -> None:
    import hdbscan
    import umap

    rows = conn.execute("""
        SELECT p.pick_id, r.model_id, p.explanation
        FROM picks p JOIN responses r ON p.response_id=r.response_id
        WHERE p.explanation IS NOT NULL AND length(trim(p.explanation)) >= ?
    """, (min_chars,)).fetchall()
    if len(rows) < 10:
        print("    too few explanations; skipping explanation embedding", flush=True)
        return

    pick_ids = [r[0] for r in rows]
    model_ids = [r[1] for r in rows]
    texts = [r[2] for r in rows]
    print(f"    embedding {len(texts)} explanations...", flush=True)
    vecs = model.encode(texts, batch_size=128, show_progress_bar=False,
                        normalize_embeddings=True)
    vecs = np.asarray(vecs, dtype=np.float32)

    xy = umap.UMAP(n_neighbors=15, min_dist=0.1, metric="cosine",
                   random_state=42).fit_transform(vecs)
    # cluster on the 2D layout so cluster colors match the visible structure
    labels = hdbscan.HDBSCAN(min_cluster_size=max(25, len(texts) // 150),
                             min_samples=5, core_dist_n_jobs=1).fit_predict(xy)

    conn.executemany(
        "UPDATE picks SET expl_umap_x=?, expl_umap_y=?, expl_cluster_id=? WHERE pick_id=?",
        [(float(x), float(y), int(cl), pid)
         for (x, y), cl, pid in zip(xy, labels, pick_ids)])
    conn.commit()
    np.savez_compressed(npz_path, pick_ids=np.array(pick_ids), vecs=vecs)

    # model centroids in explanation space
    agg: dict[str, list] = {}
    for mid, (x, y) in zip(model_ids, xy):
        agg.setdefault(mid, []).append((float(x), float(y)))
    for mid, pts in agg.items():
        arr = np.asarray(pts)
        conn.execute("INSERT OR REPLACE INTO model_centroids VALUES (?,?,?,?,?,?)",
                     (mid, "explanation", "all", float(arr[:, 0].mean()),
                      float(arr[:, 1].mean()), len(pts)))
    conn.commit()
    print(f"    explanation space: {len(texts)} points, "
          f"{len(set(labels))} clusters, {len(agg)} model centroids", flush=True)
