"""Package entry point: python -m workbench <cmd>."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
