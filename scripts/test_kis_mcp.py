"""Check that the Trading MCP accepts only explicit paper credentials."""

import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch


TRADE = runpy.run_path(str(Path(__file__).with_name("kis_mcp.py")))["trade_environment"]


class TradingCredentialsTest(unittest.TestCase):
    def environment(self, variables: dict[str, str], dotenv: dict[str, str]) -> dict[str, str]:
        def read_values(path: Path) -> dict[str, str]:
            self.assertEqual(path.name, ".env")  # kis.key must never be read.
            return dotenv

        with patch.dict(os.environ, variables, clear=True), patch.dict(TRADE.__globals__, {"read_values": read_values}), patch.object(Path, "mkdir"), patch.object(Path, "chmod"):
            return TRADE()

    def test_paper_values_from_environment_or_dotenv(self) -> None:
        paper = {"KIS_PAPER_APP_KEY": "dummy-key", "KIS_PAPER_APP_SECRET": "dummy-secret", "KIS_PAPER_ACCOUNT_NO": "12345678-01"}
        for variables, dotenv in ((paper | {"KIS_FAKE_SECRET": "dummy", "SAFE": "kept"}, {}), ({}, paper)):
            with self.subTest(source="environment" if variables else "dotenv"):
                result = self.environment(variables, dotenv)
                self.assertEqual(result["KIS_PAPER_APP_KEY"], "dummy-key")
                self.assertEqual(result["KIS_PAPER_APP_SECRET"], "dummy-secret")
                self.assertEqual(result["KIS_PAPER_STOCK"], "12345678")
                self.assertNotIn("KIS_FAKE_SECRET", result)
                self.assertEqual(result.get("SAFE"), variables.get("SAFE"))

    def test_legacy_only_rejected(self) -> None:
        legacy = {"KIS_APP_KEY": "dummy-key", "KIS_APP_SECRET": "dummy-secret", "KIS_ACCOUNT_NO": "12345678-01"}
        for variables, dotenv in ((legacy, {}), ({}, legacy)):
            with self.subTest(source="environment" if variables else "dotenv"):
                with self.assertRaisesRegex(ValueError, "KIS_PAPER_APP_KEY"):
                    self.environment(variables, dotenv)


if __name__ == "__main__":
    unittest.main()
