.PHONY: start-worker test lint format

start-worker:
	PYTHONPATH=src python -m entrypoints.worker

test:
	PYTHONPATH=src python -m pytest tests/ -q

lint:
	ruff check src tests

format:
	ruff format src tests
