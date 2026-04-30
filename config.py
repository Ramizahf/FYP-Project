import os
from datetime import timedelta

# ─────────────────────────────────────────────────────────────
#  MigrantSafe — Flask Configuration
# ─────────────────────────────────────────────────────────────

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'migrantsafe-dev-secret-key-change-in-prod')

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATABASE = os.path.join(BASE_DIR, 'database.db')
    DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
    DATABASE_FALLBACK_TO_SQLITE = os.environ.get(
        'DATABASE_FALLBACK_TO_SQLITE',
        'True' if os.environ.get('FLASK_DEBUG', 'False').lower() == 'true' else 'False'
    ).lower() == 'true'
    DATABASE_INIT_ON_STARTUP = os.environ.get(
        'DATABASE_INIT_ON_STARTUP',
        'False' if os.environ.get('VERCEL') else 'True'
    ).lower() == 'true'
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    REPORT_EVIDENCE_FOLDER = os.path.join(UPLOAD_FOLDER, 'report_evidence')
    REPORT_EVIDENCE_MAX_BYTES = 5 * 1024 * 1024

    # Set FLASK_DEBUG=True in .env to enable debug mode.
    # Defaults to False so it is safe if the app is ever deployed.
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

    # Session expires after 2 hours of inactivity
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
    SESSION_PERMANENT = True
