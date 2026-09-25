"""Upbit daily candle adapter: parsing, paging, rate-limit handling (no network)."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from unittest import mock

import pytest
import requests

from marketdata import quality
from marketdata.sources import upbit

FIXTURE = json.loads((Path(__file__).parents[1] / "fixtures" / "upbit_candles_days.json").read_text())["items"]


def _response(status=200, items=None, remaining="group=candle; min=1800; sec=9"):
    response = mock.Mock(status_code=status, headers={"Remaining-Req": remaining}, text="")
    response.json.return_value = items if items is not None else []
    response.raise_for_status.side_effect = None if status < 400 else requests.HTTPError(str(status))
    return response


def _source(*responses):
    session = mock.Mock()
    session.get.side_effect = list(responses)
    sleeps = []
    return upbit.UpbitSource(session=session, sleep=sleeps.append), session, sleeps


def test_parse_candles_maps_documented_fields_oldest_first():
    bars = upbit.parse_candles("KRW-BTC", FIXTURE)
    assert [bar.ts.date() for bar in bars] == sorted(bar.ts.date() for bar in bars)
    newest = bars[-1]
    assert newest.ts == datetime(2026, 1, 10, tzinfo=UTC)
    assert (newest.open, newest.high, newest.low, newest.close, newest.volume) == (
        100_000_000.0,
        102_000_000.0,
        98_500_000.0,
        100_500_000.0,
        1234.5,
    )
    assert newest.source == "upbit"
    assert not quality.has_errors(quality.check(bars))


def test_remaining_req_header_parsing():
    assert upbit.remaining_per_second("group=candle; min=1800; sec=29") == 29
    assert upbit.remaining_per_second("group=candle; min=1800; sec=0") == 0
    assert upbit.remaining_per_second(None) is None


def test_fetch_pages_backwards_until_start_and_trims_the_range():
    newer, older = FIXTURE[:5], FIXTURE[5:]
    source, session, _ = _source(_response(items=newer), _response(items=older), _response(items=[]))
    bars = source.fetch_daily("KRW-BTC", date(2026, 1, 3), date(2026, 1, 9))
    assert [bar.ts.day for bar in bars] == [3, 4, 5, 6, 7, 8, 9]
    first_params = session.get.call_args_list[0].kwargs["params"]
    assert first_params == {"market": "KRW-BTC", "to": "2026-01-10T00:00:00Z", "count": 200}
    assert session.get.call_args_list[1].kwargs["params"]["to"] == "2026-01-06T00:00:00Z"
    assert "Origin" not in session.get.call_args_list[0].kwargs["headers"]


def test_429_backs_off_and_retries():
    source, session, sleeps = _source(_response(status=429), _response(items=FIXTURE[:1]), _response(items=[]))
    bars = source.fetch_daily("KRW-BTC", date(2026, 1, 10), date(2026, 1, 10))
    assert len(bars) == 1
    assert 1 in sleeps  # 2**0 seconds after the first 429


def test_418_stops_immediately():
    source, session, _ = _source(_response(status=418))
    with pytest.raises(upbit.UpbitBlocked):
        source.fetch_daily("KRW-BTC", date(2026, 1, 1), date(2026, 1, 10))
    assert session.get.call_count == 1


def test_exhausted_second_quota_waits_a_second():
    source, _, sleeps = _source(
        _response(items=FIXTURE[:1], remaining="group=candle; min=1800; sec=0"), _response(items=[])
    )
    source.fetch_daily("KRW-BTC", date(2026, 1, 10), date(2026, 1, 10))
    assert 1.0 in sleeps


@pytest.mark.network
def test_live_upbit_daily_candles_match_the_documented_shape():
    bars = upbit.UpbitSource().fetch_daily("KRW-BTC", date(2026, 1, 1), date(2026, 1, 7))
    assert len(bars) == 7
    assert not quality.has_errors(quality.check(bars))
