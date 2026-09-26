"""메일이 준비되기 전 공개 배포의 가입 차단과 화면 안내 신호."""

from app import create_app
from settings import Settings

CLOSED = Settings(
    profile="public",
    secret_key="p" * 40,
    session_cookie_secure=True,
    admin_email="owner@example.com",
    ratelimit_enabled=True,
    signup_enabled=False,
)


def _client(settings):
    application = create_app(settings)
    application.config.update(TESTING=True)
    return application.test_client()


def test_closed_signup_refuses_registration_before_touching_the_database():
    response = _client(CLOSED).post(
        "/api/member/register",
        json={"username": "가입", "email": "a@example.test", "password": "x" * 20, "password2": "x" * 20},
    )
    assert response.status_code == 403
    assert response.get_json()["error"] == "SIGNUP_CLOSED"


def test_me_tells_the_page_whether_signup_is_open(client):
    assert client.get("/api/member/me").get_json()["signupOpen"] is True
    assert _client(CLOSED).get("/api/member/me").get_json()["signupOpen"] is False
