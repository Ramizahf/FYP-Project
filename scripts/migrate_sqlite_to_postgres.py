"""
Copy the local SQLite database into the configured Postgres/Supabase database.

Usage:
    python scripts/migrate_sqlite_to_postgres.py
    python scripts/migrate_sqlite_to_postgres.py --truncate

Set DATABASE_URL in .env before running. Use --truncate only when you want to
clear the target tables first.
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    print("Missing psycopg. Run: pip install -r requirements.txt", file=sys.stderr)
    raise

ROOT = Path(__file__).resolve().parents[1]
SQLITE_PATH = ROOT / "database.db"
sys.path.insert(0, str(ROOT))

TABLES = [
    "users",
    "agents",
    "reports",
    "chatbot_logs",
    "chat_messages",
    "enquiries",
    "worker_job_preferences",
    "job_listings",
    "job_interests",
]

OPTIONAL_FOREIGN_KEYS = {
    "agents": {"user_id": "users"},
    "reports": {"worker_id": "users", "agent_id": "agents"},
    "chatbot_logs": {"user_id": "users"},
}

REQUIRED_FOREIGN_KEYS = {
    "chat_messages": {"user_id": "users"},
    "enquiries": {"worker_id": "users", "agent_id": "agents"},
    "worker_job_preferences": {"worker_id": "users"},
    "job_listings": {"agent_id": "agents"},
    "job_interests": {"worker_id": "users", "job_id": "job_listings"},
}


def sqlite_table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def sqlite_columns(conn, table_name):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")]


def postgres_columns(cur, table_name):
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table_name,),
    )
    return {row["column_name"] for row in cur.fetchall()}


def sqlite_ids(sqlite_conn, table_name):
    if not sqlite_table_exists(sqlite_conn, table_name):
        return set()
    return {row["id"] for row in sqlite_conn.execute(f"SELECT id FROM {table_name}")}


def prepare_row(table_name, row, columns, valid_ids):
    values = {col: row[col] for col in columns}

    for column, parent_table in OPTIONAL_FOREIGN_KEYS.get(table_name, {}).items():
        if column in values and values[column] is not None and values[column] not in valid_ids[parent_table]:
            values[column] = None

    for column, parent_table in REQUIRED_FOREIGN_KEYS.get(table_name, {}).items():
        if column in values and values[column] not in valid_ids[parent_table]:
            return None

    return tuple(values[col] for col in columns)


def copy_table(sqlite_conn, pg_cur, table_name, valid_ids):
    if not sqlite_table_exists(sqlite_conn, table_name):
        print(f"skip {table_name}: not in SQLite database")
        return

    sqlite_cols = sqlite_columns(sqlite_conn, table_name)
    pg_cols = postgres_columns(pg_cur, table_name)
    columns = [col for col in sqlite_cols if col in pg_cols]
    if not columns:
        print(f"skip {table_name}: no shared columns")
        return

    rows = sqlite_conn.execute(
        f"SELECT {', '.join(columns)} FROM {table_name} ORDER BY id"
    ).fetchall()
    if not rows:
        print(f"copy {table_name}: 0 rows")
        return

    placeholders = ", ".join(["%s"] * len(columns))
    column_sql = ", ".join(columns)
    update_cols = [col for col in columns if col != "id"]
    if update_cols:
        update_sql = ", ".join(f"{col} = EXCLUDED.{col}" for col in update_cols)
        conflict_sql = f"ON CONFLICT (id) DO UPDATE SET {update_sql}"
    else:
        conflict_sql = "ON CONFLICT (id) DO NOTHING"

    insert_sql = (
        f"INSERT INTO {table_name} ({column_sql}) "
        f"VALUES ({placeholders}) {conflict_sql}"
    )
    prepared_rows = [
        prepared
        for row in rows
        if (prepared := prepare_row(table_name, row, columns, valid_ids)) is not None
    ]
    if not prepared_rows:
        print(f"copy {table_name}: 0 rows copied, {len(rows)} skipped")
        return

    pg_cur.executemany(insert_sql, prepared_rows)
    skipped = len(rows) - len(prepared_rows)
    suffix = f", {skipped} skipped" if skipped else ""
    print(f"copy {table_name}: {len(prepared_rows)} rows{suffix}")


def reset_sequence(pg_cur, table_name):
    pg_cur.execute("SELECT to_regclass(%s) AS seq", (f"{table_name}_id_seq",))
    row = pg_cur.fetchone()
    if not row or not row["seq"]:
        return
    pg_cur.execute(
        f"""
        SELECT setval(
            %s,
            GREATEST(COALESCE((SELECT MAX(id) FROM {table_name}), 0), 1),
            COALESCE((SELECT MAX(id) FROM {table_name}), 0) > 0
        )
        """,
        (f"{table_name}_id_seq",),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Clear target Postgres tables with TRUNCATE ... CASCADE before copying.",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env", override=True)
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set in .env")
    if not SQLITE_PATH.exists():
        raise RuntimeError(f"SQLite database not found: {SQLITE_PATH}")

    from app_factory import create_app

    create_app()

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    valid_ids = {table_name: sqlite_ids(sqlite_conn, table_name) for table_name in TABLES}
    try:
        with psycopg.connect(database_url, row_factory=dict_row) as pg_conn:
            with pg_conn.cursor() as pg_cur:
                if args.truncate:
                    pg_cur.execute(
                        "TRUNCATE TABLE "
                        + ", ".join(reversed(TABLES))
                        + " RESTART IDENTITY CASCADE"
                    )
                    print("target tables truncated")

                for table_name in TABLES:
                    copy_table(sqlite_conn, pg_cur, table_name, valid_ids)
                for table_name in TABLES:
                    reset_sequence(pg_cur, table_name)
            pg_conn.commit()
    finally:
        sqlite_conn.close()

    print("migration complete")


if __name__ == "__main__":
    main()
