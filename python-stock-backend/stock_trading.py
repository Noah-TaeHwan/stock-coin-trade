import time

from models import StockOrder, StockPosition
from stock_market import current_price, get_chart_cached, get_stock_info, order_quote
from volatility import annualized_volatility

INITIAL_CASH = 100_000_000  # matches the seed deposit granted at registration (members.py)

BUY = "BUY"
SELL = "SELL"


def _get_position(db, member_id: int, symbol: str) -> StockPosition | None:
    # 잠금 읽기로 최신 커밋 값을 읽는다. REPEATABLE READ에서 일반 읽기는 트랜잭션의
    # 첫 읽기 시점 스냅샷을 보므로, 먼저 커밋된 다른 주문의 결과를 놓칠 수 있다.
    return (
        db.query(StockPosition)
        .filter(StockPosition.member_id == member_id, StockPosition.symbol == symbol)
        .with_for_update()
        .populate_existing()
        .first()
    )


def _stock_volatility(symbol: str) -> float | None:
    """최근 1개월 일봉 종가로 계산한 연환산(252거래일) 변동성(%)."""
    try:
        ohlcv, _ = get_chart_cached(symbol, "1m")
        return annualized_volatility([candle["c"] for candle in ohlcv], trading_periods=252)
    except Exception:
        return None


def get_positions(db, member_id: int, include_volatility: bool = False) -> list[dict]:
    rows = db.query(StockPosition).filter(StockPosition.member_id == member_id).all()
    result = []
    for pos in rows:
        price = current_price(pos.symbol)
        eval_amount = pos.quantity * price
        pnl = eval_amount - (pos.quantity * pos.avg_price)
        info = get_stock_info(pos.symbol) or {}
        name = info.get("name", pos.symbol)
        sector = info.get("sector", "기타")
        item = {
            "symbol":       pos.symbol,
            "name":         name,
            "sector":       sector,
            "quantity":     pos.quantity,
            "avgPrice":     pos.avg_price,
            "currentPrice": price,
            "evalAmount":   eval_amount,
            "pnl":          pnl,
        }
        if include_volatility:
            item["volatility"] = _stock_volatility(pos.symbol)
        result.append(item)
    return result


def get_account_snapshot(db, member) -> dict:
    from alternatives import position_value
    positions = get_positions(db, member.member_id)
    total_pos = sum(p["evalAmount"] for p in positions) + position_value(db, member.member_id)
    total_asset = member.asset + total_pos
    pnl_rate = round(((total_asset - INITIAL_CASH) / INITIAL_CASH * 100) if INITIAL_CASH else 0, 4)
    return {"cash": member.asset, "totalAsset": total_asset, "totalPnlRate": pnl_rate}


def get_order_history(db, member_id: int, limit: int = 50) -> list[dict]:
    rows = (
        db.query(StockOrder)
        .filter(StockOrder.member_id == member_id)
        .order_by(StockOrder.created_at.desc(), StockOrder.stock_order_id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "ts":       int(o.created_at.timestamp() * 1000) if o.created_at else int(time.time() * 1000),
            "type":     o.order_type,
            "symbol":   o.symbol,
            "name":     o.name,
            "quantity": o.quantity,
            "price":    o.price,
            "amount":   o.amount,
            "source":   o.source,
        }
        for o in rows
    ]


def allows_simulated_price(profile: str) -> bool:
    """공개(public) 프로필에서는 시뮬레이션 가격으로 체결하지 않는다."""
    return profile != "public"


def execute_order(
    db,
    member,
    symbol: str,
    side: str,
    quantity: int,
    source: str = "WEB",
    allow_simulated_price: bool = True,
) -> dict:
    """Execute a market BUY/SELL for `member` against their shared cash balance
    (member.asset). Raises ValueError with a user-facing message on failure.

    allow_simulated_price=False refuses to fill at the offline simulated price
    that stock_market falls back to when every quote source fails."""
    symbol = (symbol or "").upper()
    side = (side or "").upper()
    if side not in (BUY, SELL):
        raise ValueError("side는 BUY 또는 SELL이어야 합니다.")
    info = get_stock_info(symbol)
    if not info:
        raise ValueError(f"지원하지 않는 KRX 종목입니다: {symbol}")
    if not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("quantity는 1 이상의 정수여야 합니다.")

    # 시세 조회는 네트워크를 타므로 행 잠금을 잡기 전에 한다.
    try:
        price, simulated = order_quote(symbol)
    except Exception as exc:
        raise ValueError("실시간 시세를 확인할 수 없어 주문할 수 없습니다. 잠시 후 다시 시도해주세요.") from exc
    if simulated and not allow_simulated_price:
        raise ValueError("실시간 시세를 확인할 수 없어 주문할 수 없습니다. 잠시 후 다시 시도해주세요.")
    amount = price * quantity

    # 같은 회원의 주문은 회원 행 잠금으로 차례로 처리한다. 잔액과 포지션은 모두
    # 잠금 읽기로 가져와 먼저 커밋된 주문의 결과를 반영한다.
    db.refresh(member, with_for_update=True)
    position = _get_position(db, member.member_id, symbol)

    if side == BUY:
        if amount > member.asset:
            raise ValueError("보유 현금이 부족합니다.")
        member.asset -= amount
        if position is None:
            position = StockPosition(
                member_id=member.member_id,
                symbol=symbol,
                quantity=quantity,
                avg_price=price,
            )
            db.add(position)
        else:
            total_qty = position.quantity + quantity
            total_amount = position.avg_price * position.quantity + amount
            position.quantity = total_qty
            position.avg_price = int(total_amount / total_qty)
    else:
        if position is None or position.quantity < quantity:
            raise ValueError("매도 가능한 수량이 부족합니다.")
        position.quantity -= quantity
        member.asset += amount
        if position.quantity == 0:
            db.delete(position)

    db.add(StockOrder(
        member_id=member.member_id,
        symbol=symbol,
        name=info["name"],
        order_type=side,
        quantity=quantity,
        price=price,
        amount=amount,
        source=source,
    ))

    return {
        "status": "ok",
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "price": price,
        "amount": amount,
        "simulated": simulated,
    }
