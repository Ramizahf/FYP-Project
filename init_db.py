"""
init_db.py
──────────
Run this script ONCE to create the SQLite database and its tables.
It also seeds the database with demo users and sample agents so you
can log in and test the app right away.

Usage:
    python init_db.py
"""

import sqlite3
import os
from datetime import datetime
from werkzeug.security import generate_password_hash
from config import Config

# ─────────────────────────────────────────────────────────────
#  SQL — Create all tables
# ─────────────────────────────────────────────────────────────

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name           TEXT    NOT NULL,
    email               TEXT    NOT NULL UNIQUE,
    password_hash       TEXT    NOT NULL,
    role                TEXT    NOT NULL CHECK(role IN ('worker', 'agent', 'admin')),
    country             TEXT,
    phone               TEXT,
    google_sub          TEXT    UNIQUE,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_AGENTS = """
CREATE TABLE IF NOT EXISTS agents (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER REFERENCES users(id),
    agency_name         TEXT    NOT NULL,
    license_number      TEXT,
    country             TEXT,
    state               TEXT,
    industry            TEXT,
    phone               TEXT,
    email               TEXT,
    description         TEXT,
    verification_status TEXT    NOT NULL DEFAULT 'pending'
                        CHECK(verification_status IN ('verified', 'pending', 'reported')),
    created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_REPORTS = """
