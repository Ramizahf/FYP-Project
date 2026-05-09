import re
import sqlite3
from datetime import date, datetime

from flask import current_app, g

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional until Postgres is configured
    psycopg = None
    dict_row = None


IntegrityError = (
    (sqlite3.IntegrityError, psycopg.IntegrityError)
    if psycopg is not None
    else (sqlite3.IntegrityError,)
)


def _use_postgres():
    return bool(current_app.config.get('DATABASE_URL'))


def _postgres_url():
    return current_app.config['DATABASE_URL']


def _allow_sqlite_fallback():
    return bool(current_app.config.get('DATABASE_FALLBACK_TO_SQLITE'))


def _postgres_connect():
    return psycopg.connect(
        _postgres_url(),
        row_factory=dict_row,
        connect_timeout=10,
        prepare_threshold=None,
    )


def _disable_postgres_for_this_process(exc):
    current_app.logger.warning(
        "Postgres is unavailable; falling back to SQLite for this process: %s",
        exc,
    )
    current_app.config['DATABASE_URL'] = ''


def _translate_sql(sql):
    """Translate the app's SQLite-style SQL into psycopg-compatible SQL."""
    translated = sql.replace('?', '%s')
    translated = translated.replace("datetime('now')", 'CURRENT_TIMESTAMP')
    return translated


def _insert_with_returning_id(sql):
    """Return inserted primary keys on Postgres for legacy execute_db callers."""
    stripped = sql.strip().rstrip(';')
    if re.match(r'^insert\s+into\s+', stripped, re.IGNORECASE) and not re.search(
        r'\breturning\b', stripped, re.IGNORECASE
    ):
        return f'{stripped} RETURNING id'
    return sql


def _normalize_value(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=' ', timespec='seconds')
    if isinstance(value, date):
        return value.isoformat()
    return value


def _normalize_row(row):
    return {key: _normalize_value(value) for key, value in dict(row).items()}


def _table_columns(cur, table_name):
    if _use_postgres():
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (table_name,)
        )
        return {row['column_name'] for row in cur.fetchall()}

    return {row[1] for row in cur.execute(f"PRAGMA table_info({table_name})").fetchall()}


