"""Convert marketdata bars to the DataFrame the engine uses."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from marketdata.bars import Bar

COLUMNS = ["open", "high", "low", "close", "volume"]


def bars_to_frame(bars: Sequence[Bar]) -> pd.DataFrame:
    """Oldest-first OHLCV indexed by bar time. Duplicate timestamps are an error."""
    frame = (
        pd.DataFrame(
            [(b.ts, b.open, b.high, b.low, b.close, b.volume) for b in bars],
            columns=["ts", *COLUMNS],
        )
        .set_index("ts")
        .sort_index()
    )
    if frame.index.has_duplicates:
        raise ValueError("bars contain duplicate timestamps")
    return frame.astype(float)
