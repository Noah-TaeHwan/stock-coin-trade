"""닉네임(사칭 방지)과 이메일(단일 주소) 입력 규칙."""

import pytest

from accounts import email_problem, nickname_problem, normalize_nickname


@pytest.mark.parametrize("name", ["주식왕", "ab", "노아 Trader 01", "가" * 20])
def test_ordinary_nicknames_pass(name):
    assert nickname_problem(normalize_nickname(name)) is None


@pytest.mark.parametrize("name", ["a", "가" * 21, "adm‮nimda", "no​ah", "tab\tname", "  "])
def test_short_long_and_invisible_or_control_characters_are_refused(name):
    assert nickname_problem(normalize_nickname(name)) is not None


def test_fullwidth_nickname_is_normalized():
    assert normalize_nickname("ｎｏａｈ") == "noah"


@pytest.mark.parametrize(
    "email", ["a@x.test,b@y.test", "a b@x.test", "<a@x.test>", "a@x.test\n", "x" * 250 + "@x.test", "nope"]
)
def test_email_must_be_one_plain_address(email):
    assert email_problem(email) is not None


def test_plain_email_passes():
    assert email_problem("user.name+tag@example.test") is None
