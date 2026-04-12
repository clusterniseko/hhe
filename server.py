from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2, psycopg2.extras, os

app = Flask(__name__)

# ── CORS: permite llamadas desde GitHub Pages ──────────────────────────
CORS(app, resources={r"/*": {"origins": "*"}})

# ── Conexión a PostgreSQL ──────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ── Contraseña admin (definida UNA sola vez) ───────────────────────────
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "HILTON2026")


def get_db():
    con = psycopg2.connect(DATABASE_URL)
    return con


def init_db():
    with get_db() as con:
        with con.cursor() as cur:
            # 1. Create table if it doesn't exist yet (new installs)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS registrations (
                    id          SERIAL PRIMARY KEY,
                    room        TEXT    NOT NULL,
                    first_name  TEXT    NOT NULL,
                    last_name   TEXT    NOT NULL,
                    email       TEXT    NOT NULL,
                    phone       TEXT,
                    country     TEXT,
                    zip         TEXT,
                    lang        TEXT    DEFAULT 'en',
                    ticket_used BOOLEAN DEFAULT FALSE,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 2. Drop the old combined constraint if it exists
            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'registrations_first_name_last_name_email_key'
                    ) THEN
                        ALTER TABLE registrations
                            DROP CONSTRAINT registrations_first_name_last_name_email_key;
                    END IF;
                END $$;
            """)

            # 3. Deduplicate by email — keep the row with the highest id (most recent)
            cur.execute("""
                DELETE FROM registrations
                WHERE id NOT IN (
                    SELECT MAX(id) FROM registrations GROUP BY email
                );
            """)

            # 4. Deduplicate by (first_name, last_name) — keep the most recent
            cur.execute("""
                DELETE FROM registrations
                WHERE id NOT IN (
                    SELECT MAX(id) FROM registrations GROUP BY first_name, last_name
                );
            """)

            # 5. Now safely add the two separate UNIQUE constraints
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'registrations_email_key'
                    ) THEN
                        ALTER TABLE registrations
                            ADD CONSTRAINT registrations_email_key UNIQUE (email);
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'registrations_first_name_last_name_key'
                    ) THEN
                        ALTER TABLE registrations
                            ADD CONSTRAINT registrations_first_name_last_name_key
                            UNIQUE (first_name, last_name);
                    END IF;
                END $$;
            """)
        con.commit()


