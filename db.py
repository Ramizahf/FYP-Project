import sqlite3

from flask import current_app, g


def ensure_database_schema():
    """
    Apply lightweight schema fixes for older SQLite databases.

    This keeps the app working even if database.db was created before
    worker profile fields like country/phone or Google account linkage
    were added.
    """
    conn = sqlite3.connect(current_app.config['DATABASE'])
    try:
        cur = conn.cursor()
        existing_cols = {
            row[1] for row in cur.execute("PRAGMA table_info(users)").fetchall()
        }

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
        job_listing_cols = {
            row[1] for row in cur.execute("PRAGMA table_info(job_listings)").fetchall()
        }
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
        g.db = sqlite3.connect(current_app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db


def row_to_dict(row):
    """Convert a single sqlite3.Row to a plain Python dict."""
    return dict(row) if row else None


def rows_to_dicts(rows):
    """
    Convert a list of sqlite3.Row objects to a list of plain dicts.

    sqlite3.Row objects support row['column'] access but are not JSON-serializable.
    """
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
    cur = get_db().execute(sql, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


def execute_db(sql, args=()):
    """Run an INSERT / UPDATE / DELETE and commit."""
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


def init_db(app):
    """Attach DB lifecycle hooks and run startup migrations."""
    app.teardown_appcontext(close_db)
    with app.app_context():
        ensure_database_schema()
