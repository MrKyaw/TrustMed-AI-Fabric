# Testing

```bash
PYTHONPATH=src python3 -m pytest
PYTHONPATH=src python3 -m pytest --cov=trustmed_fabric --cov-report=term-missing
PYTHONPATH=src python3 -m ruff check src tests
PYTHONPATH=src python3 -m mypy src
```

The suite contains 96 tests across unit, integration, API, MCP, CLI, property,
security and contract categories. The coverage gate is 88% and the current
result is 90%.
