"""
migrate.py — Railway PostgreSQL migration
Removes UNIQUE constraints on room and email,
adds combined UNIQUE (first_name, last_name, email).

Run once on Railway:
  railway run python migrate.py
"""

import psycopg2, os, sys

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not DATABASE_URL:
    print("❌  DATABASE_URL not set. Run this via: railway run python migrate.py")
    sys.exit(1)

steps = [
    # 1. Drop UNIQUE on room (constraint name may vary — try both common names)
    ("Drop UNIQUE on room (name variant 1)",
     "ALTER TABLE registrations DROP CONSTRAINT IF EXISTS registrations_room_key;"),

    ("Drop UNIQUE on room (name variant 2)",
     "ALTER TABLE registrations DROP CONSTRAINT IF EXISTS unique_room;"),

    # 2. Drop UNIQUE on email (constraint name may vary)
    ("Drop UNIQUE on email (name variant 1)",
     "ALTER TABLE registrations DROP CONSTRAINT IF EXISTS registrations_email_key;"),

    ("Drop UNIQUE on email (name variant 2)",
     "ALTER TABLE registrations DROP CONSTRAINT IF EXISTS unique_email;"),

    # 3. Add combined UNIQUE (first_name, last_name, email)
    ("Add UNIQUE (first_name, last_name, email)",
     "ALTER TABLE registrations ADD CONSTRAINT unique_guest UNIQUE (first_name, last_name, email);"),
]

try:
    con = psycopg2.connect(DATABASE_URL)
    con.autocommit = False
    cur = con.cursor()

    for label, sql in steps:
        try:
            cur.execute(sql)
            print(f"✅  {label}")
        except psycopg2.Error as e:
            # Non-fatal: constraint didn't exist or already applied
            print(f"⚠️   {label} — skipped ({e.pgerror.strip()})")
            con.rollback()
            cur = con.cursor()

    con.commit()
    cur.close()
    con.close()
    print("\n✅  Migration complete.")

except psycopg2.Error as e:
    print(f"\n❌  Connection error: {e}")
    sys.exit(1)
