"""Database bootstrap steps that used to run on every `import app`.

They are idempotent (CREATE TABLE IF NOT EXISTS, and seeds skip rows that
already exist), so they can run once per deployment from the Flask CLI:

    flask --app app init-db
    flask --app app seed-demo
"""

from alternatives import ensure_tables as ensure_alternative_tables
from api_usage import ensure_api_usage_table
from crypto import ensure_crypto_tables
from demo_seed import seed_bababa_dataset, seed_demo_investors, seed_ganada_dataset
from error_analysis import ensure_error_analysis_table
from kis_practice import ensure_kis_practice_tables
from market_bots import ensure_bot_accounts
from members import ensure_member_tables


def create_tables() -> None:
    """Create the MariaDB tables the instructor modules manage themselves."""
    ensure_alternative_tables()
    ensure_member_tables()
    ensure_kis_practice_tables()
    ensure_crypto_tables()
    ensure_error_analysis_table()
    ensure_api_usage_table()


def seed_demo_data() -> None:
    """Add the sample investors, their datasets and the market-bot accounts.

    seed_demo_investors() still honours DEMO_SEED_ENABLED; the two datasets
    only attach to accounts that already exist.
    """
    seed_demo_investors()
    seed_ganada_dataset()
    seed_bababa_dataset()
    ensure_bot_accounts()
