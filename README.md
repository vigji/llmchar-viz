# llmchar-viz

An explorable web view of the **base exploration** behind the `llmchar` study: an
open-vocabulary sweep where ~21 LLMs were each asked *"name the 5 characters you most
identify with."* That sweep is what first surfaced the headline finding — a small Mistral
model (Ministral-8B) names **Hannibal Lecter** ~50% of the time when given no system
prompt, and a real deployed "Le Chat" system prompt suppresses that ~37×.

This repo packages those responses into a single portable **SQLite** file and a **static,
serverless web explorer** (SQLite compiled to WebAssembly via sql.js — the `.db` loads and
is queried entirely in your browser).

**Live: https://vigji.github.io/llmchar-viz/**

## What's inside

- **`llmchar.db`** — the single-file, directly-queryable database (the committed deliverable).
- **`web/`** — the static explorer (open locally now; GitHub Pages-ready).
- **`src/llmchar/`** — the *ported* base-exploration generation pipeline (so the data is
  reproducible).
- **`src/llmchar_viz/`** — the DB builder: ETL, canonicalization/dedup, embeddings, aggregates.

## Explore it locally

```bash
make serve            # then open http://localhost:8000/web/
```

No build step, no server code — just static files reading `llmchar.db` in the browser.

## Rebuild the database

The DB is a pure derived artifact. Rebuild it from the raw responses:

```bash
make install          # uv env incl. local embedding model deps
# (place/regenerate the raw response JSON under data/ — see "Reproduce the data")
make db               # ETL + dedup + embeddings -> llmchar.db   (offline, no API key)
```

### Reproduce the data (optional, costs API spend)

The raw per-call JSON is **not** committed (large, regenerable). Two paths:

1. **Copy** the existing `data/raw`, `data/phase0/raw`, `data/phase2/raw` from the source
   `llmchar` repo into this repo's gitignored `data/`.
2. **Regenerate** the base sweep with the ported CLI (needs `OPENROUTER_API_KEY` in `.env`):
   ```bash
   uv run llmchar run --tier PILOT
   ```

### Character feature labels

The character map / "Character features" view need each character tagged on three axes
(moral alignment, expertise, nature). `make classify` does this once via a cheap LLM
(needs `OPENROUTER_API_KEY`) and caches the result to the committed `data/char_specs.json`,
so subsequent `make db` runs are offline and reproducible.

### Optional extras

`make prodgen` runs a separate bare-vs-deployed-system-prompt probe (Mistral / Claude / Grok);
its data is not loaded into the default DB but the code is kept for reuse.

## Deployment (GitHub Pages)

Live at **https://vigji.github.io/llmchar-viz/**, served by **Pages → Deploy from a branch**
(`main`, root). `.nojekyll` makes Pages copy files as-is, and every asset path is
`import.meta.url`-relative, so the same code works locally and at the `/llmchar-viz/` base
path. **Pushing to `main` re-publishes automatically** (~1 min) — including a freshly built
`llmchar.db`.

To reproduce the setup: make the repo public, then Settings → Pages → Source = "Deploy from a
branch", Branch = `main` / `/ (root)`. (A GitHub Actions template also exists at `deploy/pages.yml`
if you'd rather publish only `web/` + the DB; it needs the `workflow` token scope.)
For a custom domain, add a `CNAME` file with the domain and point DNS at GitHub Pages.

## Provenance

Data and method come from the `llmchar` research project. Findings shown here are the
exploratory base layer; see the source repo for the pre-registered confirmatory analyses.
