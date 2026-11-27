#!/usr/bin/env python3
"""CLI: build thin or full PDF from snapshot, or extract then build."""

from __future__ import annotations

import src.macos_libs  # noqa: F401  — before WeasyPrint (Homebrew dylib path)

import argparse
from pathlib import Path

from src.extract import run_extract
from src.report import build_report, load_config


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    report_cfg = cfg.get("report") or {}
    default_layout = report_cfg.get("default_layout") or "full"
    default_type = report_cfg.get("default_type") or "auto"

    p = argparse.ArgumentParser(
        description="Build noise measurement PDF report (thin or full layout)"
    )
    p.add_argument("--snapshot", type=Path, help="Existing snapshot directory")
    p.add_argument("--start", help="Local start (extract if no --snapshot)")
    p.add_argument("--end", help="Local end exclusive")
    p.add_argument(
        "--layout",
        choices=("thin", "full"),
        default=default_layout,
        help=f"PDF layout (default: {default_layout})",
    )
    p.add_argument(
        "--type",
        dest="summary_type",
        choices=("auto", "weekly", "monthly", "full"),
        default=default_type,
        help=f"Summary framing for full layout (default: {default_type})",
    )
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

    print(
        f"[report] PDF építés ({args.layout}"
        f"{', type=' + args.summary_type if args.layout == 'full' else ''}): {snap}",
        flush=True,
    )
    paths = build_report(
        snap,
        layout=args.layout,
        summary_type=args.summary_type if args.layout == "full" else None,
        config=cfg,
    )
    print(f"[report] pdf:  {paths.pdf_path}", flush=True)
    print(f"[report] html: {paths.html_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