POSTGRES_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id                  BIGSERIAL PRIMARY KEY,
        full_name           TEXT NOT NULL,
        email               TEXT NOT NULL UNIQUE,
        password_hash       TEXT NOT NULL,
        role                TEXT NOT NULL CHECK(role IN ('worker', 'agent', 'admin')),
        country             TEXT,
        phone               TEXT,
        google_sub          TEXT UNIQUE,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agents (
        id                  BIGSERIAL PRIMARY KEY,
        user_id             BIGINT REFERENCES users(id),
        agency_name         TEXT NOT NULL,
        license_number      TEXT,
        country             TEXT,
        state               TEXT,
        industry            TEXT,
        phone               TEXT,
        email               TEXT,
        description         TEXT,
        verification_status TEXT NOT NULL DEFAULT 'pending'
                            CHECK(verification_status IN ('verified', 'pending', 'reported')),
        created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reports (
        id               BIGSERIAL PRIMARY KEY,
        worker_id        BIGINT REFERENCES users(id),
        agent_id         BIGINT REFERENCES agents(id),
        agent_name       TEXT NOT NULL,
        agent_staff_name TEXT,
        report_reason    TEXT NOT NULL,
        description      TEXT NOT NULL,
        incident_date    TEXT,
        evidence_path    TEXT,
        status           TEXT NOT NULL DEFAULT 'open'
                         CHECK(status IN ('open', 'resolved', 'dismissed')),
        created_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chatbot_logs (
        id         BIGSERIAL PRIMARY KEY,
        user_id    BIGINT REFERENCES users(id),
        message    TEXT NOT NULL,
        response   TEXT NOT NULL,
        language   TEXT NOT NULL DEFAULT 'en',
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id         BIGSERIAL PRIMARY KEY,
        user_id    BIGINT NOT NULL REFERENCES users(id),
        sender     TEXT NOT NULL CHECK(sender IN ('user', 'bot')),
        message    TEXT NOT NULL,
        language   TEXT NOT NULL DEFAULT 'en',
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS enquiries (
        id            BIGSERIAL PRIMARY KEY,
        worker_id     BIGINT NOT NULL REFERENCES users(id),
        agent_id      BIGINT NOT NULL REFERENCES agents(id),
        subject       TEXT NOT NULL,
        category      TEXT NOT NULL,
        message       TEXT NOT NULL,
        idempotency_key TEXT UNIQUE,
        reply_message TEXT,
        status        TEXT NOT NULL DEFAULT 'open'
                      CHECK(status IN ('open', 'replied', 'closed')),
        created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        replied_at    TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS worker_job_preferences (
        id                 BIGSERIAL PRIMARY KEY,
        worker_id          BIGINT NOT NULL UNIQUE REFERENCES users(id),
        desired_job        TEXT NOT NULL,
        preferred_location TEXT,
        job_description    TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS job_listings (
        id          BIGSERIAL PRIMARY KEY,
        agent_id    BIGINT NOT NULL REFERENCES agents(id),
        job_title   TEXT NOT NULL,
        location    TEXT NOT NULL,
        description TEXT NOT NULL,
        status      TEXT NOT NULL DEFAULT 'live',
        created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS job_interests (
        id         BIGSERIAL PRIMARY KEY,
        worker_id  BIGINT NOT NULL REFERENCES users(id),
        job_id     BIGINT NOT NULL REFERENCES job_listings(id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower ON users(lower(email))",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub ON users(google_sub) WHERE google_sub IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_chat_messages_user_id_id ON chat_messages(user_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_enquiries_worker_id_created_at ON enquiries(worker_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_enquiries_agent_id_status_created_at ON enquiries(agent_id, status, created_at DESC)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_worker_job_preferences_worker_id ON worker_job_preferences(worker_id)",
    "CREATE INDEX IF NOT EXISTS idx_job_listings_agent_id_created_at ON job_listings(agent_id, created_at DESC)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_job_interests_worker_job ON job_interests(worker_id, job_id)",
)


def ensure_database_schema():
    """Apply startup schema setup for SQLite or Postgres."""
    if _use_postgres():
        if psycopg is None:
            raise RuntimeError(
                'DATABASE_URL is set, but psycopg is not installed. Run: pip install -r requirements.txt'
            )
        try:
            conn = _postgres_connect()
        except psycopg.OperationalError as exc:
            if not _allow_sqlite_fallback():
                raise
            _disable_postgres_for_this_process(exc)
        else:
            try:
                with conn.cursor() as cur:
                    for statement in POSTGRES_SCHEMA:
                        cur.execute(statement)
                    enquiry_cols = _table_columns(cur, 'enquiries')
                    if 'idempotency_key' not in enquiry_cols:
                        cur.execute("ALTER TABLE enquiries ADD COLUMN idempotency_key TEXT")
                    cur.execute(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_enquiries_idempotency_key "
                        "ON enquiries(idempotency_key) WHERE idempotency_key IS NOT NULL"
                    )
                conn.commit()
            finally:
                conn.close()
            return

    if _use_postgres():
        return

    conn = sqlite3.connect(current_app.config['DATABASE'])
    try:
        cur = conn.cursor()
        existing_cols = _table_columns(cur, 'users')

        if 'country' not in existing_cols:
            cur.execute("ALTER TABLE users ADD COLUMN country TEXT")
        if 'phone' not in existing_cols:
            cur.execute("ALTER TABLE users ADD COLUMN phone TEXT")
        if 'google_sub' not in existing_cols:
            cur.execute("ALTER TABLE users ADD COLUMN google_sub TEXT")

        cur.execute("UPDATE users SET email = lower(trim(email)) WHERE email IS NOT NULL")
        cur.execute("""
            UPDATE users
            SET email = substr(email, 1, instr(email, '@') - 1) || '@gmail.com'
            WHERE email LIKE '%@googlemail.com'
        """)

        duplicate_emails = cur.execute("""
            SELECT email, COUNT(*) AS total
            FROM users
            GROUP BY email
            HAVING COUNT(*) > 1
        """).fetchall()
        if duplicate_emails:
            duplicates = ', '.join(row[0] for row in duplicate_emails)
            raise RuntimeError(
                f'Duplicate user emails found after normalization: {duplicates}. '
                'Resolve them before starting the app again.'
            )

        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_nocase "
            "ON users(email COLLATE NOCASE)"
        )
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub "
            "ON users(google_sub) WHERE google_sub IS NOT NULL"
        )
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id),
                sender     TEXT    NOT NULL CHECK(sender IN ('user', 'bot')),
                message    TEXT    NOT NULL,
                language   TEXT    NOT NULL DEFAULT 'en',
                created_at TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_messages_user_id_id "
            "ON chat_messages(user_id, id)"
        )
        cur.execute("""
            CREATE TABLE IF NOT EXISTS enquiries (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id     INTEGER NOT NULL REFERENCES users(id),
                agent_id      INTEGER NOT NULL REFERENCES agents(id),
                subject       TEXT    NOT NULL,
                category      TEXT    NOT NULL,
                message       TEXT    NOT NULL,
                idempotency_key TEXT UNIQUE,
                reply_message TEXT,
                status        TEXT    NOT NULL DEFAULT 'open'
                              CHECK(status IN ('open', 'replied', 'closed')),
                created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                replied_at    TEXT
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_enquiries_worker_id_created_at "
            "ON enquiries(worker_id, created_at DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_enquiries_agent_id_status_created_at "
            "ON enquiries(agent_id, status, created_at DESC)"
        )
        enquiry_cols = _table_columns(cur, 'enquiries')
        if 'idempotency_key' not in enquiry_cols:
            cur.execute("ALTER TABLE enquiries ADD COLUMN idempotency_key TEXT")
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_enquiries_idempotency_key "
            "ON enquiries(idempotency_key) WHERE idempotency_key IS NOT NULL"
        )
        report_cols = _table_columns(cur, 'reports')
        if 'agent_staff_name' not in report_cols:
            cur.execute("ALTER TABLE reports ADD COLUMN agent_staff_name TEXT")
        if 'evidence_path' not in report_cols:
            cur.execute("ALTER TABLE reports ADD COLUMN evidence_path TEXT")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS worker_job_preferences (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id          INTEGER NOT NULL UNIQUE REFERENCES users(id),
                desired_job        TEXT    NOT NULL,
                preferred_location TEXT,
                job_description    TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS job_listings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id    INTEGER NOT NULL REFERENCES agents(id),
                job_title   TEXT    NOT NULL,
                location    TEXT    NOT NULL,
                description TEXT    NOT NULL,
                status      TEXT    NOT NULL DEFAULT 'live',
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        job_listing_cols = _table_columns(cur, 'job_listings')
        if 'status' not in job_listing_cols:
            cur.execute("ALTER TABLE job_listings ADD COLUMN status TEXT NOT NULL DEFAULT 'live'")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS job_interests (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id  INTEGER NOT NULL REFERENCES users(id),
                job_id     INTEGER NOT NULL REFERENCES job_listings(id),
                created_at TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_worker_job_preferences_worker_id "
            "ON worker_job_preferences(worker_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_job_listings_agent_id_created_at "
            "ON job_listings(agent_id, created_at DESC)"
        )
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_job_interests_worker_job "
            "ON job_interests(worker_id, job_id)"
        )

        legacy_chatbot_logs = cur.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'chatbot_logs'"
        ).fetchone()
        existing_chat_messages = cur.execute(
            "SELECT COUNT(*) FROM chat_messages"
        ).fetchone()[0]
        if legacy_chatbot_logs and existing_chat_messages == 0:
            legacy_rows = cur.execute(
                "SELECT user_id, message, response, language, created_at "
                "FROM chatbot_logs WHERE user_id IS NOT NULL ORDER BY id ASC"
            ).fetchall()
            for user_id, message, response, language, created_at in legacy_rows:
                cur.execute(
                    "INSERT INTO chat_messages (user_id, sender, message, language, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_id, 'user', message, language, created_at)
                )
                cur.execute(
                    "INSERT INTO chat_messages (user_id, sender, message, language, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_id, 'bot', response, language, created_at)
                )

        conn.commit()
    finally:
        conn.close()


def get_db():
    """Return the database connection for this request."""
    if 'db' not in g:
        if _use_postgres():
            if psycopg is None:
                raise RuntimeError('DATABASE_URL is set, but psycopg is not installed.')
            g.db = _postgres_connect()
        else:
            g.db = sqlite3.connect(current_app.config['DATABASE'])
            g.db.row_factory = sqlite3.Row
    return g.db


def row_to_dict(row):
    """Convert a single database row to a plain Python dict."""
    return dict(row) if row else None


def rows_to_dicts(rows):
    """Convert database rows to plain dictionaries."""
    return [dict(r) for r in rows] if rows else []


def close_db(error=None):
    """Automatically close the DB connection when the request ends."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def query_db(sql, args=(), one=False):
    """
    Run a SELECT query and return results.
    one=True  -> return a single row (or None)
    one=False -> return a list of rows
    """
    db = get_db()
    if _use_postgres():
        with db.cursor() as cur:
            cur.execute(_translate_sql(sql), args)
            rv = [_normalize_row(row) for row in cur.fetchall()]
    else:
        cur = db.execute(sql, args)
        rv = cur.fetchall()
        cur.close()
    return (rv[0] if rv else None) if one else rv


def execute_db(sql, args=()):
    """Run an INSERT / UPDATE / DELETE and commit."""
    db = get_db()
    if _use_postgres():
        statement = _insert_with_returning_id(_translate_sql(sql))
        with db.cursor() as cur:
            cur.execute(statement, args)
            inserted = cur.fetchone() if cur.description else None
        db.commit()
        return inserted['id'] if inserted and 'id' in inserted else None

    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


def init_db(app):
    """Attach DB lifecycle hooks and run startup migrations."""
    app.teardown_appcontext(close_db)
    if not app.config.get('DATABASE_INIT_ON_STARTUP', True):
        app.logger.info('Skipping database schema initialization on startup.')
        return

    with app.app_context():
        ensure_database_schema()
