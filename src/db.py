"""Read-only PostgreSQL access for noisereport.

This module must only issue SELECT (and read-only introspection). Never INSERT/UPDATE/DELETE.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

_ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    load_dotenv(_ROOT / ".env")


def database_url() -> str:
    load_env()
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env "
            "(or copy from ../noise/database/.env)."
        )
    return url


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url(), pool_pre_ping=True)


@contextmanager
def connect(engine: Engine | None = None) -> Iterator[Connection]:
    eng = engine or make_engine()
    with eng.connect() as conn:
        yield conn


def smoke_select(conn: Connection) -> dict[str, int | str]:
    """Minimal read check against the measurement archive."""
    sound = conn.execute(
        text("SELECT count(*)::bigint AS n FROM noise_monitor.sound_sample")
    ).scalar_one()
    schemas = conn.execute(
        text(
            """
            SELECT nspname
            FROM pg_namespace
            WHERE nspname IN ('noise_monitor', 'noise_report')
            ORDER BY 1
            """
        )
    ).scalars().all()
    return {
        "sound_sample_count": int(sound),
        "schemas": ", ".join(schemas),
    }


def main() -> None:
    with connect() as conn:
        info = smoke_select(conn)
    print("ok: connected (SELECT)")
    print(f"  schemas: {info['schemas']}")
    print(f"  noise_monitor.sound_sample rows: {info['sound_sample_count']}")


if __name__ == "__main__":
    main()
