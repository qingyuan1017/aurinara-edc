"""Build the async SQLAlchemy URL from split ECS settings before exec."""

from __future__ import annotations

import os
import sys
from urllib.parse import quote_plus


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: aws_entrypoint.py COMMAND [ARG ...]")
    required = ["DATABASE_HOST", "DATABASE_NAME", "DATABASE_USER", "DATABASE_PASSWORD"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"missing database settings: {', '.join(missing)}")
    user = quote_plus(os.environ["DATABASE_USER"])
    password = quote_plus(os.environ["DATABASE_PASSWORD"])
    host = os.environ["DATABASE_HOST"]
    port = os.environ.get("DATABASE_PORT", "5432")
    name = quote_plus(os.environ["DATABASE_NAME"])
    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}?ssl=require"
    )
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
