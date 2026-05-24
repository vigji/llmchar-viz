.PHONY: help install classify db serve prodgen clean

help:
	@echo "llmchar-viz targets:"
	@echo "  make install   - create uv env with embed extras"
	@echo "  make classify  - LLM-tag characters on 3 axes -> data/char_specs.json (needs OPENROUTER_API_KEY)"
	@echo "  make db        - build the single-file SQLite DB offline (data/.. -> llmchar.db)"
	@echo "  make serve     - serve the static web explorer (LAN; http://localhost:8000/web/)"
	@echo "  make prodgen   - optional bare-vs-deployed-prompt probe (not in the default DB)"
	@echo "  make clean     - remove the built DB and vector dumps"

install:
	uv sync --extra embed

# Network step: tag characters (alignment / expertise / nature); cached + committed.
classify:
	uv run python -m llmchar_viz.classify_characters

# Optional network step: bare-vs-deployed-prompt probe (kept for reuse; not loaded by `make db`).
prodgen:
	uv run llmchar-viz-prodgen

# Offline step: ETL + dedup + embeddings + aggregates -> llmchar.db
db:
	uv run --extra embed llmchar-viz-build

serve:
	python3 scripts/serve.py 8000

clean:
	rm -f llmchar.db vectors_*.npz
