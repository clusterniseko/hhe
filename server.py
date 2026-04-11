from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3, os

app = Flask(__name__)

# ── CORS: permite llamadas desde GitHub Pages ──────────────────────────
# Cambia el origen por tu URL real de GitHub Pages
# Ejemplo: "https://tuusuario.github.io"
CORS(app, origins=["https://TU-USUARIO.github.io", "http://localhost"])

DB = "registrations.db"


def get_db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with get_db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS registrations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                room        TEXT    NOT NULL UNIQUE,
                first_name  TEXT    NOT NULL,
                last_name   TEXT    NOT NULL,
                email       TEXT    NOT NULL,
                phone       TEXT,
                country     TEXT,
                zip         TEXT,
                lang        TEXT    DEFAULT 'en',
                ticket_used INTEGER DEFAULT 0,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


# ── POST /register ─────────────────────────────────────────────────────
# Recibe los datos del formulario (index.html) y los guarda en la DB
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

    with get_db() as con:
        existing = con.execute(
            "SELECT id FROM registrations WHERE room = ?", (room,)
        ).fetchone()

        if existing:
            return jsonify({"error": "room_already_registered"}), 409

        con.execute(
            """INSERT INTO registrations
               (room, first_name, last_name, email, phone, country, zip, lang)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (room, first_name, last_name, email, phone, country, zip_code, lang)
        )

    return jsonify({"success": True, "room": room}), 201


# ── GET /check-ticket ─────────────────────────────────────────────────
# ticket.html lo llama al cargar para saber si el ticket ya fue usado
# Identifica al huésped por email + nombre (no por room)
@app.route("/check-ticket", methods=["GET"])
def check_ticket():
    email  = request.args.get("email", "").strip().lower()
    nombre = request.args.get("nombre", "").strip()

    if not email:
        return jsonify({"registered": False, "ticket_used": False})

    with get_db() as con:
        row = con.execute(
            """SELECT first_name, last_name, ticket_used, created_at
               FROM registrations
               WHERE email = ?""",
            (email,)
        ).fetchone()

    if not row:
        return jsonify({"registered": False, "ticket_used": False})

    return jsonify({
        "registered":  True,
        "ticket_used": bool(row["ticket_used"]),
        "name":        row["first_name"] + " " + row["last_name"],
        "at":          row["created_at"]
    })


# ── POST /use-ticket ───────────────────────────────────────────────────
# ticket.html lo llama al hacer doble click para marcar el ticket como usado
# Identifica al huésped por email + nombre (no por room)
@app.route("/use-ticket", methods=["POST"])
def use_ticket():
    data   = request.get_json(silent=True) or {}
    email  = data.get("email", "").strip().lower()
    nombre = data.get("nombre", "").strip()

    if not email:
        return jsonify({"error": "missing_email"}), 400

    with get_db() as con:
        row = con.execute(
            "SELECT id, ticket_used FROM registrations WHERE email = ?",
            (email,)
        ).fetchone()

        if not row:
            return jsonify({"error": "not_found"}), 404

        if row["ticket_used"]:
            return jsonify({"error": "already_used"}), 409

        con.execute(
            "UPDATE registrations SET ticket_used = 1 WHERE email = ?",
            (email,)
        )

    return jsonify({"success": True}), 200


# ── GET /registrations ─────────────────────────────────────────────────
# Panel de administración — lista todos los registros
@app.route("/registrations", methods=["GET"])
def list_all():
    with get_db() as con:
        rows = con.execute(
            """SELECT room, first_name, last_name, email, phone,
                      country, zip, lang, ticket_used, created_at
               FROM registrations ORDER BY created_at DESC"""
        ).fetchall()

    return jsonify([dict(r) for r in rows])


# ── GET /health ────────────────────────────────────────────────────────
# Railway usa este endpoint para verificar que el servicio está vivo
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
