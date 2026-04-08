import sqlite3

from flask import current_app, g


def ensure_database_schema():
    """
    Apply lightweight schema fixes for older SQLite databases.

    This keeps the app working even if database.db was created before
    worker profile fields like country/phone were added.
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
