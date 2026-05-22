"""SQLite schema for the single-file llmchar.db.

Everything heavy (canonicalization, 2D embedding coords, cluster ids, per-cell
pick frequencies, model similarity) is precomputed at build time and frozen into
the DB, so the static web app only ever runs cheap SELECTs. Full embedding
vectors are NOT stored here (they go to a gitignored .npz); only the 2D
projection + cluster id per row live in the DB to keep it well under 50 MB.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
PRAGMA journal_mode = OFF;
PRAGMA synchronous = OFF;

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- interned long/repetitive strings (system prompts, user prompts) so the
-- Le Chat / claude.ai prompts etc. are stored once, not on every response.
CREATE TABLE texts (
    text_id INTEGER PRIMARY KEY,
    text    TEXT
);

CREATE TABLE models (
    model_id    TEXT PRIMARY KEY,   -- 'mistralai/ministral-8b-2512'
    family      TEXT,               -- mistral, claude, grok, ...
    vendor      TEXT,               -- display vendor
    scale_tier  TEXT,               -- flagship|mid|small|tiny|unknown
    label       TEXT,               -- short display name
    access_path TEXT                -- openrouter|mistral_direct
);

CREATE TABLE characters (
    canonical         TEXT PRIMARY KEY,   -- 'Hannibal Lecter'
    real_or_fictional TEXT,               -- real|fictional|unsure (reconciled)
    domain            TEXT,
    era               TEXT,
    gender            TEXT,
    axis              TEXT,               -- optional thematic axis (nullable)
    wiki_title        TEXT,
    wiki_url          TEXT,
    wiki_summary      TEXT,
    char_umap_x       REAL,
    char_umap_y       REAL,
    char_cluster_id   INTEGER,
    pick_count        INTEGER DEFAULT 0
);

CREATE TABLE responses (
    response_id      INTEGER PRIMARY KEY,
    source_key       TEXT,               -- original cache_key/key (provenance)
    model_id         TEXT REFERENCES models(model_id),
    experiment       TEXT,               -- base_selfid_open | phase0_selfid_single
                                         -- | phase2_darkpersona | prodbare_selfid_open
    condition        TEXT,               -- bare | minimal | production
    condition_detail TEXT,               -- none|production_lechat|production_std|prod_claude|prod_grok
    variant          TEXT,
    temperature      REAL,
    reasoning        TEXT,
    rep              INTEGER,
    kind             TEXT,               -- experiment | control
    persona          TEXT,               -- phase2 dark-persona id (nullable)
    system_text_id   INTEGER REFERENCES texts(text_id),
    prompt_text_id   INTEGER REFERENCES texts(text_id),
    response_content TEXT,
    parse_status     TEXT,
    refused          INTEGER DEFAULT 0,
    n_picks          INTEGER DEFAULT 0,
    cost_usd         REAL,
    latency_s        REAL,
    timestamp        TEXT
);

CREATE TABLE picks (
    pick_id                 INTEGER PRIMARY KEY,
    response_id             INTEGER REFERENCES responses(response_id),
    rank                    INTEGER,
    raw_name                TEXT,
    canonical               TEXT REFERENCES characters(canonical),
    canon_method            TEXT,       -- alias|canonical_exact|fuzzy|new
    canon_score             REAL,
    model_real_or_fictional TEXT,
    domain                  TEXT,
    explanation             TEXT,
    expl_umap_x             REAL,
    expl_umap_y             REAL,
    expl_cluster_id         INTEGER
);

-- precomputed per-cell pick frequency (powers the prod-vs-bare view)
CREATE TABLE pick_freq_by_condition (
    model_id    TEXT,
    canonical   TEXT,
    condition   TEXT,
    experiment  TEXT,
    n_responses INTEGER,   -- denominator: responses in that (model,condition,experiment) cell
    n_picks     INTEGER,   -- responses in which this character appears
    freq        REAL,      -- n_picks / n_responses
    PRIMARY KEY (model_id, canonical, condition, experiment)
);

-- behavioral model-model similarity (cosine of pick-frequency vectors)
CREATE TABLE model_similarity (
    model_a    TEXT,
    model_b    TEXT,
    similarity REAL,
    PRIMARY KEY (model_a, model_b)
);

CREATE TABLE model_clusters (
    model_id   TEXT PRIMARY KEY,
    order_idx  INTEGER,    -- dendrogram leaf order
    cluster_id INTEGER
);

-- per-model centroid in each embedding space (overlay on the maps)
CREATE TABLE model_centroids (
    model_id  TEXT,
    space     TEXT,        -- 'explanation' | 'character'
    condition TEXT,        -- bare|minimal|production|all
    umap_x    REAL,
    umap_y    REAL,
    n         INTEGER,
    PRIMARY KEY (model_id, space, condition)
);
"""

INDEX_SQL = """
CREATE INDEX idx_picks_canonical ON picks(canonical);
CREATE INDEX idx_picks_response  ON picks(response_id);
CREATE INDEX idx_resp_model      ON responses(model_id);
CREATE INDEX idx_resp_filter     ON responses(experiment, condition, variant, temperature);
CREATE INDEX idx_freq_model      ON pick_freq_by_condition(model_id);
CREATE INDEX idx_freq_char       ON pick_freq_by_condition(canonical);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


def create_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(INDEX_SQL)
