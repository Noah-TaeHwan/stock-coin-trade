"""Database bootstrap steps that used to run on every `import app`.

They are idempotent (CREATE TABLE IF NOT EXISTS, and seeds skip rows that
already exist), so they can run once per deployment from the Flask CLI:

    flask --app app init-db
    flask --app app seed-demo
"""

from sqlalchemy import func, text

from alternatives import ensure_tables as ensure_alternative_tables
from accounts import PUBLIC_DEMO_EMAIL, PUBLIC_DEMO_PASSWORD, PUBLIC_DEMO_USERNAME
from api_usage import ensure_api_usage_table
from crypto import ensure_crypto_tables
from dart_radar import ensure_dart_tables
from demo_seed import seed_bababa_dataset, seed_demo_investors, seed_ganada_dataset
from error_analysis import ensure_error_analysis_table
from kis_practice import ensure_kis_practice_tables
from market_bots import ensure_bot_accounts
from db import session_scope
from members import INITIAL_ASSET, ensure_member_tables
import passwords
from member_sessions import ensure_session_table
from member_tokens import ensure_token_table
from member_delete import ensure_deletable
from models import Member
from authz import admin_email
from jev_usage import ensure_jev_tables
from research_agent import ensure_ai_tables
from stock_trading import ensure_stock_order_columns
from settings import profile_from_env


def create_tables() -> None:
    """Create the MariaDB tables the instructor modules manage themselves."""
    ensure_alternative_tables()
    ensure_member_tables()
    ensure_session_table()
    ensure_token_table()
    ensure_kis_practice_tables()
    ensure_crypto_tables()
    ensure_error_analysis_table()
    ensure_api_usage_table()
    ensure_ai_tables()
    ensure_stock_order_columns()
    ensure_jev_tables()
    ensure_dart_tables()
    ensure_deletable()


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


def create_admin(email: str, password: str, username: str = "admin") -> str:
    """Create the admin member, or reset its password if it exists.

    Returns "created" or "updated". The public profile blocks registering the
    ADMIN_EMAIL address, so this is how that account is made.
    """
    email = email.strip().lower()
    if "@" not in email:
        raise ValueError("ADMIN_EMAIL is not an email address.")
    weak = passwords.problem(password, email=email, nickname=username)
    if weak:
        raise ValueError(weak)
    hashed = passwords.hash_password(password)
    with session_scope() as db:
        member = db.query(Member).filter(Member.email == email).first()
        if member:
            if member.is_demo:
                raise ValueError("공용 데모 계정은 관리자로 전환할 수 없습니다.")
            member.password = hashed
            member.email_verified_at = member.email_verified_at or func.now()
            # 새 비밀번호와 기존 세션 폐기를 한 트랜잭션으로 커밋한다(탈취된 옛 쿠키가 남지 않게).
            db.execute(text("DELETE FROM member_session WHERE member_id = :m"), {"m": member.member_id})
            db.execute(text("UPDATE api_key SET is_active = 0 WHERE member_id = :m"), {"m": member.member_id})
            return "updated"
        # CLI로 만드는 관리자는 운영자 본인이므로 메일 인증을 거친 것으로 본다.
        db.add(Member(username=username, email=email, password=hashed, asset=INITIAL_ASSET, email_verified_at=func.now()))
        return "created"


def create_public_demo() -> str:
    """공개 자격정보를 가진 일반 회원을 한 번 만들고, 같은 계정이면 유지한다."""
    if admin_email() == PUBLIC_DEMO_EMAIL:
        raise ValueError("관리자 주소와 공용 데모 주소가 같습니다.")
    with session_scope() as db:
        member = db.query(Member).filter(Member.email == PUBLIC_DEMO_EMAIL).first()
        if member:
            if (member.is_demo and member.username == PUBLIC_DEMO_USERNAME and
                    member.email_verified_at is not None and
                    passwords.verify(PUBLIC_DEMO_PASSWORD, member.password)):
                return "unchanged"
            raise ValueError("이미 사용 중인 이메일입니다. 기존 계정은 변경하지 않았습니다.")
        db.add(Member(username=PUBLIC_DEMO_USERNAME, email=PUBLIC_DEMO_EMAIL,
                      password=passwords.hash_password(PUBLIC_DEMO_PASSWORD),
                      asset=INITIAL_ASSET, is_demo=True, email_verified_at=func.now()))
        return "created"
