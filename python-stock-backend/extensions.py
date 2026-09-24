"""Flask extensions shared by blueprints and bound in create_app()."""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Storage and the on/off switch come from app.config (RATELIMIT_STORAGE_URI,
# RATELIMIT_ENABLED), set by Settings.flask_config().
limiter = Limiter(key_func=get_remote_address)
