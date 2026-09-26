"""System-owned account domains and the rules for signing in with them."""

import unicodedata

# 시드 샘플 투자자와 시장 봇 계정. 가입으로는 만들 수 없다.
DEMO_EMAIL_DOMAIN = "@sample-investor.local"
BOT_EMAIL_DOMAIN = "@system-bot.local"
RESERVED_EMAIL_DOMAINS = (DEMO_EMAIL_DOMAIN, BOT_EMAIL_DOMAIN)

# bcrypt 해시가 아니므로 어떤 비밀번호와도 일치하지 않는다(passwords.verify가 False).
UNUSABLE_PASSWORD = "!unusable"


def _normalized(email: str | None) -> str:
    return (email or "").strip().lower()


def is_reserved_email(email: str | None) -> bool:
    return _normalized(email).endswith(RESERVED_EMAIL_DOMAINS)


def can_sign_in(email: str | None, profile: str) -> bool:
    """Bots never sign in. Sample investors sign in only outside the public profile."""
    address = _normalized(email)
    if address.endswith(BOT_EMAIL_DOMAIN):
        return False
    if address.endswith(DEMO_EMAIL_DOMAIN):
        return profile != "public"
    return True


PRIVACY_VERSION = "2026-09-26"
NICKNAME_MIN, NICKNAME_MAX = 2, 20


def normalize_nickname(value: object) -> str:
    """닉네임을 NFKC로 정규화하고 앞뒤 공백을 지운다.

    @param value 입력 값
    @returns 정규화한 닉네임
    """
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def nickname_problem(name: str) -> str | None:
    """닉네임 규칙 위반 메시지(2~20자, 제어·방향 전환·폭 0 문자 금지). 통과면 None.

    @param name 정규화한 닉네임
    @returns 위반 메시지 또는 None
    """
    if not NICKNAME_MIN <= len(name) <= NICKNAME_MAX:
        return f"닉네임은 {NICKNAME_MIN}~{NICKNAME_MAX}자로 정해 주세요."
    if any(unicodedata.category(ch) in ("Cc", "Cf") for ch in name):
        return "닉네임에 보이지 않는 문자나 제어 문자를 쓸 수 없습니다."
    return None


def email_problem(email: str) -> str | None:
    """이메일 입력 규칙 위반 메시지(주소 하나, 254자 이하). 통과면 None.

    @param email 입력 이메일(앞뒤 공백 제거 뒤)
    @returns 위반 메시지 또는 None
    """
    import mailer  # mailer가 extensions·errors를 불러오므로 accounts 로딩 순서를 바꾸지 않게 안에서 부른다

    return None if mailer.valid_address(email) else "올바른 이메일 주소 하나를 입력해 주세요."
