"""코인 매도 수량은 보유 수량과 같은 소수 8자리 기준으로 비교한다."""

from types import SimpleNamespace
from unittest import mock

import pytest

import crypto

HELD = 0.12345679  # 매수 시 round(..., 8)로 저장되는 보유 수량


def _db(held):
    """execute_crypto_sell이 쓰는 두 조회(마켓, 잠금 보유)만 흉내 낸다."""
    db = mock.MagicMock()
    market = SimpleNamespace(upbit_market_id=1, korean_name="비트코인")
    db.query.return_value.filter.return_value.first.return_value = market
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = held
    return db


@pytest.fixture(autouse=True)
def fixed_price():
    with mock.patch.object(crypto, "_upbit_trade_price", return_value=100_000_000):
        yield


def test_full_sell_with_more_than_eight_decimals_sells_everything():
    held = SimpleNamespace(buy_crypto_count=HELD, buy_total_krw=12_345_679)
    member = SimpleNamespace(member_id=7, asset=0)
    db = _db(held)

    crypto.execute_crypto_sell(db, member, "KRW-BTC", 0.123456794)

    db.delete.assert_called_once_with(held)
    order = db.add.call_args.args[0]
    assert order.quantity == HELD


def test_sell_that_rounds_to_zero_is_rejected():
    held = SimpleNamespace(buy_crypto_count=HELD, buy_total_krw=12_345_679)
    with pytest.raises(ValueError):
        crypto.execute_crypto_sell(_db(held), SimpleNamespace(member_id=7, asset=0), "KRW-BTC", 0.000000001)
