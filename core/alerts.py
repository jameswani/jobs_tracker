"""Alerting: macOS notification + stderr. Never raises."""
from __future__ import annotations

import subprocess
import sys


def notify(title: str, message: str):
    print(f"[{title}] {message}", file=sys.stderr)
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{message[:180]}" with title "{title[:60]}"'],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass
