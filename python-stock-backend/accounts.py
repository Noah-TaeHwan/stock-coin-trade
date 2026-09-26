"""System-owned account domains and the rules for signing in with them."""

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
