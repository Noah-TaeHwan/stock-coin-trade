import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask

import alpaca_test
from alpaca_test_api import alpaca_test_bp


class AlpacaLabTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(SECRET_KEY="test-secret", TESTING=True)
        app.register_blueprint(alpaca_test_bp)
        self.client = app.test_client()

    def login(self):
        with self.client.session_transaction() as sess:
            sess["member_id"] = 7

    def test_status_requires_login(self):
        response = self.client.get("/api/alpaca-test/status")
        self.assertEqual(response.status_code, 401)

    # The status endpoint must report readiness without echoing credential
    # values. These tests call the real get_alpaca_configuration_status();
    # the earlier version mocked it and then asserted on the mock's output,
    # so it could not fail.
    def _status_with(self, env, key_file_text=None):
        with tempfile.TemporaryDirectory() as key_dir:
            key_dir = Path(key_dir)
            if key_file_text is not None:
                key_path = key_dir / "al.key"
                key_path.write_text(key_file_text, encoding="utf-8")
                key_path.chmod(0o600)
            with patch.dict(os.environ, env, clear=False), \
                    patch("alpaca_test.SECRETS_DIR", key_dir), patch("alpaca_test.ROOT_DIR", key_dir), \
                    patch("broker_test.SECRETS_DIR", key_dir), patch("broker_test.ROOT_DIR", key_dir):
                self.login()
                return self.client.get("/api/alpaca-test/status")

    def test_status_from_environment_does_not_echo_credentials(self):
        response = self._status_with({"ALPACA_API_KEY": "PK-ENV-7f3a91c2", "ALPACA_SECRET_KEY": "SK-ENV-9c2d44e1"})
        self.assertEqual(response.status_code, 200)
        status = response.get_json()["status"]
        self.assertTrue(status["configured"])
        self.assertEqual(status["source"], "environment")
        body = response.get_data(as_text=True)
        self.assertNotIn("PK-ENV-7f3a91c2", body)
        self.assertNotIn("SK-ENV-9c2d44e1", body)

    def test_status_from_key_file_does_not_echo_credentials(self):
        response = self._status_with(
            {"ALPACA_API_KEY": "", "ALPACA_SECRET_KEY": ""},
            key_file_text="Key=PK-FILE-51b0d7aa\nSecret=SK-FILE-0e6c93f4\n",
        )
        self.assertEqual(response.status_code, 200)
        status = response.get_json()["status"]
        self.assertTrue(status["configured"])
        self.assertEqual(status["source"], "al.key")
        self.assertEqual(status["keyFile"]["permission"], "600")
        body = response.get_data(as_text=True)
        self.assertNotIn("PK-FILE-51b0d7aa", body)
        self.assertNotIn("SK-FILE-0e6c93f4", body)

    @patch("alpaca_test._audit_alpaca_call")
    @patch("alpaca_test._headers", return_value={})
    @patch("alpaca_test.requests.get")
    def test_read_call_is_audited_without_account_identifier(self, request_call, _headers, audit):
        response = Mock(status_code=200, ok=True)
        response.json.return_value = {"id": "account-secret-id", "account_number": "123456", "status": "ACTIVE"}
        request_call.return_value = response
        result = alpaca_test._get(f"{alpaca_test.ALPACA_PAPER_BASE}/account")
        self.assertEqual(result["status"], "ACTIVE")
        logged = str(audit.call_args.kwargs["response_body"])
        self.assertNotIn("account-secret-id", logged)
        self.assertNotIn("123456", logged)
        self.assertTrue(audit.call_args.kwargs["success"])


if __name__ == "__main__":
    unittest.main()