CREATE TABLE IF NOT EXISTS reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id     INTEGER REFERENCES users(id),
    agent_id      INTEGER REFERENCES agents(id),
    agent_name    TEXT    NOT NULL,
    agent_staff_name TEXT,
    report_reason TEXT    NOT NULL,
    description   TEXT    NOT NULL,
    incident_date TEXT,
    evidence_path TEXT,
    status        TEXT    NOT NULL DEFAULT 'open'
                  CHECK(status IN ('open', 'resolved', 'dismissed')),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_CHATBOT_LOGS = """
CREATE TABLE IF NOT EXISTS chatbot_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id),
    message    TEXT NOT NULL,
    response   TEXT NOT NULL,
    language   TEXT NOT NULL DEFAULT 'en',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_CHAT_MESSAGES = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    sender     TEXT    NOT NULL CHECK(sender IN ('user', 'bot')),
    message    TEXT    NOT NULL,
    language   TEXT    NOT NULL DEFAULT 'en',
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_ENQUIRIES = """
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
);
"""

CREATE_WORKER_JOB_PREFERENCES = """
CREATE TABLE IF NOT EXISTS worker_job_preferences (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id          INTEGER NOT NULL UNIQUE REFERENCES users(id),
    desired_job        TEXT    NOT NULL,
    preferred_location TEXT,
    job_description    TEXT
);
"""

CREATE_JOB_LISTINGS = """
CREATE TABLE IF NOT EXISTS job_listings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    INTEGER NOT NULL REFERENCES agents(id),
    job_title   TEXT    NOT NULL,
    location    TEXT    NOT NULL,
    description TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'live',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_JOB_INTERESTS = """
CREATE TABLE IF NOT EXISTS job_interests (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id  INTEGER NOT NULL REFERENCES users(id),
    job_id     INTEGER NOT NULL REFERENCES job_listings(id),
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

# ─────────────────────────────────────────────────────────────
#  SEED DATA — Demo users
# ─────────────────────────────────────────────────────────────

DEMO_USERS = [
    # (full_name, email, plain_password, role)
    # Passwords meet registration rules: 8+ chars, 1 uppercase, 1 number
    ('Demo Worker',  'worker@migrantsafe.com', 'Worker01',  'worker'),
    ('Demo Agent',   'agent@migrantsafe.com',  'Agent01',   'agent'),
    ('Admin',        'admin@migrantsafe.com',  'Admin01',   'admin'),
]

# ─────────────────────────────────────────────────────────────
#  SEED DATA — Sample agents (realistic dummy data)
# ─────────────────────────────────────────────────────────────

SAMPLE_AGENTS = [
    # (agency_name, license_number, state, industry, phone, email, description, status)
    (
        'Suria Recruitment Sdn Bhd',
        'JTKSM/P/2019/0145',
        'Kuala Lumpur', 'Construction',
        '+60 3-2111 4567', 'info@suriarecruit.com.my',
        'A licensed recruitment agency specialising in placing construction workers from Bangladesh, Nepal, and Myanmar. Known for transparent fee structures and timely visa processing. Over 500 workers placed successfully.',
        'verified'
    ),
    (
        'Harapan Recruitment Sdn Bhd',
        'JTKSM/P/2020/0288',
        'Penang', 'Hospitality',
        '+60 4-2890 3322', 'contact@harapanhr.my',
        'Specialises in hospitality and service-sector placements across Penang and Northern Malaysia. Fully compliant with MOHR guidelines and zero-cost-to-worker policy.',
        'verified'
    ),
    (
        'AsiaBridge Manpower',
        'JTKSM/P/2018/0097',
        'Sabah', 'Agriculture',
        '+60 88-226 711', 'ops@asiabridge.my',
        'Long-established manpower agency serving plantation and agricultural sectors in Sabah. Works with palm oil estates and rubber plantations.',
        'verified'
    ),
    (
        'TrustWork Recruitment',
        'JTKSM/P/2021/0501',
        'Selangor', 'Construction',
        '+60 3-5522 9911', 'support@trustwork.my',
        'Award-winning agency known for ethical recruitment practices. Provides pre-departure orientation in Bangla and Nepali.',
        'verified'
    ),
    (
        'Bintang Labour Agency',
        'JTKSM/P/2023/0812',
        'Selangor', 'General',
        '+60 3-7788 6600', 'admin@bintan-labour.my',
        'Recently registered agency offering general labour placements. Currently under standard admin review process.',
        'pending'
    ),
    (
        'GlobalPath Agency',
        'JTKSM/P/2024/0033',
        'Kuala Lumpur', 'Technology',
        '+60 3-2284 5599', 'hello@globalpath.my',
        'A newer agency focusing on technology and IT sector placements. Application for verification submitted.',
        'pending'
    ),
    (
        'FastWork Services',
        'JTKSM/P/2020/0376',
        'Johor', 'Manufacturing',
        '+60 7-3319 8870', 'info@fastworkjb.com',
        'This agency has received multiple worker complaints regarding excessive upfront fees and misleading job descriptions. Admin investigation is currently active.',
        'reported'
    ),
]


# ─────────────────────────────────────────────────────────────
#  MAIN — Run the setup
# ─────────────────────────────────────────────────────────────

def init_db():
    db_path = Config.DATABASE
    print(f"→ Using database: {db_path}")

    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()

    # Create tables (IF NOT EXISTS — safe to re-run)
    print("→ Creating tables...")
    cur.execute(CREATE_USERS)
    cur.execute(CREATE_AGENTS)
    cur.execute(CREATE_REPORTS)
    cur.execute(CREATE_CHATBOT_LOGS)
    cur.execute(CREATE_CHAT_MESSAGES)
    cur.execute(CREATE_ENQUIRIES)
    cur.execute(CREATE_WORKER_JOB_PREFERENCES)
    cur.execute(CREATE_JOB_LISTINGS)
    cur.execute(CREATE_JOB_INTERESTS)
    conn.commit()
    print("  ✓ Tables created.")

    # ── MIGRATION: remove NOT NULL from agents.user_id ──────────────────────
    # SQLite cannot drop a NOT NULL constraint with ALTER TABLE.
    # We check the notnull flag; if set, rebuild the table with the nullable schema.
    agents_cols = cur.execute("PRAGMA table_info(agents)").fetchall()
    user_id_col = next((c for c in agents_cols if c[1] == 'user_id'), None)
    if user_id_col and user_id_col[3] == 1:   # col[3] = notnull flag
        print("→ Migration: removing NOT NULL from agents.user_id ...")
        cur.executescript("""
            PRAGMA foreign_keys = OFF;

            CREATE TABLE IF NOT EXISTS agents_new (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id             INTEGER REFERENCES users(id),
                agency_name         TEXT    NOT NULL,
                license_number      TEXT,
                country             TEXT,
                state               TEXT,
                industry            TEXT,
                phone               TEXT,
                email               TEXT,
                description         TEXT,
                verification_status TEXT    NOT NULL DEFAULT 'pending'
                                    CHECK(verification_status IN ('verified', 'pending', 'reported')),
                created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            INSERT INTO agents_new SELECT * FROM agents;
            DROP TABLE agents;
            ALTER TABLE agents_new RENAME TO agents;

            PRAGMA foreign_keys = ON;
        """)
        conn.commit()
        print("  ✓ Migration: agents.user_id is now nullable.")

        # Unlink public sample agents from the demo agent account.
        # Keep only the row whose email matches the demo agent as their personal profile.
        cur.execute(
            "UPDATE agents SET user_id = NULL WHERE email != 'agent@migrantsafe.com'"
        )
        conn.commit()
        print("  ✓ Migration: public sample agents unlinked from demo agent account.")

    # ── MIGRATION: add country and phone columns to users if they don't exist yet
    # This handles existing databases that were created before this fix.
    existing_cols = [row[1] for row in cur.execute("PRAGMA table_info(users)").fetchall()]
    if 'country' not in existing_cols:
        cur.execute("ALTER TABLE users ADD COLUMN country TEXT")
        print("  ✓ Migration: added 'country' column to users table.")
    if 'phone' not in existing_cols:
        cur.execute("ALTER TABLE users ADD COLUMN phone TEXT")
        print("  ✓ Migration: added 'phone' column to users table.")
    if 'google_sub' not in existing_cols:
        cur.execute("ALTER TABLE users ADD COLUMN google_sub TEXT")
        print("  OK Migration: added 'google_sub' column to users table.")
    report_cols = [row[1] for row in cur.execute("PRAGMA table_info(reports)").fetchall()]
    if 'evidence_path' not in report_cols:
        cur.execute("ALTER TABLE reports ADD COLUMN evidence_path TEXT")
        print("  OK Migration: added 'evidence_path' column to reports table.")
    job_listing_cols = [row[1] for row in cur.execute("PRAGMA table_info(job_listings)").fetchall()]
    if 'status' not in job_listing_cols:
        cur.execute("ALTER TABLE job_listings ADD COLUMN status TEXT NOT NULL DEFAULT 'live'")
        print("  OK Migration: added 'status' column to job_listings table.")
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
            f"Duplicate user emails found after normalization: {duplicates}. "
            "Resolve them before running init_db.py again."
        )

    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_nocase "
        "ON users(email COLLATE NOCASE)"
    )
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub "
        "ON users(google_sub) WHERE google_sub IS NOT NULL"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_messages_user_id_id "
        "ON chat_messages(user_id, id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_enquiries_worker_id_created_at "
        "ON enquiries(worker_id, created_at DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_enquiries_agent_id_status_created_at "
        "ON enquiries(agent_id, status, created_at DESC)"
    )
    enquiry_cols = {c[1] for c in cur.execute("PRAGMA table_info(enquiries)").fetchall()}
    if 'idempotency_key' not in enquiry_cols:
        cur.execute("ALTER TABLE enquiries ADD COLUMN idempotency_key TEXT")
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_enquiries_idempotency_key "
        "ON enquiries(idempotency_key) WHERE idempotency_key IS NOT NULL"
    )
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

    # Seed demo users (skip if already exist)
    print("→ Seeding demo users...")
    for full_name, email, plain_pw, role in DEMO_USERS:
        email = email.strip().lower()
        existing = cur.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            print(f"  ⟳ Skipped (already exists): {email}")
            continue
        pw_hash = generate_password_hash(plain_pw)
        cur.execute(
            "INSERT INTO users (full_name, email, password_hash, role) "
            "VALUES (?, ?, ?, ?)",
            (full_name, email, pw_hash, role)
        )
        print(f"  ✓ Created user: {email}  [{role}]")
    conn.commit()

    # Get the demo agent user's id — used only for their personal profile row
    agent_user = cur.execute("SELECT id FROM users WHERE email = ?", ('agent@migrantsafe.com',)).fetchone()
    agent_user_id = agent_user[0] if agent_user else None

    # Seed sample agents (skip if agents table already has data)
    existing_agents = cur.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    if existing_agents == 0:
        print("→ Seeding sample agents (public, user_id = NULL)...")
        for agency_name, license_number, state, industry, phone, email, description, status in SAMPLE_AGENTS:
            cur.execute("""
                INSERT INTO agents
                    (user_id, agency_name, license_number, state, industry, phone, email, description, verification_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                None,           # ← public sample: not owned by any user account
                agency_name, license_number, state, industry,
                phone, email, description, status
            ))
            print(f"  ✓ Public agent: {agency_name}  [{status}]")

        # Seed one personal agent profile linked to the demo agent account.
        # This is the profile the demo agent sees and edits on their dashboard.
        if agent_user_id:
            cur.execute("""
                INSERT INTO agents
                    (user_id, agency_name, license_number, state, industry, phone, email, description, verification_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                agent_user_id,
                'Demo Recruitment Agency',
                'JTKSM/P/2025/DEMO',
                'Kuala Lumpur',
                'General',
                '+60 3-0000 0000',
                'agent@migrantsafe.com',
                'This is the demo agent profile. Log in as the demo agent to edit this profile.',
                'pending'
            ))
            print(f"  ✓ Personal agent profile linked to agent@migrantsafe.com [pending]")

        conn.commit()
        print("  ✓ Sample agents seeded.")
    else:
        print(f"  ⟳ Agents table already has {existing_agents} row(s). Skipping.")

    conn.close()
    print("\n✅ Database initialised successfully!")
    print("\nDemo login credentials:")
    print("  Migrant Worker   : worker@migrantsafe.com / Worker01")
    print("  Recruitment Agent: agent@migrantsafe.com  / Agent01")
    print("  Admin            : admin@migrantsafe.com  / Admin01")


if __name__ == '__main__':
    init_db()
