import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from flask import Flask

from kis_practice import PracticeOrderRejected, kis_practice_bp
from models import KisPracticeAccount, KisPracticeOrder, KisPracticePosition


class KisPracticeApiTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(SECRET_KEY="test-secret", TESTING=True)
        app.register_blueprint(kis_practice_bp)
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess["member_id"] = 7
            sess["csrf_token"] = "csrf-test-token"

    @staticmethod
    @contextmanager
    def _fake_session():
        yield Mock()

    def test_practice_ledger_uses_dedicated_tables(self):
        self.assertEqual(KisPracticeAccount.__tablename__, "kis_practice_account")
        self.assertEqual(KisPracticePosition.__tablename__, "kis_practice_position")
        self.assertEqual(KisPracticeOrder.__tablename__, "kis_practice_order")

    def test_order_requires_csrf(self):
        response = self.client.post(
            "/api/kis-practice/orders",
            json={"symbol": "005930", "side": "BUY", "quantity": 1},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "CSRF_INVALID")

    @patch("kis_practice._execute_order")
    @patch("kis_practice.session_scope", side_effect=_fake_session)
    def test_insufficient_balance_returns_http_409(self, _session_scope, execute_order):
        execute_order.side_effect = PracticeOrderRejected(
            "INSUFFICIENT_BALANCE",
            "주문 가능 금액(예수금)이 부족합니다.",
            status_code=409,
            details={"availableCash": 10_000, "requiredAmount": 70_000, "shortageAmount": 60_000},
        )
        response = self.client.post(
            "/api/kis-practice/orders",
            json={"symbol": "005930", "side": "BUY", "quantity": 1},
            headers={"X-CSRF-Token": "csrf-test-token"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json(), {
            "error": "INSUFFICIENT_BALANCE",
            "message": "주문 가능 금액(예수금)이 부족합니다.",
            "availableCash": 10_000,
            "requiredAmount": 70_000,
            "shortageAmount": 60_000,
        })


if __name__ == "__main__":
    unittest.main()
