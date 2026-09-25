"""Database bootstrap steps that used to run on every `import app`.

They are idempotent (CREATE TABLE IF NOT EXISTS, and seeds skip rows that
already exist), so they can run once per deployment from the Flask CLI:

    flask --app app init-db
    flask --app app seed-demo
"""

import bcrypt

from alternatives import ensure_tables as ensure_alternative_tables
from api_usage import ensure_api_usage_table
from crypto import ensure_crypto_tables
from demo_seed import seed_bababa_dataset, seed_demo_investors, seed_ganada_dataset
from error_analysis import ensure_error_analysis_table
from kis_practice import ensure_kis_practice_tables
from market_bots import ensure_bot_accounts
from db import session_scope
from members import INITIAL_ASSET, ensure_member_tables
from models import Member
from research_agent import ensure_ai_tables
from settings import profile_from_env


def create_tables() -> None:
    """Create the MariaDB tables the instructor modules manage themselves."""
    ensure_alternative_tables()
    ensure_member_tables()
    ensure_kis_practice_tables()
    ensure_crypto_tables()
    ensure_error_analysis_table()
    ensure_api_usage_table()
    ensure_ai_tables()


def seed_demo_data() -> None:
    """Add the sample investors, their datasets and the market-bot accounts.

    seed_demo_investors() still honours DEMO_SEED_ENABLED; the two datasets
    only attach to accounts that already exist.
    """
    seed_demo_investors()
    # 두 데이터셋은 사용자명(가나다·바바바)으로 계정을 찾아 자산을 덮어쓴다. 공개 배포에서는
    # 누구나 그 이름으로 가입할 수 있으므로 실행하지 않는다.
    if profile_from_env() != "public":
        seed_ganada_dataset()
        seed_bababa_dataset()
    ensure_bot_accounts()


MIN_ADMIN_PASSWORD_LENGTH = 12


def create_admin(email: str, password: str, username: str = "admin") -> str:
    """Create the admin member, or reset its password if it exists.

    Returns "created" or "updated". The public profile blocks registering the
    ADMIN_EMAIL address, so this is how that account is made.
    """
    email = email.strip().lower()
    if "@" not in email:
        raise ValueError("ADMIN_EMAIL is not an email address.")
    if len(password) < MIN_ADMIN_PASSWORD_LENGTH:
        raise ValueError(f"Admin password must be at least {MIN_ADMIN_PASSWORD_LENGTH} characters.")
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    with session_scope() as db:
        member = db.query(Member).filter(Member.email == email).first()
        if member:
            member.password = hashed
            return "updated"
        db.add(Member(username=username, email=email, password=hashed, asset=INITIAL_ASSET))
        return "created"
