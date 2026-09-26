"""F1 회원 주행: 가입 → 메일 인증 → 로그인·로그아웃(복사 쿠키 거부)·모든 기기 로그아웃 → 메일 재설정 → 비밀번호 변경 → 탈퇴·DB 스캔.

검증 스택은 Mailpit이 있어 메일 인증 모드다. 메일 링크는 common.mail_link로 읽고, 토큰은 증거에 남기지 않는다.
사용법: python3 scripts/verify/f1_accounts.py (먼저 scripts/verify/stack.sh up·doctor)
"""

import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

HIDDEN = {"token": "***"}


def _token(link: str) -> str:
    """메일 링크의 프래그먼트에서 토큰을 꺼낸다.

    @param link 메일 속 링크
    @returns 토큰
    """
    return link.split("#t=", 1)[1]


def _login(client: common.Client, rec: common.Recorder, name: str, email: str, password: str) -> tuple[int, dict]:
    """로그인하고 증거를 남긴다.

    @returns (상태, 본문)
    """
    status, body = client.call("POST", "/api/member/login", {"email": email, "password": password})
    rec.add(name, {"email": email, "password": password}, status, body)
    return status, body


def steps(client: common.Client, rec: common.Recorder) -> None:
    """F1 단계를 순서대로 실행하고 기대값과 다르면 AssertionError를 낸다."""
    status, body = client.call("GET", "/health")
    rec.add("health", {}, status, body)
    # nginx는 모르는 경로에도 index.html을 200으로 주므로 본문까지 확인해야 백엔드 응답이다.
    if status != 200 or body != {"status": "ok"}:
        raise ConnectionError(f"/health가 백엔드 응답이 아님: {status}")

    email = common.unique_email()
    password = "verify-" + secrets.token_hex(8)
    reset_password = "verify-new-" + secrets.token_hex(8)
    changed_password = "verify-changed-" + secrets.token_hex(8)
    signup = {"username": "검증", "email": email, "agreeAge": True, "agreePrivacy": True}

    # 15자 미만 비밀번호는 가입 단계에서 거절된다(NIST SP 800-63B-4, passwords.py).
    status, body = client.call("POST", "/api/member/register",
                               {**signup, "password": "fourteen-chars", "password2": "fourteen-chars"})
    rec.add("register-short-password", {**signup, "password": "fourteen-chars"}, status, body)
    assert status == 400 and body.get("field") == "password", f"짧은 비밀번호 기대 400/password, 실제 {status}/{body}"

    status, body = client.call("POST", "/api/member/register", {**signup, "password": password, "password2": password})
    rec.add("register", {**signup, "password": password}, status, body)
    assert status == 202 and body == {"status": "check_email"}, f"가입 기대 202 check_email, 실제 {status}/{body}"

    status, body = _login(client, rec, "login-before-verify", email, password)
    assert status == 401, f"인증 전 로그인 기대 401, 실제 {status}/{body}"

    token = _token(common.mail_link(email, "/member/verify.html#t="))
    status, body = client.call("POST", "/api/member/verify", {"token": token})
    rec.add("verify", HIDDEN, status, body)
    assert status == 200 and body.get("verified") is True, f"인증 기대 200, 실제 {status}/{body}"
    status, body = client.call("POST", "/api/member/verify", {"token": token})
    rec.add("verify-reuse", HIDDEN, status, body)
    assert status == 400, f"같은 토큰 재사용 기대 400, 실제 {status}/{body}"

    status, body = _login(client, rec, "login", email, password)
    assert status == 200 and body.get("username") == "검증", f"로그인 기대 200/검증, 실제 {status}/{body}"
    status, body = client.call("GET", "/api/member/me")
    rec.add("me-after-login", {}, status, body)
    assert body.get("loggedIn") is True, f"로그인 뒤 loggedIn 기대 True, 실제 {body}"

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

    status, body = _login(client, rec, "login-again", email, password)
    assert status == 200, f"재로그인 기대 200, 실제 {status}/{body}"
    other = common.Client(client.base)
    status, body = _login(other, rec, "login-second-device", email, password)
    assert status == 200, f"두 번째 기기 로그인 기대 200, 실제 {status}/{body}"
    status, body = client.call("POST", "/api/member/logout-all")
    rec.add("logout-all", {}, status, body)
    assert status == 200 and body.get("success") is True, f"모든 기기 로그아웃 기대 200/True, 실제 {status}/{body}"
    status, body = other.call("GET", "/api/member/me")
    rec.add("me-other-device-after-logout-all", {}, status, body)
    assert body.get("loggedIn") is False, f"모든 기기 로그아웃 뒤 다른 기기 loggedIn 기대 False, 실제 {body}"

    status, body = client.call("POST", "/api/member/password/reset-request", {"email": email})
    rec.add("reset-request", {"email": email}, status, body)
    assert status == 202, f"재설정 요청 기대 202, 실제 {status}/{body}"
    token = _token(common.mail_link(email, "/member/reset.html#t="))
    status, body = client.call("POST", "/api/member/password/reset",
                               {"token": token, "password": reset_password, "password2": reset_password})
    rec.add("reset", {**HIDDEN, "password": reset_password}, status, body)
    assert status == 200 and body.get("success") is True, f"재설정 기대 200, 실제 {status}/{body}"
    status, body = _login(client, rec, "login-old-password", email, password)
    assert status == 401, f"옛 비밀번호 로그인 기대 401, 실제 {status}/{body}"
    status, body = _login(client, rec, "login-new-password", email, reset_password)
    assert status == 200, f"새 비밀번호 로그인 기대 200, 실제 {status}/{body}"

    status, body = client.call("POST", "/api/member/password/change",
                               {"current": reset_password, "password": changed_password, "password2": changed_password})
    # 증거 가림은 키 이름에 password가 있어야 동작하므로 current_password로 적는다.
    rec.add("password-change", {"current_password": reset_password, "password": changed_password}, status, body)
    assert status == 200 and body.get("success") is True, f"비밀번호 변경 기대 200, 실제 {status}/{body}"
    status, body = client.call("GET", "/api/member/me")
    rec.add("me-after-change", {}, status, body)
    assert body.get("loggedIn") is True, f"변경 뒤 이 기기 loggedIn 기대 True, 실제 {body}"

    rows = common.mariadb_scalar(f"SELECT COUNT(*) FROM member WHERE email = '{email}'")
    rec.add("db-member-rows", {"email": email}, 0, {"rows": rows})
    assert rows == "1", f"member 행 기대 1, 실제 {rows}"

    # 탈퇴: 비밀번호 확인 뒤 member_id를 가진 모든 표에서 0행이어야 한다(information_schema로 표를 찾는다).
    member_id = common.mariadb_scalar(f"SELECT member_id FROM member WHERE email = '{email}'")
    status, body = client.call("POST", "/api/member/delete", {"password": "wrong-password-value"})
    rec.add("delete-wrong-password", {"password": "wrong-password-value"}, status, body)
    assert status == 400, f"틀린 비밀번호 탈퇴 기대 400, 실제 {status}/{body}"
    status, body = client.call("POST", "/api/member/delete", {"password": changed_password})
    rec.add("delete", {"password": changed_password}, status, body)
    assert status == 200 and body.get("success") is True, f"탈퇴 기대 200, 실제 {status}/{body}"
    status, body = client.call("GET", "/api/member/me")
    rec.add("me-after-delete", {}, status, body)
    assert body.get("loggedIn") is False, f"탈퇴 뒤 loggedIn 기대 False, 실제 {body}"
    tables = common.mariadb_scalar("SELECT GROUP_CONCAT(TABLE_NAME) FROM information_schema.COLUMNS "
                                   "WHERE TABLE_SCHEMA = 'mockinv' AND COLUMN_NAME = 'member_id'").split(",")
    left = {table: common.mariadb_scalar(f"SELECT COUNT(*) FROM {table} WHERE member_id = {int(member_id)}")
            for table in tables}
    nonzero = {table: count for table, count in left.items() if count != "0"}
    # 표 이름에 token이 들어가면 증거 가림에 걸리므로, 검사한 표 수와 0이 아닌 표만 남긴다.
    rec.add("db-scan-after-delete", {"member_id": member_id}, 0, {"tables_checked": len(left), "nonzero": nonzero})
    assert not nonzero, f"탈퇴 뒤 남은 행: {nonzero}"


if __name__ == "__main__":
    sys.exit(common.run("F1", steps))
