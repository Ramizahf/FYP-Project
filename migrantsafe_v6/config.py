import os
from datetime import timedelta

# ─────────────────────────────────────────────────────────────
#  MigrantSafe — Flask Configuration
# ─────────────────────────────────────────────────────────────

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'migrantsafe-dev-secret-key-change-in-prod')

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATABASE = os.path.join(BASE_DIR, 'database.db')

    # Set FLASK_DEBUG=True in .env to enable debug mode.
    # Defaults to False so it is safe if the app is ever deployed.
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

    # Session expires after 2 hours of inactivity
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
    SESSION_PERMANENT = True
