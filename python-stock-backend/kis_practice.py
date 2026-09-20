"""KIS-style stock practice ledger, isolated from the repository's mock portfolio."""

import time

from flask import Blueprint, jsonify, request, session

from db import engine, session_scope
from models import Base, KisPracticeAccount, KisPracticeOrder, KisPracticePosition
from security import csrf_is_valid
from stock_market import current_price, get_stock_info


INITIAL_CASH = 100_000_000
BUY = "BUY"
SELL = "SELL"

kis_practice_bp = Blueprint("kis_practice", __name__, url_prefix="/api/kis-practice")


class PracticeOrderRejected(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.details = details or {}


def ensure_kis_practice_tables() -> None:
    """Create only the isolated practice ledger tables when they do not exist."""
    Base.metadata.create_all(
        bind=engine,
        tables=[KisPracticeAccount.__table__, KisPracticePosition.__table__, KisPracticeOrder.__table__],
        checkfirst=True,
    )


@kis_practice_bp.before_request
def require_login():
    if not session.get("member_id"):
        return jsonify({"error": "UNAUTHORIZED", "message": "로그인이 필요합니다."}), 401


def _account(db, member_id: int, *, lock: bool = False) -> KisPracticeAccount:
    query = db.query(KisPracticeAccount).filter(KisPracticeAccount.member_id == member_id)
    if lock:
        query = query.with_for_update()
    account = query.first()
    if account is None:
        account = KisPracticeAccount(member_id=member_id, cash=INITIAL_CASH)
        db.add(account)
        db.flush()
    return account


def _position(db, member_id: int, symbol: str) -> KisPracticePosition | None:
    return db.query(KisPracticePosition).filter_by(member_id=member_id, symbol=symbol).first()


def _serialize_positions(db, member_id: int) -> list[dict]:
    rows = db.query(KisPracticePosition).filter_by(member_id=member_id).all()
    result = []
    for row in rows:
        try:
            price = int(current_price(row.symbol))
        except Exception:
            price = int(row.avg_price)
        info = get_stock_info(row.symbol) or {}
        result.append({
            "symbol": row.symbol,
            "name": info.get("name", row.symbol),
            "quantity": int(row.quantity),
            "avgPrice": int(row.avg_price),
            "currentPrice": price,
            "evalAmount": int(row.quantity * price),
            "pnl": int(row.quantity * (price - row.avg_price)),
        })
    return result


def _execute_order(db, member_id: int, symbol: str, side: str, quantity: int) -> dict:
    symbol = symbol.upper().strip()
    side = side.upper().strip()
    if side not in (BUY, SELL):
        raise PracticeOrderRejected("INVALID_SIDE", "매수 또는 매도를 선택해주세요.")
    if not isinstance(quantity, int) or quantity < 1:
        raise PracticeOrderRejected("INVALID_QUANTITY", "주문수량은 1주 이상의 정수여야 합니다.")
    info = get_stock_info(symbol)
    if not info:
        raise PracticeOrderRejected("INVALID_SYMBOL", "지원하지 않는 KRX 종목입니다.")
    try:
        price = int(current_price(symbol))
    except Exception as exc:
        raise PracticeOrderRejected("QUOTE_UNAVAILABLE", "현재 시세를 확인할 수 없습니다.", status_code=503) from exc
    if price <= 0:
        raise PracticeOrderRejected("QUOTE_UNAVAILABLE", "유효한 현재가를 확인할 수 없습니다.", status_code=503)

    account = _account(db, member_id, lock=True)
    position = _position(db, member_id, symbol)
    amount = price * quantity

    if side == BUY:
        if amount > account.cash:
            raise PracticeOrderRejected(
                "INSUFFICIENT_BALANCE",
                "주문 가능 금액(예수금)이 부족합니다.",
                status_code=409,
                details={
                    "availableCash": int(account.cash),
                    "requiredAmount": amount,
                    "shortageAmount": amount - int(account.cash),
                },
            )
        account.cash -= amount
        if position is None:
            db.add(KisPracticePosition(member_id=member_id, symbol=symbol, quantity=quantity, avg_price=price))
        else:
            new_quantity = position.quantity + quantity
            position.avg_price = int((position.avg_price * position.quantity + amount) / new_quantity)
            position.quantity = new_quantity
    else:
        available = int(position.quantity if position else 0)
        if quantity > available:
            raise PracticeOrderRejected(
                "INSUFFICIENT_POSITION",
                "매도 가능한 보유수량이 부족합니다.",
                status_code=409,
                details={"availableQuantity": available, "requestedQuantity": quantity},
            )
        position.quantity -= quantity
        account.cash += amount
        if position.quantity == 0:
            db.delete(position)

    db.add(KisPracticeOrder(
        member_id=member_id, symbol=symbol, name=info["name"], order_type=side,
        quantity=quantity, price=price, amount=amount,
    ))
    return {"status": "ok", "symbol": symbol, "side": side, "quantity": quantity, "price": price, "amount": amount}


@kis_practice_bp.get("/account")
def account():
    member_id = session["member_id"]
    with session_scope() as db:
        practice_account = _account(db, member_id)
        positions = _serialize_positions(db, member_id)
        total_asset = int(practice_account.cash) + sum(row["evalAmount"] for row in positions)
        return jsonify({
            "cash": int(practice_account.cash),
            "totalAsset": total_asset,
            "totalPnlRate": round((total_asset - INITIAL_CASH) / INITIAL_CASH * 100, 4),
            "ledger": "KIS_PRACTICE",
        })


@kis_practice_bp.get("/positions")
def positions():
    with session_scope() as db:
        return jsonify({"positions": _serialize_positions(db, session["member_id"]), "ledger": "KIS_PRACTICE"})


@kis_practice_bp.get("/orders/history")
def history():
    try:
        limit = max(1, min(int(request.args.get("limit", 20)), 200))
    except (TypeError, ValueError):
        limit = 20
    with session_scope() as db:
        rows = (db.query(KisPracticeOrder).filter_by(member_id=session["member_id"])
                .order_by(KisPracticeOrder.created_at.desc(), KisPracticeOrder.kis_practice_order_id.desc())
                .limit(limit).all())
        return jsonify({"history": [{
            "ts": int(row.created_at.timestamp() * 1000) if row.created_at else int(time.time() * 1000),
            "type": row.order_type, "symbol": row.symbol, "name": row.name,
            "quantity": int(row.quantity), "price": int(row.price), "amount": int(row.amount),
        } for row in rows], "ledger": "KIS_PRACTICE"})


@kis_practice_bp.post("/orders")
def order():
    if not csrf_is_valid():
        return jsonify({"error": "CSRF_INVALID", "message": "요청 검증에 실패했습니다. 화면을 새로고침해주세요."}), 403
    body = request.get_json(silent=True) or {}
    try:
        quantity = int(body.get("quantity", 0))
    except (TypeError, ValueError):
        quantity = 0
    with session_scope() as db:
        try:
            result = _execute_order(
                db, session["member_id"], str(body.get("symbol", "")), str(body.get("side", "")), quantity,
            )
        except PracticeOrderRejected as exc:
            return jsonify({"error": exc.code, "message": str(exc), **exc.details}), exc.status_code
        return jsonify(result)
