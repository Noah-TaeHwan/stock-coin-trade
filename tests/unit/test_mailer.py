"""메일: 단일 수신자, 고정 템플릿, 프래그먼트 링크, 발송 실패 숨김, 발송 상한."""

import logging
import ssl
from types import SimpleNamespace

import pytest

import mailer
from app import create_app
from settings import Settings

CONFIG = {"SMTP_HOST": "mailpit", "SMTP_PORT": 1025, "SMTP_USER": "", "SMTP_PASSWORD": "", "SMTP_STARTTLS": False}


@pytest.mark.parametrize(
    "address",
    [
        "a@x.test,b@y.test",
        "a@x.test b@y.test",
        "<a@x.test>",
        "a@x.test\nBcc: c@z.test",
        "no-at-sign",
        "a@@x.test",
        "x" * 250 + "@x.test",
    ],
)
def test_only_a_single_plain_address_is_accepted(address):
    assert mailer.valid_address(address) is False
    with pytest.raises(ValueError):
        mailer.build("verify", address, "tok", sender="no-reply@x.test", base_url="https://desk.example.test")


def test_links_use_the_configured_base_and_a_fragment_token():
    msg = mailer.build(
        "reset", "user@example.test", "abc123", sender="no-reply@x.test", base_url="https://desk.example.test"
    )
    body = msg.get_content()
    assert "https://desk.example.test/member/reset.html#t=abc123" in body
    assert "?t=" not in body and msg["To"] == "user@example.test"


def test_templates_take_no_user_text():
    # build에는 닉네임 같은 사용자 입력을 넘길 인자가 없다. 제목·본문은 코드에 고정돼 있다.
    for kind in ("verify", "exists", "reset"):
        msg = mailer.build(kind, "user@example.test", "tok", sender="no-reply@x.test", base_url="https://d.test")
        assert msg["Subject"] == mailer.TEMPLATES[kind][0]


def test_send_uses_one_recipient_and_verified_tls(monkeypatch):
    calls = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls["target"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context):
            calls["verify_mode"] = context.verify_mode

        def login(self, user, password):
            calls["login"] = user

        def send_message(self, msg, to_addrs):
            calls["to_addrs"] = to_addrs

    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    msg = mailer.build("verify", "user@example.test", "tok", sender="no-reply@x.test", base_url="https://d.test")
    mailer.send(msg, {**CONFIG, "SMTP_STARTTLS": True, "SMTP_USER": "u", "SMTP_PASSWORD": "p"})
    assert calls["to_addrs"] == ["user@example.test"] and calls["verify_mode"] == ssl.CERT_REQUIRED


class _Inline:
    """threading.Thread 대용: start()에서 바로 실행한다."""

    def __init__(self, target, daemon):
        self.target = target

    def start(self):
        self.target()


def _mail_app(ratelimit_enabled=False):
    application = create_app(
        Settings(
            profile="local",
            secret_key="k" * 40,
            session_cookie_secure=False,
            ratelimit_enabled=ratelimit_enabled,
            smtp_host="mailpit",
            smtp_port=1025,
            smtp_starttls=False,
            smtp_from="no-reply@stockdesk.local",
            public_base_url="http://127.0.0.1:3334",
        )
    )
    application.config.update(TESTING=True)
    return application


def test_send_failure_is_swallowed_and_logged_without_address(monkeypatch, caplog):
    # threading 모듈 전체가 아니라 mailer가 보는 이름만 바꾼다(limiter 저장소도 스레드를 쓴다).
    monkeypatch.setattr(mailer, "threading", SimpleNamespace(Thread=_Inline))

    def broken(msg, config):
        raise ConnectionRefusedError("mail server down")

    monkeypatch.setattr(mailer, "send", broken)
    with _mail_app().test_request_context("/"), caplog.at_level(logging.WARNING, logger="mailer"):
        mailer.queue("verify", "secret-person@example.test", "tok-value")
    assert "ConnectionRefusedError" in caplog.text
    assert "secret-person" not in caplog.text and "tok-value" not in caplog.text


def test_per_address_cap_counts_every_kind(monkeypatch):
    # threading 모듈 전체가 아니라 mailer가 보는 이름만 바꾼다(limiter 저장소도 스레드를 쓴다).
    monkeypatch.setattr(mailer, "threading", SimpleNamespace(Thread=_Inline))
    sent = []
    monkeypatch.setattr(mailer, "send", lambda msg, config: sent.append(msg["To"]))
    with _mail_app(ratelimit_enabled=True).test_request_context("/"):
        for kind in ("verify", "exists", "reset", "verify"):
            mailer.queue(kind, "capped@example.test", "tok")
        mailer.queue("verify", "other@example.test", "tok")
    assert sent == ["capped@example.test"] * 3 + ["other@example.test"]
