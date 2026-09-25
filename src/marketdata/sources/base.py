"""Interface every daily bar source implements."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from marketdata.bars import Bar


class BarSource(Protocol):
    id: str  # registry key in config/data_sources.toml

    def fetch_daily(self, symbol: str, start: date, end: date) -> list[Bar]:
        """Daily bars for start..end inclusive, oldest first."""
        ...