# ── POST /register ─────────────────────────────────────────────────────
@app.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}

    room       = str(data.get("room", "")).strip()
    first_name = data.get("firstName", "").strip()
    last_name  = data.get("lastName", "").strip()
    email      = data.get("email", "").strip().lower()
    phone      = data.get("phone", "").strip()
    country    = data.get("country", "").strip()
    zip_code   = data.get("zip", "").strip()
    lang       = data.get("lang", "en").strip()

    if not room or not first_name or not last_name or not email:
        return jsonify({"error": "missing_fields"}), 400

    try:
        with get_db() as con:
            with con.cursor() as cur:
                # Check name duplicate
                cur.execute(
                    """SELECT id FROM registrations
                       WHERE first_name = %s AND last_name = %s""",
                    (first_name, last_name)
                )
                if cur.fetchone():
                    return jsonify({"error": "guest_already_registered", "field": "name"}), 409

                # Check email duplicate
                cur.execute(
                    "SELECT id FROM registrations WHERE email = %s",
                    (email,)
                )
                if cur.fetchone():
                    return jsonify({"error": "guest_already_registered", "field": "email"}), 409

                cur.execute(
                    """INSERT INTO registrations
                       (room, first_name, last_name, email, phone, country, zip, lang)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (room, first_name, last_name, email, phone, country, zip_code, lang)
                )
            con.commit()
    except psycopg2.errors.UniqueViolation as e:
        field = "email" if "email" in str(e) else "name"
        return jsonify({"error": "guest_already_registered", "field": field}), 409

    return jsonify({"success": True, "room": room}), 201


# ── GET /check-ticket ──────────────────────────────────────────────────
@app.route("/check-ticket", methods=["GET"])
def check_ticket():
    email  = request.args.get("email", "").strip().lower()
    nombre = request.args.get("nombre", "").strip()

    if not email and not nombre:
        return jsonify({"registered": False, "ticket_used": False})

    with get_db() as con:
        with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            row = None

            if email:
                cur.execute(
                    """SELECT first_name, last_name, ticket_used, created_at
                       FROM registrations WHERE email = %s""",
                    (email,)
                )
                row = cur.fetchone()

            if not row and nombre:
                parts = nombre.strip().split(" ", 1)
                first = parts[0] if len(parts) > 0 else ""
                last  = parts[1] if len(parts) > 1 else ""
                if first and last:
                    cur.execute(
                        """SELECT first_name, last_name, ticket_used, created_at
                           FROM registrations
                           WHERE first_name = %s AND last_name = %s""",
                        (first, last)
                    )
                    row = cur.fetchone()

    if not row:
        return jsonify({"registered": False, "ticket_used": False})

    return jsonify({
        "registered":  True,
        "ticket_used": bool(row["ticket_used"]),
        "name":        row["first_name"] + " " + row["last_name"],
        "at":          str(row["created_at"])
    })


# ── POST /use-ticket ───────────────────────────────────────────────────
@app.route("/use-ticket", methods=["POST"])
def use_ticket():
    data   = request.get_json(silent=True) or {}
    email  = data.get("email", "").strip().lower()
    nombre = data.get("nombre", "").strip()

    if not email and not nombre:
        return jsonify({"error": "missing_fields"}), 400

    with get_db() as con:
        with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            row = None

            if email:
                cur.execute(
                    "SELECT id, ticket_used FROM registrations WHERE email = %s",
                    (email,)
                )
                row = cur.fetchone()

            if not row and nombre:
                parts = nombre.strip().split(" ", 1)
                first = parts[0] if len(parts) > 0 else ""
                last  = parts[1] if len(parts) > 1 else ""
                if first and last:
                    cur.execute(
                        """SELECT id, ticket_used FROM registrations
                           WHERE first_name = %s AND last_name = %s""",
                        (first, last)
                    )
                    row = cur.fetchone()

            if not row:
                return jsonify({"error": "not_found"}), 404

            if row["ticket_used"]:
                return jsonify({"error": "already_used"}), 409

            cur.execute(
                "UPDATE registrations SET ticket_used = TRUE WHERE id = %s",
                (row["id"],)
            )
        con.commit()

    return jsonify({"success": True}), 200


# ── GET /registrations ─────────────────────────────────────────────────
@app.route("/registrations", methods=["GET"])
def list_all():
    with get_db() as con:
        with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT room, first_name, last_name, email, phone,
                          country, zip, lang, ticket_used, created_at
                   FROM registrations ORDER BY created_at DESC"""
            )
            rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])


# ── GET /admin/registrations ───────────────────────────────────────────
@app.route("/admin/registrations", methods=["GET"])
def admin_registrations():
    if request.args.get("password", "") != ADMIN_PASSWORD:
        return jsonify({"error": "unauthorized"}), 401

    with get_db() as con:
        with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT room, first_name, last_name, email, phone,
                          country, zip, lang, ticket_used, created_at
                   FROM registrations ORDER BY created_at DESC"""
            )
            rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])


# ── DELETE /admin/delete ──────────────────────────────────────────────
@app.route("/admin/delete", methods=["DELETE"])
def admin_delete():
    if request.args.get("password", "") != ADMIN_PASSWORD:
        return jsonify({"error": "unauthorized"}), 401

    data  = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()

    if not email:
        return jsonify({"error": "missing_email"}), 400

    with get_db() as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM registrations WHERE email = %s", (email,))
            deleted = cur.rowcount
        con.commit()

    if deleted == 0:
        return jsonify({"error": "not_found"}), 404

    return jsonify({"success": True, "deleted": deleted}), 200


# ── GET /health ────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ── Arranque ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# Gunicorn llama init_db() al importar el módulo
init_db()
