"""F2 백테스트 영수증 주행: 같은 입력을 두 번 실행하면 같은 receiptId, 조회로 다시 읽힌다.

사용법: python3 scripts/verify/f2_backtest.py (먼저 scripts/verify/stack.sh up·doctor)
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

REQUEST = {"symbol": "005930", "strategy": "ma2050", "feeRate": 0.00015, "slippage": 0.0005, "fast": 20, "slow": 50}


def steps(client: common.Client, rec: common.Recorder) -> None:
    """F2 단계를 실행하고 기대값과 다르면 AssertionError를 낸다."""
    status, first = client.call("POST", "/api/quant/backtests", REQUEST)
    rec.add("backtest-1", REQUEST, status, {"receiptId": first.get("receiptId") if isinstance(first, dict) else first})
    if status == 404:
        raise ConnectionError(f"시세 데이터 부족: {first}")
    assert status in (200, 201), f"첫 실행 기대 200/201, 실제 {status}/{first}"
    receipt = first.get("receiptId", "")
    assert re.fullmatch(r"[0-9a-f]{64}", receipt), f"receiptId 형식 오류: {receipt!r}"

    status, second = client.call("POST", "/api/quant/backtests", REQUEST)
    rec.add("backtest-2", REQUEST, status, {"receiptId": second.get("receiptId")})
    assert status == 200 and second.get("receiptId") == receipt, (
        f"같은 입력 기대 200/같은 영수증, 실제 {status}/{second.get('receiptId')}")

    status, stored = client.call("GET", f"/api/quant/backtests/{receipt}")
    rec.add("stored", {"receiptId": receipt}, status,
            {"receiptId": stored.get("receiptId"), "hasMetrics": "metrics" in stored})
    assert status == 200 and stored.get("receiptId") == receipt and "metrics" in stored, f"조회 실패 {status}/{stored}"


if __name__ == "__main__":
    sys.exit(common.run("F2", steps))
