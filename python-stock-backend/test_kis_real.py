import unittest
from unittest.mock import patch

from flask import Flask

from kis_real import kis_real_bp


class KisRealApiTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(SECRET_KEY="test-secret", TESTING=True)
        app.register_blueprint(kis_real_bp)
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess["member_id"] = 7
            sess["csrf_token"] = "csrf-test-token"

    @patch.dict("os.environ", {}, clear=True)
    def test_status_requires_separate_real_configuration(self):
        response = self.client.get("/api/kis-real/status")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertFalse(body["ready"])
        self.assertFalse(body["configured"]["appKey"])
        self.assertEqual(body["environment"], "KIS 실전투자")

    def test_balance_requires_csrf(self):
        response = self.client.post("/api/kis-real/balance", json={})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "CSRF_INVALID")

    @patch("kis_real.requests.post")
    @patch.dict("os.environ", {}, clear=True)
    def test_missing_real_configuration_never_calls_kis(self, token_request):
        response = self.client.post(
            "/api/kis-real/balance", json={}, headers={"X-CSRF-Token": "csrf-test-token"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "REAL_CONFIG_REQUIRED")
        token_request.assert_not_called()

    @patch("kis_real.get_real_balance")
    def test_authorized_balance_response_is_read_only(self, get_balance):
        get_balance.return_value = {
            "cashBalance": "10000", "totalEvalAmount": "12000", "totalProfitLoss": "2000",
            "holdingsCount": 0, "holdings": [], "environment": "KIS 실전투자", "readOnly": True,
        }
        response = self.client.post(
            "/api/kis-real/balance", json={}, headers={"X-CSRF-Token": "csrf-test-token"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["balance"]["readOnly"])
        get_balance.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
