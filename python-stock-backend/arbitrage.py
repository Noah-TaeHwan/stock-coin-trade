"""코인 거래소 간 가격 차이(김프·국내 스프레드)와 차익 순손익 모의 계산.

공개 시세·호가·캔들만 조회한다. 주문·출금 기능은 없다.
해외 거래소는 USDT 마켓을 쓰고, 원화 환산은 업비트 KRW-USDT 가격을 기준으로 한다.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

import requests
from flask import Blueprint, jsonify, request

arb_bp = Blueprint("arbitrage", __name__, url_prefix="/api/arb")

COINS = ["BTC", "ETH", "XRP", "SOL", "DOGE", "ADA", "TRX", "LINK"]

# 테이커 수수료(%)는 각 거래소 공개 수수료 페이지의 기본 등급 기준 참고값이다.
# 쿠폰·등급·이벤트로 달라지므로 화면에서 사용자가 고칠 수 있게 한다.
FEE_REFERENCE_DATE = "2026-09-24"
EXCHANGES: dict[str, dict[str, Any]] = {
    "UPBIT":   {"name": "업비트", "quote": "KRW",  "takerFeePct": 0.05, "feeUrl": "https://upbit.com/service_center/guide"},
    "BITHUMB": {"name": "빗썸",   "quote": "KRW",  "takerFeePct": 0.04, "feeUrl": "https://www.bithumb.com/react/info/fee/inout"},
    "COINONE": {"name": "코인원", "quote": "KRW",  "takerFeePct": 0.20, "feeUrl": "https://coinone.co.kr/support/fee-guide"},
    "KORBIT":  {"name": "코빗",   "quote": "KRW",  "takerFeePct": 0.20, "feeUrl": "https://www.korbit.co.kr/info/fee"},
    "OKX":     {"name": "OKX",    "quote": "USDT", "takerFeePct": 0.10, "feeUrl": "https://www.okx.com/fees"},
    "BINANCE": {"name": "Binance", "quote": "USDT", "takerFeePct": 0.10, "feeUrl": "https://www.binance.com/en/fee/schedule"},
}
KRW_EXCHANGES = [code for code, meta in EXCHANGES.items() if meta["quote"] == "KRW"]
GLOBAL_EXCHANGES = [code for code, meta in EXCHANGES.items() if meta["quote"] == "USDT"]

# 전송 참고표. 출금 수수료는 거래소·네트워크마다 다르고 수시로 바뀌는 대표값(코인 단위)이다.
# 예상 전송 시간 = 블록 시간 × 입금 반영에 필요한 확인 수. 거래소 출금 심사·트래블룰 확인 시간은 빠져 있다.
NETWORKS: dict[str, dict[str, Any]] = {
    "BTC":  {"network": "Bitcoin",        "bithumbNet": "BTC",  "blockSec": 600, "confirmations": 2,  "withdrawFee": 0.0005},
    "ETH":  {"network": "Ethereum",       "bithumbNet": "ETH",  "blockSec": 12,  "confirmations": 64, "withdrawFee": 0.005},
    "XRP":  {"network": "XRP Ledger",     "bithumbNet": "XRP",  "blockSec": 4,   "confirmations": 1,  "withdrawFee": 1},
    "SOL":  {"network": "Solana",         "bithumbNet": "SOL",  "blockSec": 0.4, "confirmations": 32, "withdrawFee": 0.01},
    "DOGE": {"network": "Dogecoin",       "bithumbNet": "DOGE", "blockSec": 60,  "confirmations": 20, "withdrawFee": 5},
    "ADA":  {"network": "Cardano",        "bithumbNet": "ADA",  "blockSec": 20,  "confirmations": 15, "withdrawFee": 1},
    "TRX":  {"network": "TRON",           "bithumbNet": "TRX",  "blockSec": 3,   "confirmations": 20, "withdrawFee": 1},
    "LINK": {"network": "Ethereum ERC-20", "bithumbNet": "ETH",  "blockSec": 12,  "confirmations": 64, "withdrawFee": 0.5},
}

BTC_TX_VBYTES = 140  # 입력 1개·출력 2개 SegWit 송금의 대략적 크기
TICKER_TTL = 5
ORDERBOOK_TTL = 5
FX_TTL = 3600
HISTORY_TTL = 60
HTTP_TIMEOUT = 4
DEFAULT_SIZE_KRW = 1_000_000
MIN_SIZE_KRW = 10_000
MAX_SIZE_KRW = 1_000_000_000

_HEADERS = {"User-Agent": "NoahTradingDesk/1.0 (+arbitrage monitor)"}
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="arb")
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


class SourceError(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def _cached(key: str, ttl: float, loader: Callable[[], Any]) -> Any:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = loader()
    with _cache_lock:
        _cache[key] = (now + ttl, value)
    return value


def _get_json(url: str, params: dict | None = None) -> Any:
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise SourceError("error", f"연결 실패: {exc.__class__.__name__}") from exc
    # Binance는 지원하지 않는 지역에서 451, CloudFront 차단은 403을 돌려준다.
    if resp.status_code in (403, 451):
        raise SourceError("blocked", f"접속 지역 제한 (HTTP {resp.status_code})")
    if not resp.ok:
        raise SourceError("error", f"HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise SourceError("error", "JSON 응답이 아님") from exc


def _num(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _pct(ratio: float | None) -> float | None:
    return None if ratio is None else round(ratio * 100, 4)


# ── 시세 ───────────────────────────────────────────────────────────────────
# 각 함수는 {심볼: 가격}을 돌려준다. 원화 거래소에는 USDT 가격도 넣는다.

def _tickers_upbit() -> dict[str, float]:
    markets = ",".join(f"KRW-{s}" for s in [*COINS, "USDT"])
    body = _get_json("https://api.upbit.com/v1/ticker", {"markets": markets})
    return {row["market"].split("-")[1]: float(row["trade_price"]) for row in body}


def _tickers_bithumb() -> dict[str, float]:
    data = _get_json("https://api.bithumb.com/public/ticker/ALL_KRW").get("data") or {}
    return {s: p for s in [*COINS, "USDT"] if (p := _num((data.get(s) or {}).get("closing_price")))}


def _tickers_coinone() -> dict[str, float]:
    rows = _get_json("https://api.coinone.co.kr/public/v2/ticker_new/KRW").get("tickers") or []
    wanted = {*COINS, "USDT"}
    return {s: p for row in rows if (s := str(row.get("target_currency", "")).upper()) in wanted and (p := _num(row.get("last")))}


def _tickers_korbit() -> dict[str, float]:
    symbols = ",".join(f"{s.lower()}_krw" for s in [*COINS, "USDT"])
    rows = _get_json("https://api.korbit.co.kr/v2/tickers", {"symbol": symbols}).get("data") or []
    return {row["symbol"].split("_")[0].upper(): p for row in rows if (p := _num(row.get("close")))}


def _tickers_okx() -> dict[str, float]:
    rows = _get_json("https://www.okx.com/api/v5/market/tickers", {"instType": "SPOT"}).get("data") or []
    wanted = {f"{s}-USDT": s for s in COINS}
    return {wanted[row["instId"]]: p for row in rows if row.get("instId") in wanted and (p := _num(row.get("last")))}


def _tickers_binance() -> dict[str, float]:
    symbols = "[" + ",".join(f'"{s}USDT"' for s in COINS) + "]"
    rows = _get_json("https://api.binance.com/api/v3/ticker/price", {"symbols": symbols})
    return {row["symbol"][:-4]: p for row in rows if (p := _num(row.get("price")))}


TICKER_FETCHERS: dict[str, Callable[[], dict[str, float]]] = {
    "UPBIT": _tickers_upbit,
    "BITHUMB": _tickers_bithumb,
    "COINONE": _tickers_coinone,
    "KORBIT": _tickers_korbit,
    "OKX": _tickers_okx,
    "BINANCE": _tickers_binance,
}


def _fetch_usd_krw() -> dict[str, Any]:
    body = _get_json("https://open.er-api.com/v6/latest/USD")
    return {"usdKrw": _num((body.get("rates") or {}).get("KRW")), "updatedAt": body.get("time_last_update_utc")}


def _run_sources(fetchers: dict[str, Callable[[], Any]]) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    futures = {code: _POOL.submit(fn) for code, fn in fetchers.items()}
    results: dict[str, Any] = {}
    status: dict[str, dict[str, str]] = {}
    for code, future in futures.items():
        try:
            results[code] = future.result()
            status[code] = {"status": "ok"}
        except SourceError as exc:
            status[code] = {"status": exc.status, "message": str(exc)}
        except Exception as exc:  # 응답 형식이 바뀐 경우도 해당 소스만 실패로 처리한다.
            status[code] = {"status": "error", "message": f"응답 해석 실패: {exc.__class__.__name__}"}
    return results, status


def _usdt_krw(tickers: dict[str, dict[str, float]]) -> tuple[float | None, str | None]:
    for code in KRW_EXCHANGES:
        price = (tickers.get(code) or {}).get("USDT")
        if price:
            return price, code
    return None, None


def build_snapshot(tickers: dict[str, dict[str, float]], usd_krw: float | None) -> dict[str, Any]:
    usdt_krw, usdt_source = _usdt_krw(tickers)
    coins = []
    for symbol in COINS:
        prices: dict[str, dict[str, float | None]] = {}
        for code, meta in EXCHANGES.items():
            native = (tickers.get(code) or {}).get(symbol)
            krw = native if meta["quote"] == "KRW" else (native * usdt_krw if native and usdt_krw else None)
            prices[code] = {"native": native, "krw": krw}

        ref_global_code = next((c for c in GLOBAL_EXCHANGES if prices[c]["native"]), None)
        ref_usdt = prices[ref_global_code]["native"] if ref_global_code else None
        ref_domestic_code = next((c for c in KRW_EXCHANGES if prices[c]["krw"]), None)
        ref_krw = prices[ref_domestic_code]["krw"] if ref_domestic_code else None

        premium_by_exchange = {
            code: _pct(prices[code]["krw"] / (ref_usdt * usdt_krw) - 1) if prices[code]["krw"] and ref_usdt and usdt_krw else None
            for code in KRW_EXCHANGES
        }
        domestic = [(prices[c]["krw"], c) for c in KRW_EXCHANGES if prices[c]["krw"]]
        low = min(domestic) if domestic else None
        high = max(domestic) if domestic else None
        coins.append({
            "symbol": symbol,
            "prices": prices,
            "domesticRef": ref_domestic_code,
            "globalRef": ref_global_code,
            "kimpUsdtPct": _pct(ref_krw / (ref_usdt * usdt_krw) - 1) if ref_krw and ref_usdt and usdt_krw else None,
            "kimpFxPct": _pct(ref_krw / (ref_usdt * usd_krw) - 1) if ref_krw and ref_usdt and usd_krw else None,
            "premiumUsdtByExchange": premium_by_exchange,
            "domesticSpread": {
                "pct": _pct(high[0] / low[0] - 1) if low and high and len(domestic) > 1 else None,
                "low": low[1] if low else None,
                "high": high[1] if high else None,
            },
        })
    return {
        "fx": {
            "usdKrw": usd_krw,
            "usdtKrw": usdt_krw,
            "usdtSource": usdt_source,
            "usdtPremiumPct": _pct(usdt_krw / usd_krw - 1) if usdt_krw and usd_krw else None,
        },
        "coins": coins,
    }


def _load_snapshot() -> dict[str, Any]:
    tickers, status = _run_sources(TICKER_FETCHERS)
    try:
        fx = _cached("fx", FX_TTL, _fetch_usd_krw)
        status["FX"] = {"status": "ok"}
    except SourceError as exc:
        fx = {"usdKrw": None, "updatedAt": None}
        status["FX"] = {"status": exc.status, "message": str(exc)}
    snapshot = build_snapshot(tickers, fx["usdKrw"])
    snapshot["fx"]["usdKrwUpdatedAt"] = fx["updatedAt"]
    snapshot["exchanges"] = {code: {"name": meta["name"], "quote": meta["quote"]} for code, meta in EXCHANGES.items()}
    snapshot["sources"] = status
    snapshot["fetchedAt"] = int(time.time() * 1000)
    return snapshot


@arb_bp.get("/snapshot")
def snapshot():
    return jsonify(_cached("snapshot", TICKER_TTL, _load_snapshot))


# ── 호가 기반 순스프레드 ───────────────────────────────────────────────────
# 호가는 [(가격, 수량)] 목록으로 맞춘다. asks는 낮은 가격부터, bids는 높은 가격부터.

def _levels(rows: list, price_key: Any, qty_key: Any) -> list[tuple[float, float]]:
    out = []
    for row in rows or []:
        price, qty = _num(row[price_key]), _num(row[qty_key])
        if price and qty:
            out.append((price, qty))
    return out


def _book_upbit(symbol: str) -> dict:
    units = (_get_json("https://api.upbit.com/v1/orderbook", {"markets": f"KRW-{symbol}"}) or [{}])[0].get("orderbook_units") or []
    return {"asks": _levels(units, "ask_price", "ask_size"), "bids": _levels(units, "bid_price", "bid_size")}


def _book_bithumb(symbol: str) -> dict:
    data = _get_json(f"https://api.bithumb.com/public/orderbook/{symbol}_KRW", {"count": 30}).get("data") or {}
    return {"asks": _levels(data.get("asks"), "price", "quantity"), "bids": _levels(data.get("bids"), "price", "quantity")}


def _book_coinone(symbol: str) -> dict:
    body = _get_json(f"https://api.coinone.co.kr/public/v2/orderbook/KRW/{symbol}", {"size": 15})
    return {"asks": _levels(body.get("asks"), "price", "qty"), "bids": _levels(body.get("bids"), "price", "qty")}


def _book_korbit(symbol: str) -> dict:
    data = _get_json("https://api.korbit.co.kr/v2/orderbook", {"symbol": f"{symbol.lower()}_krw"}).get("data") or {}
    return {"asks": _levels(data.get("asks"), "price", "qty"), "bids": _levels(data.get("bids"), "price", "qty")}


def _book_okx(symbol: str) -> dict:
    data = (_get_json("https://www.okx.com/api/v5/market/books", {"instId": f"{symbol}-USDT", "sz": 50}).get("data") or [{}])[0]
    return {"asks": _levels(data.get("asks"), 0, 1), "bids": _levels(data.get("bids"), 0, 1)}


def _book_binance(symbol: str) -> dict:
    body = _get_json("https://api.binance.com/api/v3/depth", {"symbol": f"{symbol}USDT", "limit": 50})
    return {"asks": _levels(body.get("asks"), 0, 1), "bids": _levels(body.get("bids"), 0, 1)}


BOOK_FETCHERS: dict[str, Callable[[str], dict]] = {
    "UPBIT": _book_upbit,
    "BITHUMB": _book_bithumb,
    "COINONE": _book_coinone,
    "KORBIT": _book_korbit,
    "OKX": _book_okx,
    "BINANCE": _book_binance,
}


def vwap_buy(asks: list[tuple[float, float]], spend: float) -> dict[str, Any]:
    """spend(호가 통화)만큼 매도 호가를 위에서부터 사들인다."""
    remaining, qty = spend, 0.0
    for price, size in asks:
        cost = price * size
        if cost >= remaining:
            qty += remaining / price
            remaining = 0.0
            break
        qty += size
        remaining -= cost
    filled = spend - remaining
    return {"qty": qty, "avgPrice": filled / qty if qty else None, "insufficient": remaining > 1e-9}


def vwap_sell(bids: list[tuple[float, float]], qty: float) -> dict[str, Any]:
    """qty를 매수 호가에 위에서부터 판다."""
    remaining, proceeds = qty, 0.0
    for price, size in bids:
        take = min(size, remaining)
        proceeds += take * price
        remaining -= take
        if remaining <= 1e-12:
            remaining = 0.0
            break
    sold = qty - remaining
    return {"proceeds": proceeds, "avgPrice": proceeds / sold if sold else None, "insufficient": remaining > 1e-12}


def simulate_pair(buy_book: dict, sell_book: dict, size_krw: float, buy_fee_pct: float, sell_fee_pct: float,
                  withdraw_fee: float) -> dict[str, Any]:
    """A에서 size_krw만큼 사서 B로 보낸 뒤 모두 판다. 두 호가는 원화로 환산돼 있어야 한다.

    수수료는 체결 금액·수량에서 테이커 비율만큼 뺀다. 출금 수수료는 코인 단위로 뺀다.
    """
    buy = vwap_buy(buy_book["asks"], size_krw)
    if not buy["qty"]:
        return {"ok": False, "reason": "매수 호가 없음"}
    qty_after_buy = buy["qty"] * (1 - buy_fee_pct / 100)
    qty_arrived = qty_after_buy - withdraw_fee
    if qty_arrived <= 0:
        return {"ok": False, "reason": "출금 수수료가 매수 수량보다 큼"}
    sell = vwap_sell(sell_book["bids"], qty_arrived)
    if not sell["avgPrice"]:
        return {"ok": False, "reason": "매도 호가 없음"}
    proceeds = sell["proceeds"] * (1 - sell_fee_pct / 100)
    gross = sell["avgPrice"] / buy["avgPrice"] - 1
    buy_fee_krw = size_krw * buy_fee_pct / 100
    withdraw_fee_krw = withdraw_fee * sell["avgPrice"]
    sell_fee_krw = sell["proceeds"] * sell_fee_pct / 100
    net = proceeds - size_krw
    return {
        "ok": True,
        "buyAvgKrw": buy["avgPrice"],
        "sellAvgKrw": sell["avgPrice"],
        "qtyBought": buy["qty"],
        "qtyArrived": qty_arrived,
        "grossPct": _pct(gross),
        "costs": {"buyFeeKrw": buy_fee_krw, "withdrawFeeKrw": withdraw_fee_krw, "sellFeeKrw": sell_fee_krw},
        "netKrw": net,
        "netPct": _pct(net / size_krw),
        "insufficientDepth": buy["insufficient"] or sell["insufficient"],
    }


def _to_krw(book: dict, rate: float) -> dict:
    return {side: [(price * rate, qty) for price, qty in book[side]] for side in ("asks", "bids")}


def _bithumb_wallet(symbol: str) -> dict[str, Any]:
    rows = _get_json(f"https://api.bithumb.com/public/assetsstatus/multichain/{symbol}").get("data") or []
    net = NETWORKS[symbol]["bithumbNet"]
    row = next((r for r in rows if r.get("net_type") == net), None)
    if not row:
        return {"deposit": "unknown", "withdraw": "unknown"}
    return {"deposit": "open" if row.get("deposit_status") == 1 else "closed",
            "withdraw": "open" if row.get("withdrawal_status") == 1 else "closed"}


def transfer_info(symbol: str) -> dict[str, Any]:
    net = NETWORKS[symbol]
    return {
        "network": net["network"],
        "blockSec": net["blockSec"],
        "confirmations": net["confirmations"],
        "estimatedMinutes": round(net["blockSec"] * net["confirmations"] / 60, 1),
        "withdrawFee": net["withdrawFee"],
    }


def _float_arg(name: str, default: float, low: float, high: float) -> float:
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return min(max(value, low), high)


@arb_bp.get("/<symbol>/matrix")
def matrix(symbol: str):
    symbol = symbol.upper()
    if symbol not in COINS:
        return jsonify({"error": "UNSUPPORTED_SYMBOL", "message": f"지원 코인: {', '.join(COINS)}"}), 404

    size_krw = _float_arg("sizeKrw", DEFAULT_SIZE_KRW, MIN_SIZE_KRW, MAX_SIZE_KRW)
    withdraw_fee = _float_arg("withdrawFee", NETWORKS[symbol]["withdrawFee"], 0, 1e9)
    fees = {code: _float_arg(f"fee_{code}", meta["takerFeePct"], 0, 5) for code, meta in EXCHANGES.items()}

    def load_books():
        return _run_sources({code: (lambda fn=fn: fn(symbol)) for code, fn in BOOK_FETCHERS.items()})

    books, cached_status = _cached(f"books:{symbol}", ORDERBOOK_TTL, load_books)
    status = dict(cached_status)  # 캐시된 상태를 요청별 메시지로 오염시키지 않는다.
    snap = _cached("snapshot", TICKER_TTL, _load_snapshot)
    usdt_krw = snap["fx"]["usdtKrw"]

    krw_books: dict[str, dict] = {}
    for code, book in books.items():
        if EXCHANGES[code]["quote"] == "USDT":
            if not usdt_krw:
                status[code] = {"status": "error", "message": "USDT 원화 환산값 없음"}
                continue
            book = _to_krw(book, usdt_krw)
        if book["asks"] and book["bids"]:
            krw_books[code] = book

    try:
        wallet = {"BITHUMB": _cached(f"wallet:{symbol}", 60, lambda: _bithumb_wallet(symbol))}
    except SourceError:
        wallet = {"BITHUMB": {"deposit": "unknown", "withdraw": "unknown"}}

    pairs = []
    for buy_code, buy_book in krw_books.items():
        for sell_code, sell_book in krw_books.items():
            if buy_code == sell_code:
                continue
            result = simulate_pair(buy_book, sell_book, size_krw, fees[buy_code], fees[sell_code], withdraw_fee)
            pairs.append({"buy": buy_code, "sell": sell_code, **result})

    viable = [p for p in pairs if p.get("ok")]
    best = max(viable, key=lambda p: p["netKrw"], default=None)
    return jsonify({
        "symbol": symbol,
        "sizeKrw": size_krw,
        "usdtKrw": usdt_krw,
        "fees": fees,
        "feeReferenceDate": FEE_REFERENCE_DATE,
        "books": {code: {"bestAskKrw": b["asks"][0][0], "bestBidKrw": b["bids"][0][0]} for code, b in krw_books.items()},
        "pairs": pairs,
        "best": {"buy": best["buy"], "sell": best["sell"], "netKrw": best["netKrw"], "netPct": best["netPct"]} if best else None,
        "transfer": transfer_info(symbol),
        "wallet": {code: wallet.get(code, {"deposit": "unknown", "withdraw": "unknown"}) for code in EXCHANGES},
        "sources": status,
        "fetchedAt": int(time.time() * 1000),
    })


# ── 프리미엄 추이 (DB 없이 캔들로 복원) ────────────────────────────────────

HISTORY_INTERVALS = {
    "1H": {"upbit": "minutes/60", "okx": "1H", "binance": "1h"},
    "1D": {"upbit": "days", "okx": "1Dutc", "binance": "1d"},
}
HISTORY_COUNT = 200


def _upbit_closes(market: str, unit: str) -> dict[int, float]:
    rows = _get_json(f"https://api.upbit.com/v1/candles/{unit}", {"market": market, "count": HISTORY_COUNT})
    out = {}
    for row in rows:
        ts = datetime.fromisoformat(row["candle_date_time_utc"]).replace(tzinfo=timezone.utc)
        out[int(ts.timestamp())] = float(row["trade_price"])
    return out


def _okx_closes(symbol: str, bar: str) -> dict[int, float]:
    rows = _get_json("https://www.okx.com/api/v5/market/candles", {"instId": f"{symbol}-USDT", "bar": bar, "limit": HISTORY_COUNT}).get("data") or []
    return {int(row[0]) // 1000: float(row[4]) for row in rows}


def _binance_closes(symbol: str, interval: str) -> dict[int, float]:
    rows = _get_json("https://api.binance.com/api/v3/klines", {"symbol": f"{symbol}USDT", "interval": interval, "limit": HISTORY_COUNT})
    return {int(row[0]) // 1000: float(row[4]) for row in rows}


def premium_series(krw: dict[int, float], usdt: dict[int, float], usdt_krw: dict[int, float]) -> list[dict[str, Any]]:
    points = []
    for ts in sorted(set(krw) & set(usdt) & set(usdt_krw)):
        points.append({
            "time": ts,
            "premiumPct": _pct(krw[ts] / (usdt[ts] * usdt_krw[ts]) - 1),
            "krw": krw[ts],
            "usdt": usdt[ts],
            "usdtKrw": usdt_krw[ts],
        })
    return points


def _load_history(symbol: str, interval: str) -> dict[str, Any]:
    spec = HISTORY_INTERVALS[interval]
    krw = _upbit_closes(f"KRW-{symbol}", spec["upbit"])
    usdt_krw = _upbit_closes("KRW-USDT", spec["upbit"])
    source, errors = None, {}
    for code, loader in (("OKX", lambda: _okx_closes(symbol, spec["okx"])), ("BINANCE", lambda: _binance_closes(symbol, spec["binance"]))):
        try:
            usdt = loader()
            source = code
            break
        except SourceError as exc:
            errors[code] = {"status": exc.status, "message": str(exc)}
    if not source:
        raise SourceError("error", "해외 거래소 캔들을 가져오지 못했습니다.")
    return {"symbol": symbol, "interval": interval, "domestic": "UPBIT", "global": source,
            "points": premium_series(krw, usdt, usdt_krw), "sources": errors}


@arb_bp.get("/<symbol>/history")
def history(symbol: str):
    symbol = symbol.upper()
    interval = request.args.get("interval", "1H").upper()
    if symbol not in COINS:
        return jsonify({"error": "UNSUPPORTED_SYMBOL", "message": f"지원 코인: {', '.join(COINS)}"}), 404
    if interval not in HISTORY_INTERVALS:
        return jsonify({"error": "UNSUPPORTED_INTERVAL", "message": "interval은 1H 또는 1D입니다."}), 400
    try:
        return jsonify(_cached(f"history:{symbol}:{interval}", HISTORY_TTL, lambda: _load_history(symbol, interval)))
    except SourceError as exc:
        return jsonify({"error": "SOURCE_UNAVAILABLE", "message": str(exc)}), 502


# ── 전송·수수료 참고표 ─────────────────────────────────────────────────────

def _mempool_fees() -> dict[str, Any]:
    body = _get_json("https://mempool.space/api/v1/fees/recommended")
    return {key: body.get(key) for key in ("fastestFee", "halfHourFee", "hourFee", "economyFee")}


@arb_bp.get("/network")
def network():
    try:
        mempool = _cached("mempool", 60, _mempool_fees)
        mempool_status = {"status": "ok"}
    except SourceError as exc:
        mempool, mempool_status = None, {"status": exc.status, "message": str(exc)}

    btc_krw = None
    snap = _cached("snapshot", TICKER_TTL, _load_snapshot)
    btc = next((c for c in snap["coins"] if c["symbol"] == "BTC"), None)
    if btc and btc["domesticRef"]:
        btc_krw = btc["prices"][btc["domesticRef"]]["krw"]

    onchain = None
    if mempool and mempool.get("fastestFee") is not None:
        sats = mempool["fastestFee"] * BTC_TX_VBYTES
        onchain = {"satPerVb": mempool["fastestFee"], "vbytes": BTC_TX_VBYTES, "sats": sats,
                   "krw": round(sats / 1e8 * btc_krw) if btc_krw else None}

    return jsonify({
        "coins": [{"symbol": s, **transfer_info(s)} for s in COINS],
        "exchanges": [{"code": code, **meta} for code, meta in EXCHANGES.items()],
        "feeReferenceDate": FEE_REFERENCE_DATE,
        "btcMempool": mempool,
        "btcOnchainEstimate": onchain,
        "sources": {"MEMPOOL": mempool_status},
    })
