.PHONY: start-worker verify lint

start-worker:
	uv run python -m src.entrypoints.worker

verify: lint
	uv run python -c "import src.workflows.inbound_call"

lint:
	uv run ruff check src
