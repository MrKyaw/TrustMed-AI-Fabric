"""Allow ``python -m trustmed_fabric`` to behave like the CLI."""

from __future__ import annotations

from trustmed_fabric.cli import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
