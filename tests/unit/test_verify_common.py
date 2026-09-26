"""검증 공용 모듈(scripts/verify/common.py)의 비밀 가림·이메일 생성·증거 기록을 확인한다."""

import importlib.util
import json
import re
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "verify_common", Path(__file__).resolve().parents[2] / "scripts" / "verify" / "common.py"
)
common = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(common)


def test_redact_masks_secret_keys_at_any_depth():
    body = {"csrfToken": "abc", "profile": "local", "nested": [{"password": "p", "username": "u"}], "Set-Cookie": "s=1"}
    assert common.redact(body) == {
        "csrfToken": "***", "profile": "local", "nested": [{"password": "***", "username": "u"}], "Set-Cookie": "***",
    }


def test_redact_leaves_non_dict_values_alone():
    assert common.redact("plain") == "plain"
    assert common.redact([1, 2]) == [1, 2]


def test_unique_email_is_safe_and_distinct():
    first, second = common.unique_email(), common.unique_email()
    assert first != second
    assert re.fullmatch(r"verify-\d+-[0-9a-f]{6}@example\.test", first)


def test_recorder_writes_redacted_transcript(tmp_path):
    rec = common.Recorder("F9", root=tmp_path)
    rec.add("login", {"email": "a@example.test", "password": "secret-pw"}, 200, {"username": "u", "csrfToken": "t"})
    path = rec.finish("PASS")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["verdict"] == "PASS"
    assert data["steps"][0]["request"]["password"] == "***"
    assert data["steps"][0]["body"]["csrfToken"] == "***"
    assert "secret-pw" not in path.read_text(encoding="utf-8")
    assert path.parent.name.endswith("-F9")
