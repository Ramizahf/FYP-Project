import os
from datetime import timedelta


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

    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
    SESSION_PERMANENT = True
