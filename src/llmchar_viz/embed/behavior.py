"""Behavioral model similarity.

Represent each model by its character pick-frequency vector (over the open-vocab
base sweep) and compute cosine similarity between every model pair. A SciPy
linkage gives a dendrogram leaf order + flat clusters so the heatmap reads as
behavioral families.
"""

from __future__ import annotations

import sqlite3

import numpy as np


def run(conn: sqlite3.Connection, experiment: str = "base_selfid_open") -> None:
    rows = conn.execute("""
        SELECT r.model_id, p.canonical, COUNT(*) n
        FROM picks p JOIN responses r ON p.response_id=r.response_id
        WHERE r.experiment=?
        GROUP BY r.model_id, p.canonical
    """, (experiment,)).fetchall()
    if not rows:
        print("    no base picks; skipping behavioral similarity", flush=True)
        return

    models = sorted({m for m, _, _ in rows})
    chars = sorted({c for _, c, _ in rows})
    mi = {m: i for i, m in enumerate(models)}
    ci = {c: i for i, c in enumerate(chars)}
    M = np.zeros((len(models), len(chars)), dtype=np.float64)
    for m, c, n in rows:
        M[mi[m], ci[c]] = n
    # L2-normalize rows -> cosine via dot
    norms = np.linalg.norm(M, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    Mn = M / norms
    sim = Mn @ Mn.T

    conn.execute("DELETE FROM model_similarity")
    conn.executemany("INSERT INTO model_similarity VALUES (?,?,?)",
                     [(models[i], models[j], float(sim[i, j]))
                      for i in range(len(models)) for j in range(len(models))])

    # dendrogram leaf order + flat clusters
    order = list(range(len(models)))
    clusters = [0] * len(models)
    try:
        from scipy.cluster.hierarchy import fcluster, leaves_list, linkage
        from scipy.spatial.distance import squareform
        dist = 1.0 - sim
        np.fill_diagonal(dist, 0.0)
        dist = (dist + dist.T) / 2.0
        Z = linkage(squareform(dist, checks=False), method="average")
        order = list(leaves_list(Z))
        clusters = list(fcluster(Z, t=max(2, len(models) // 4), criterion="maxclust"))
    except Exception as e:
        print(f"    linkage skipped: {e}", flush=True)

    conn.execute("DELETE FROM model_clusters")
    conn.executemany("INSERT INTO model_clusters VALUES (?,?,?)",
                     [(models[leaf], pos, int(clusters[leaf]))
                      for pos, leaf in enumerate(order)])
    conn.commit()
    print(f"    behavioral similarity: {len(models)} models, {len(chars)} chars", flush=True)
