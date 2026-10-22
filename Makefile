PYTHON ?= python3
SRC = PYTHONPATH=src

.PHONY: test lint typecheck eval

test:
	$(SRC) $(PYTHON) -m pytest

lint:
	$(SRC) $(PYTHON) -m ruff check src tests

typecheck:
	$(SRC) $(PYTHON) -m mypy src

eval:
	$(SRC) $(PYTHON) -m trustmed_fabric.cli eval
