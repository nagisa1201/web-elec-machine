#!/usr/bin/env python3
"""Command-line entry point: ``python -m web``.

See ``web/README.md`` for usage and examples.
"""

from __future__ import annotations

from .config import Config
from .server import run


def main(argv: list[str] | None = None) -> None:
    run(Config.from_args(argv))


if __name__ == "__main__":
    main()
