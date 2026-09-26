"""비밀번호 정책(NIST SP 800-63B-4 §3.1.1.2)과 잘림 없는 해시."""

import bcrypt

import passwords
from accounts import UNUSABLE_PASSWORD

GOOD = "quiet river finds the sea"


def test_length_bounds_are_15_to_64_characters():
    assert passwords.problem("quiet river fi") is not None
    assert passwords.problem("quiet river fin") is None
    assert passwords.problem("a" * 30 + "b" * 34) is None
    assert passwords.problem("a" * 30 + "b" * 35) is not None


def test_listed_repeated_and_personal_passwords_are_refused():
    listed = next(line for line in passwords.BLOCKLIST.read_text(encoding="utf-8").splitlines() if line.strip())
    assert passwords.problem(listed) is not None
    assert passwords.problem(listed.upper()) is not None
    assert passwords.problem("ㅋ" * 20) is not None
    assert passwords.problem("minsu-long-password-here", email="minsu@example.test") is not None
    assert passwords.problem("hello my nick is 주식왕", nickname="주식왕") is not None


def test_long_korean_passwords_are_never_truncated():
    base = "봄비 오는 날 공시를 읽고 차트를 천천히 본다 " * 2
    stored = passwords.hash_password(base + "가")
    assert passwords.verify(base + "가", stored) is True
    assert passwords.verify(base + "나", stored) is False


def test_nfkc_equivalent_input_verifies():
    stored = passwords.hash_password(GOOD)
    assert passwords.verify("ｑｕｉｅｔ ｒｉｖｅｒ ｆｉｎｄｓ ｔｈｅ ｓｅａ", stored) is True


def test_legacy_bcrypt_hashes_still_verify_and_ask_for_rehash():
    legacy = bcrypt.hashpw(GOOD.encode(), bcrypt.gensalt()).decode()
    assert passwords.verify(GOOD, legacy) is True
    assert passwords.needs_rehash(legacy) is True
    assert passwords.needs_rehash(passwords.hash_password(GOOD)) is False
    assert passwords.verify(GOOD, UNUSABLE_PASSWORD) is False
    assert passwords.needs_rehash(UNUSABLE_PASSWORD) is False


def test_ipv6_clients_share_a_limit_per_64_block(app):
    from extensions import client_key

    with app.test_request_context(environ_base={"REMOTE_ADDR": "2001:db8:1:2:aaaa::1"}):
        first = client_key()
    with app.test_request_context(environ_base={"REMOTE_ADDR": "2001:db8:1:2:bbbb::9"}):
        second = client_key()
    with app.test_request_context(environ_base={"REMOTE_ADDR": "203.0.113.7"}):
        v4 = client_key()
    with app.test_request_context(environ_base={"REMOTE_ADDR": "::ffff:203.0.113.8"}):
        mapped = client_key()
    assert first == second == "2001:db8:1:2::/64" and v4 == "203.0.113.7" and mapped == "203.0.113.8"
