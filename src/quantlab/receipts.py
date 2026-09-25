"""Calculation receipts: what went into a backtest, hashed.

The receipt id depends only on the engine version, the input bars and the
parameters, so running the same backtest twice gives the same id (and the
store keeps one run). The git commit is recorded but not part of the id.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime

from marketdata.bars import Bar, checksum
from quantlab import ENGINE_VERSION


def git_sha() -> str:
    if os.environ.get("GIT_SHA"):
        return os.environ["GIT_SHA"]
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=True
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def make(bars: Sequence[Bar], params: dict) -> dict:
    input_sha = checksum(bars)
    canonical = json.dumps(
        {"engine": ENGINE_VERSION, "input": input_sha, "params": params}, sort_keys=True, separators=(",", ":")
    )
    return {
        "receiptId": hashlib.sha256(canonical.encode()).hexdigest(),
        "engineVersion": ENGINE_VERSION,
        "inputSha256": input_sha,
        "params": params,
        "sources": sorted({bar.source for bar in bars}),
        "firstBar": bars[0].ts.isoformat() if bars else None,
        "lastBar": bars[-1].ts.isoformat() if bars else None,
        "barCount": len(bars),
        "gitSha": git_sha(),
        "createdAt": datetime.now(UTC).isoformat(),
    }
