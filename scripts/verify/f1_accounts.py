"""F1 회원 주행: 가입 → /me → 로그아웃(복사한 쿠키도 거부) → /me → 로그인 → /me → 모든 기기 로그아웃, DB에 회원 행 1개.

사용법: python3 scripts/verify/f1_accounts.py (먼저 scripts/verify/stack.sh up·doctor)
"""

import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402


def steps(client: common.Client, rec: common.Recorder) -> None:
    """F1 단계를 순서대로 실행하고 기대값과 다르면 AssertionError를 낸다."""
    status, body = client.call("GET", "/health")
    rec.add("health", {}, status, body)
    # nginx는 모르는 경로에도 index.html을 200으로 주므로 본문까지 확인해야 백엔드 응답이다.
    if status != 200 or body != {"status": "ok"}:
        raise ConnectionError(f"/health가 백엔드 응답이 아님: {status}")

    email, password = common.unique_email(), "verify-" + secrets.token_hex(8)
    # 15자 미만 비밀번호는 가입 단계에서 거절된다(NIST SP 800-63B-4, passwords.py).
    status, body = client.call("POST", "/api/member/register",
                               {"username": "검증", "email": email, "password": "fourteen-chars", "password2": "fourteen-chars"})
    rec.add("register-short-password", {"username": "검증", "email": email, "password": "fourteen-chars"}, status, body)
    assert status == 400 and body.get("field") == "password", f"짧은 비밀번호 기대 400/password, 실제 {status}/{body}"
    status, body = client.call("POST", "/api/member/register",
                               {"username": "검증", "email": email, "password": password, "password2": password})
    rec.add("register", {"username": "검증", "email": email, "password": password}, status, body)
    assert status == 200 and body.get("username") == "검증", f"가입 기대 200/검증, 실제 {status}/{body}"

    status, body = client.call("GET", "/api/member/me")
    rec.add("me-after-register", {}, status, body)
    assert body.get("loggedIn") is True, f"가입 뒤 loggedIn 기대 True, 실제 {body}"

    stolen = client.clone()
    status, body = client.call("POST", "/api/member/logout")
    rec.add("logout", {}, status, body)
    assert status == 200 and body.get("success") is True, f"로그아웃 기대 200/True, 실제 {status}/{body}"

    status, body = stolen.call("GET", "/api/member/me")
    rec.add("me-with-copied-cookie", {}, status, body)
    assert body.get("loggedIn") is False, f"로그아웃 전에 복사한 쿠키는 거부돼야 함, 실제 {body}"

    status, body = client.call("GET", "/api/member/me")
    rec.add("me-after-logout", {}, status, body)
    assert body.get("loggedIn") is False, f"로그아웃 뒤 loggedIn 기대 False, 실제 {body}"

    status, body = client.call("POST", "/api/member/login", {"email": email, "password": password})
    rec.add("login", {"email": email, "password": password}, status, body)
    assert status == 200 and body.get("username") == "검증", f"로그인 기대 200/검증, 실제 {status}/{body}"

    status, body = client.call("GET", "/api/member/me")
    rec.add("me-after-login", {}, status, body)
    assert body.get("loggedIn") is True, f"로그인 뒤 loggedIn 기대 True, 실제 {body}"

    other = common.Client(client.base)
    status, body = other.call("POST", "/api/member/login", {"email": email, "password": password})
    rec.add("login-second-device", {"email": email, "password": password}, status, body)
    assert status == 200, f"두 번째 기기 로그인 기대 200, 실제 {status}/{body}"
    status, body = client.call("POST", "/api/member/logout-all")
    rec.add("logout-all", {}, status, body)
    assert status == 200 and body.get("success") is True, f"모든 기기 로그아웃 기대 200/True, 실제 {status}/{body}"
    status, body = other.call("GET", "/api/member/me")
    rec.add("me-other-device-after-logout-all", {}, status, body)
    assert body.get("loggedIn") is False, f"모든 기기 로그아웃 뒤 다른 기기 loggedIn 기대 False, 실제 {body}"

    rows = common.mariadb_scalar(f"SELECT COUNT(*) FROM member WHERE email = '{email}'")
    rec.add("db-member-rows", {"email": email}, 0, {"rows": rows})
    assert rows == "1", f"member 행 기대 1, 실제 {rows}"


if __name__ == "__main__":
    sys.exit(common.run("F1", steps))
