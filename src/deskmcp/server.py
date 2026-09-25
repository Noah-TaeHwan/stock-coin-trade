"""The MCP server.

    DESK_BASE_URL=http://127.0.0.1:3333 DESK_API_KEY=... python -m deskmcp.server

Tools are read-only except `run_backtest`, which stores a run but is
idempotent (the same inputs return the same stored run), and
`place_paper_order`, which is only registered when DESK_MCP_ALLOW_ORDERS=1.
Tool annotations are hints for the client, not a security boundary: what a
tool can actually do is decided by the desk API behind it (the API key's
member, the paper account, the profile's data sources).
"""

from __future__ import annotations

import os
from typing import Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from deskmcp.client import DeskAPI, DeskError

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
STRATEGIES = Literal["ma2050", "trend", "pullback", "rsi", "breakout", "momentum"]


def _run(call, *args):
    try:
        return call(*args)
    except DeskError as exc:
        raise ToolError(str(exc)) from None


def build_server(desk: DeskAPI, allow_orders: bool = False) -> MCPServer:
    mcp = MCPServer("noah-trading-desk")

    @mcp.tool(title="Data sources", annotations=READ)
    def list_sources() -> dict[str, Any]:
        """List the market data sources, their licence status and whether this deployment may use them.

        Every number the desk returns carries a `source`; this explains what each source is."""
        return _run(desk.sources)

    @mcp.tool(title="Quote", annotations=READ)
    def get_quote(symbol: str) -> dict[str, Any]:
        """Latest quote for a KRX stock code such as 005930, with its `source` and `attribution`."""
        return _run(desk.quote, symbol)

    @mcp.tool(title="Paper account", annotations=READ)
    def get_account() -> dict[str, Any]:
        """Cash and valuation of the paper-trading account that owns the API key."""
        return _run(desk.account)

    @mcp.tool(title="Positions", annotations=READ)
    def get_positions() -> dict[str, Any]:
        """Stock positions held in the paper account."""
        return _run(desk.positions)

    @mcp.tool(title="Order history", annotations=READ)
    def list_orders(limit: int = 20) -> dict[str, Any]:
        """Most recent paper orders, newest first (1-200)."""
        if not 1 <= limit <= 200:
            raise ToolError("limit must be between 1 and 200")
        return _run(desk.orders, limit)

    @mcp.tool(
        title="Run backtest",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
        ),
    )
    def run_backtest(
        symbol: str,
        strategy: STRATEGIES = "ma2050",
        fast: int | None = None,
        slow: int | None = None,
        fee_bps: float = 1.5,
        slippage_bps: float = 5.0,
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, Any]:
        """Backtest a long-only strategy on stored daily bars and return metrics with a calculation receipt.

        Signals are taken at the close and filled at the next open; costs are in basis points.
        Ratios in `metrics`/`benchmark` are fractions (0.1 = 10%). Quote numbers together with the
        `receiptId`, which `get_backtest` resolves. The same inputs always give the same receipt."""
        payload = {
            "symbol": symbol,
            "strategy": strategy,
            "feeRate": fee_bps / 1e4,
            "slippage": slippage_bps / 1e4,
            **({"fast": fast} if fast is not None else {}),
            **({"slow": slow} if slow is not None else {}),
            **({"start": start} if start else {}),
            **({"end": end} if end else {}),
        }
        body = _run(desk.run_backtest, payload)
        # The daily curve and fills are for charts; keep the tool result small.
        return {
            "receiptId": body["receiptId"],
            "reused": body["reused"],
            "strategy": body["strategy"],
            "parameters": body["parameters"],
            "metrics": body["metrics"],
            "benchmark": body["benchmark"],
            "tradeCount": body["tradeCount"],
            "receipt": body["receipt"],
        }

    @mcp.tool(title="Backtest by receipt", annotations=READ)
    def get_backtest(receipt_id: str) -> dict[str, Any]:
        """Look up a stored backtest by its receipt id: parameters, input hash, sources, metrics."""
        return _run(desk.get_backtest, receipt_id)

    if allow_orders:

        @mcp.tool(
            title="Place paper order",
            annotations=ToolAnnotations(
                read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False
            ),
        )
        def place_paper_order(symbol: str, side: Literal["BUY", "SELL"], quantity: int) -> dict[str, Any]:
            """Place a market order in the paper (mock) account. Not a real brokerage order."""
            if not 1 <= quantity <= 100_000:
                raise ToolError("quantity must be between 1 and 100000")
            return _run(desk.place_order, symbol, side, quantity)

    return mcp


def from_env(env: dict[str, str] | None = None) -> MCPServer:
    env = dict(os.environ if env is None else env)
    desk = DeskAPI(env.get("DESK_BASE_URL", "http://127.0.0.1:3333"), env.get("DESK_API_KEY", ""))
    return build_server(desk, allow_orders=env.get("DESK_MCP_ALLOW_ORDERS") == "1")


def main() -> None:
    from_env().run(transport="stdio")


if __name__ == "__main__":
    main()
