.PHONY: help install prodgen db serve clean

help:
	@echo "llmchar-viz targets:"
	@echo "  make install   - create uv env with embed extras"
	@echo "  make prodgen   - run the new prod-vs-bare generations (network + small \$\$; needs keys)"
	@echo "  make db        - build the single-file SQLite DB offline (data/.. -> llmchar.db)"
	@echo "  make serve     - serve the static web explorer at http://localhost:8000/web/"
	@echo "  make clean     - remove the built DB and vector dumps"

install:
	uv sync --extra embed

# Network step: writes base-schema CallRecord JSON under data/raw/ (prodbare experiment).
prodgen:
	uv run llmchar-viz-prodgen

# Offline step: ETL + dedup + embeddings + aggregates -> llmchar.db
db:
	uv run --extra embed llmchar-viz-build

serve:
	python3 scripts/serve.py 8000

clean:
	rm -f llmchar.db vectors_*.npz
