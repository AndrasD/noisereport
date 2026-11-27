"""Ensure Homebrew shared libs are findable on macOS (WeasyPrint / Pango).

Set before importing weasyprint. Safe no-op on other platforms.
"""

from __future__ import annotations

import os
import sys


def ensure_homebrew_dylib_path() -> None:
    if sys.platform != "darwin":
        return
    homebrew_lib = "/opt/homebrew/lib"
    if not os.path.isdir(homebrew_lib):
        return
    key = "DYLD_FALLBACK_LIBRARY_PATH"
    parts = [p for p in os.environ.get(key, "").split(":") if p]
    if homebrew_lib not in parts:
        os.environ[key] = ":".join([homebrew_lib, *parts])


ensure_homebrew_dylib_path()
