"""Two orders from the same member must not act on a stale position.

MariaDB's default isolation is REPEATABLE READ: a plain read fixes the
transaction's snapshot, and later plain reads keep seeing it even after
another transaction commits. The order routes read the member before
placing the order, so the position must be read with a locking read.

The interleaving is driven step by step with two sessions in one thread, so
the test is deterministic:

1. Session A reads the member (A's snapshot starts here).
2. Session B places an order and commits.
3. Session A places its order.
"""

import uuid
from unittest import mock

import pytest
from sqlalchemy.orm import Session

import bootstrap
import db
import member_delete
import stock_market
import stock_trading
from models import Member, StockOrder, StockPosition

pytestmark = pytest.mark.integration

SYMBOL = "005930"
PRICE = 1_000
START_CASH = 1_000_000


def _quote(symbol):
    return {
        "symbol": symbol,
        "name": "삼성전자",
        "market": "KOSPI",
        "price": PRICE,
        "prevClose": PRICE,
        "change": 0,
        "changeRate": 0.0,
        "volume": 1,
    }


@pytest.fixture(autouse=True)
def fixed_price():
    # Both the old and new price paths go through get_quote_cached.
    with mock.patch.object(stock_market, "get_quote_cached", side_effect=_quote):
        yield


@pytest.fixture
def member_id():
    bootstrap.create_tables()
    email = f"race-{uuid.uuid4().hex[:12]}@example.test"
    with Session(db.engine) as s, s.begin():
        member = Member(username="race", email=email, password="x", asset=START_CASH)
        s.add(member)
        s.flush()
        new_id = member.member_id
    yield new_id
    member_delete.delete_member(new_id)


def _seed_position(member_id, quantity):
    with Session(db.engine) as s, s.begin():
        s.add(StockPosition(member_id=member_id, symbol=SYMBOL, quantity=quantity, avg_price=PRICE))
        s.get(Member, member_id).asset -= quantity * PRICE


def _state(member_id):
    with Session(db.engine) as s:
        cash = s.get(Member, member_id).asset
        pos = s.query(StockPosition).filter_by(member_id=member_id, symbol=SYMBOL).one_or_none()
        orders = s.query(StockOrder).filter_by(member_id=member_id).count()
        return cash, (pos.quantity if pos else 0), orders


def _order(session, member, side, quantity):
    result = stock_trading.execute_order(session, member, SYMBOL, side, quantity)
    session.commit()
    return result


def test_second_sell_sees_the_first_sells_shares_are_gone(member_id):
    _seed_position(member_id, 10)
    a, b = Session(db.engine), Session(db.engine)
    try:
        member_a = a.get(Member, member_id)  # A's snapshot: 10 shares
        _order(b, b.get(Member, member_id), stock_trading.SELL, 6)

        with pytest.raises(ValueError, match="매도 가능한 수량"):
            _order(a, member_a, stock_trading.SELL, 6)
        a.rollback()
    finally:
        a.close()
        b.close()

    cash, quantity, orders = _state(member_id)
    assert quantity == 4
    assert cash == START_CASH - 10 * PRICE + 6 * PRICE  # credited once, not twice
    assert orders == 1


def test_second_buy_adds_to_the_position_the_first_buy_created(member_id):
    a, b = Session(db.engine), Session(db.engine)
    try:
        member_a = a.get(Member, member_id)  # A's snapshot: no position
        _order(b, b.get(Member, member_id), stock_trading.BUY, 3)
        _order(a, member_a, stock_trading.BUY, 2)
    finally:
        a.close()
        b.close()

    cash, quantity, orders = _state(member_id)
    assert quantity == 5
    assert cash == START_CASH - 5 * PRICE
    assert orders == 2


def test_second_buy_is_charged_against_the_cash_left_by_the_first(member_id):
    a, b = Session(db.engine), Session(db.engine)
    all_cash = START_CASH // PRICE
    try:
        member_a = a.get(Member, member_id)
        _order(b, b.get(Member, member_id), stock_trading.BUY, all_cash)
        with pytest.raises(ValueError, match="보유 현금"):
            _order(a, member_a, stock_trading.BUY, 1)
        a.rollback()
    finally:
        a.close()
        b.close()

    cash, quantity, orders = _state(member_id)
    assert (cash, quantity, orders) == (0, all_cash, 1)
