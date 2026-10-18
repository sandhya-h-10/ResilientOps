.PHONY: install serve demo evaluate test lint

install:
	uv sync --frozen --all-extras

serve:
	.venv/bin/resilientops serve

demo:
	.venv/bin/resilientops demo --approve

evaluate:
	.venv/bin/resilientops evaluate

test:
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check src tests scripts
	.venv/bin/ruff format --check src tests scripts
