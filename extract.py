#!/usr/bin/env python3
"""CLI: extract a local-time period into Parquet + SHA-256 manifest."""

from __future__ import annotations

import argparse
import sys

from src.extract import run_extract


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Extract measurement snapshot (read-only)")
    p.add_argument("--start", required=True, help="Local start YYYY-MM-DD[THH:MM] (Europe/Budapest)")
    p.add_argument("--end", required=True, help="Local end (exclusive) YYYY-MM-DD[THH:MM]")
    args = p.parse_args(argv)

    result = run_extract(args.start, args.end)
    print(f"snapshot: {result.snapshot_dir}")
    print(f"manifest: {result.manifest_path}")
    print(f"extract_sha256: {result.extract_hash}")
    for table, n in sorted(result.row_counts.items()):
        print(f"  {table}: {n} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
