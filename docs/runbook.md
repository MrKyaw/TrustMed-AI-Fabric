# Runbook

## Start locally

```bash
PYTHONPATH=src python3 -m uvicorn trustmed_fabric.api:get_app --factory --port 8080
```

## Seed data

```bash
PYTHONPATH=src python3 -m trustmed_fabric.cli seed --reset
```

## Verify audit chain

```bash
PYTHONPATH=src python3 -m trustmed_fabric.cli audit verify
```

## Export audit ledger

```bash
PYTHONPATH=src python3 -m trustmed_fabric.cli audit export --output ledger.ndjson
```

## Run evaluation

```bash
PYTHONPATH=src python3 -m trustmed_fabric.cli eval
```
