"""HTTP client for the desk's own APIs.

The MCP server never touches the database. Everything goes through the same
HTTP endpoints a browser or script would use, so the server-side checks
(API key, per-key rate limit, paper-account scope, data source registry)
apply to MCP calls exactly as they do to any other client.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import quote

import requests

SYMBOL = re.compile(r"^[A-Za-z0-9^._-]{1,20}$")
RECEIPT = re.compile(r"^[0-9a-f]{64}$")


class DeskError(RuntimeError):
    """A request the desk rejected or could not serve; the message is safe to show."""


@dataclass
class DeskAPI:
    base_url: str
    api_key: str = ""
    timeout: float = 30.0
    session: requests.Session = field(default_factory=requests.Session)

    def _call(self, method: str, path: str, *, auth: bool = False, **kwargs) -> dict:
        headers = {"Accept": "application/json"}
        if auth:
            if not self.api_key:
                raise DeskError("DESK_API_KEY is not set; create a key under 'API 키' in the desk and export it.")
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = self.session.request(
                method, self.base_url.rstrip("/") + path, headers=headers, timeout=self.timeout, **kwargs
            )
        except requests.RequestException as exc:
            raise DeskError(f"desk API unreachable at {self.base_url}: {exc.__class__.__name__}") from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400:
            message = body.get("message") or body.get("error") or f"HTTP {response.status_code}"
            raise DeskError(f"{message} (HTTP {response.status_code})")
        return body

    # Paper account (Open API, needs an API key)
    def quote(self, symbol: str) -> dict:
        return self._call("GET", f"/openapi/v1/quote/{quote(_symbol(symbol), safe='')}", auth=True)

    def account(self) -> dict:
        return self._call("GET", "/openapi/v1/account", auth=True)

    def positions(self) -> dict:
        return self._call("GET", "/openapi/v1/positions", auth=True)

    def orders(self, limit: int) -> dict:
        return self._call("GET", "/openapi/v1/orders", auth=True, params={"limit": limit})

    def place_order(self, symbol: str, side: str, quantity: int) -> dict:
        body = {"symbol": _symbol(symbol), "side": side, "quantity": quantity}
        return self._call("POST", "/openapi/v1/orders", auth=True, json=body)

    # Research (quant API)
    def sources(self) -> dict:
        return self._call("GET", "/api/quant/sources")

    def run_backtest(self, payload: dict) -> dict:
        return self._call("POST", "/api/quant/backtests", json=payload)

    def get_backtest(self, receipt_id: str) -> dict:
        if not RECEIPT.match(receipt_id):
            raise DeskError("receipt_id must be 64 lowercase hex characters")
        return self._call("GET", f"/api/quant/backtests/{receipt_id}")


def _symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if not SYMBOL.match(symbol):
        raise DeskError("symbol must be 1-20 letters, digits or ^ . _ -")
    return symbol
