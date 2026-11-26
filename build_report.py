#!/usr/bin/env python3
"""CLI: build thin PDF from snapshot, or extract then build."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.extract import run_extract
from src.report import build_thin_report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build thin daily LAeq PDF report")
    p.add_argument("--snapshot", type=Path, help="Existing snapshot directory")
    p.add_argument("--start", help="Local start (extract if no --snapshot)")
    p.add_argument("--end", help="Local end exclusive")
    args = p.parse_args(argv)

    if args.snapshot:
        snap = args.snapshot
        print(f"[report] meglévő snapshot: {snap}", flush=True)
    else:
        if not args.start or not args.end:
            p.error("provide --snapshot or both --start and --end")
        print(
            f"[report] extract indul: {args.start} → {args.end}",
            flush=True,
        )
        print(
            "[report] többnapos időszaknál ez több percig tarthat "
            "(először a sound_sample SQL)…",
            flush=True,
        )
        result = run_extract(args.start, args.end)
        snap = result.snapshot_dir
        print(f"[report] extract_sha256: {result.extract_hash}", flush=True)

    print(f"[report] PDF építés: {snap}", flush=True)
    paths = build_thin_report(snap)
    print(f"[report] pdf:  {paths.pdf_path}", flush=True)
    print(f"[report] html: {paths.html_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
