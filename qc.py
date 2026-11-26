#!/usr/bin/env python3
"""CLI: run QC on a snapshot directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.qc import load_config, run_qc, write_qc_outputs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="QC a Parquet snapshot")
    p.add_argument("snapshot", type=Path, help="Path to snapshot directory with manifest.json")
    args = p.parse_args(argv)

    cfg = load_config()
    report = run_qc(args.snapshot, config=cfg)
    out_dir = Path(cfg.get("paths", {}).get("output_dir", "output"))
    json_path, gaps_path = write_qc_outputs(report, out_dir)

    summary = {
        "coverage_ratio": report.coverage_ratio,
        "sound_sample_count": report.sound_sample_count,
        "gaps": len(report.gaps),
        "impossible_level_count": report.impossible_level_count,
        "notes": report.notes,
        "qc_json": str(json_path),
        "gaps_csv": str(gaps_path),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
