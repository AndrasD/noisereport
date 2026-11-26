#!/usr/bin/env python3
"""CLI: offline machine detection on a snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.detect import run_detection


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Detect machine events offline")
    p.add_argument("snapshot", type=Path)
    p.add_argument("--config", type=Path, default=None)
    args = p.parse_args(argv)

    events, score, out = run_detection(args.snapshot, detector_config_path=args.config)
    print(
        json.dumps(
            {
                "events": len(events),
                "observations": score.observations,
                "hits": score.hits,
                "hit_rate": round(score.hit_rate, 3),
                "output": str(out),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
