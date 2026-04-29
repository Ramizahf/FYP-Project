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
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    REPORT_EVIDENCE_FOLDER = os.path.join(UPLOAD_FOLDER, 'report_evidence')
    REPORT_EVIDENCE_MAX_BYTES = 5 * 1024 * 1024

    # Set FLASK_DEBUG=True in .env to enable debug mode.
    # Defaults to False so it is safe if the app is ever deployed.
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

    # Session expires after 2 hours of inactivity
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
    SESSION_PERMANENT = True

    GOOGLE_OAUTH_CLIENT_ID = os.environ.get('GOOGLE_OAUTH_CLIENT_ID', '').strip()
    GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET', '').strip()
    GOOGLE_OAUTH_BASE_URL = os.environ.get('GOOGLE_OAUTH_BASE_URL', '').strip().rstrip('/')
    GOOGLE_OAUTH_ENABLED = bool(GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET)
    GOOGLE_OAUTH_SCOPES = [
        'openid',
        'https://www.googleapis.com/auth/userinfo.email',
        'https://www.googleapis.com/auth/userinfo.profile',
    ]
