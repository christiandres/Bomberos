import time
import csv
import io
import json
import os
import sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY", "bomberos-lgsm-hidrantes-clave-segura-2026")
CLAVE_ACCESO = os.environ.get("APP_PASSWORD", "420600")


def requiere_login_vista(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if sesion_expirada():
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def requiere_login_api(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if sesion_expirada():
            return jsonify({"error": "Sesión expirada por inactividad"}), 401
        return f(*args, **kwargs)
    return decorated

TIEMPO_INACTIVIDAD_SEG = int(os.environ.get("SESSION_TIMEOUT_SEG", 120))  # 30 minutos por defecto


def sesion_expirada():
    if not session.get("autenticado"):
        return True
    ultima = session.get("ultima_actividad")
    ahora = time.time()
    if ultima is not None and (ahora - ultima) > TIEMPO_INACTIVIDAD_SEG:
        session.clear()
        return True
    session.permanent = True
    session["ultima_actividad"] = ahora
    return False

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("autenticado"):
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        clave_ingresada = (request.form.get("clave") or "").strip()
        if clave_ingresada == CLAVE_ACCESO:
            session["ultima_actividad"] = time.time()
            session.permanent = True
            session["autenticado"] = True
            return redirect(url_for("index"))
        error = "Contraseña incorrecta. Verificá e intentá de nuevo."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@requiere_login_vista
def index():
    return render_template("index.html")


DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = DATABASE_URL.startswith("postgres")

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras

DB_NAME = "/tmp/hidrantes.db" if os.environ.get("RENDER") else "hidrantes.db"


class DBWrapper:
    def __init__(self, conn, is_postgres):
        self.conn = conn
        self.is_postgres = is_postgres

    def _adapt_sql(self, sql):
        if self.is_postgres:
            return sql.replace("?", "%s")
        return sql

    def execute(self, sql, params=()):
        sql = self._adapt_sql(sql)
        if self.is_postgres:
            cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


def get_db():
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        return DBWrapper(conn, True)
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return DBWrapper(conn, False)


def init_db():
    db = get_db()
    if USE_POSTGRES:
        db.execute("""
            CREATE TABLE IF NOT EXISTS hidrantes (
                id SERIAL PRIMARY KEY,
                codigo TEXT,
                ubicacion TEXT NOT NULL,
                barrio TEXT,
                lat DOUBLE PRECISION NOT NULL,
                lng DOUBLE PRECISION NOT NULL,
                tipo TEXT DEFAULT 'Columna',
                estado TEXT DEFAULT 'operativo',
                observaciones TEXT,
                ultima_revision TEXT,
                revisado_por TEXT
            )
        """)
    else:
        db.execute("""
            CREATE TABLE IF NOT EXISTS hidrantes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT,
                ubicacion TEXT NOT NULL,
                barrio TEXT,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                tipo TEXT DEFAULT 'Columna',
                estado TEXT DEFAULT 'operativo',
                observaciones TEXT,
                ultima_revision TEXT,
                revisado_por TEXT
            )
        """)

    cur = db.execute("SELECT COUNT(*) AS total FROM hidrantes")
    row = cur.fetchone()
    total = row["total"] if USE_POSTGRES else row[0]

    if total == 0:
        ejemplos = [
            (
                "H-001", "Av. Presidente Perón y San Martín (Plaza Central)", "Centro",
                -23.8065, -64.7876, "Columna", "operativo",
                "Buena presión, acceso despejado.", "2026-11-25", "Guardia"
            ),
            (
                "H-002", "Av. Libertad y Wollmann", "Centro",
                -23.8038, -64.7912, "Subterráneo", "observacion",
                "Tapa pesada, llevar llave de cuadro y barreta.", "2026-11-25", "Guardia"
            ),
            (
                "H-003", "Av. Antártida Argentina y Jujuy", "Ledesma",
                -23.8115, -64.7845, "Columna", "fuera_servicio",
                "Vástago trabado / sin agua. Reclamo pendiente.", "2026-11-25", "Guardia"
            )
        ]
        for item in ejemplos:
            db.execute("""
                INSERT INTO hidrantes
                (codigo, ubicacion, barrio, lat, lng, tipo, estado, observaciones, ultima_revision, revisado_por)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, item)

    db.commit()
    db.close()


# Se ejecuta siempre al iniciar (incluyendo Gunicorn en Render)
init_db()


@app.route("/api/hidrantes", methods=["GET"])
@requiere_login_api
def listar_hidrantes():
    db = get_db()
    rows = db.execute("SELECT * FROM hidrantes ORDER BY id DESC").fetchall()
    db.close()
    return jsonify([dict(row) for row in rows])


@app.route("/api/proximo-codigo", methods=["GET"])
@requiere_login_api
def proximo_codigo():
    db = get_db()
    rows = db.execute("SELECT codigo FROM hidrantes WHERE codigo IS NOT NULL AND codigo != ''").fetchall()
    db.close()

    max_num = 0
    for row in rows:
        cod = (row["codigo"] or "").strip().upper()
        if cod.startswith("H-"):
            parte_num = cod[2:].strip()
            if parte_num.isdigit():
                num = int(parte_num)
                if num > max_num:
                    max_num = num

    siguiente = f"H-{max_num + 1:03d}"
    return jsonify({"codigo": siguiente})


@app.route("/api/hidrantes", methods=["POST"])
@requiere_login_api
def crear_hidrante():
    data = request.json or {}
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")

    db = get_db()
    cur = db.execute("""
        INSERT INTO hidrantes
        (codigo, ubicacion, barrio, lat, lng, tipo, estado, observaciones, ultima_revision, revisado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("codigo", "").strip(),
        data.get("ubicacion", "").strip(),
        data.get("barrio", "").strip(),
        float(data["lat"]),
        float(data["lng"]),
        data.get("tipo", "Columna"),
        data.get("estado", "operativo"),
        data.get("observaciones", "").strip(),
        fecha_hoy,
        data.get("revisado_por", "Personal Activo").strip()
    ))
    nuevo_id = None
    if not USE_POSTGRES:
        nuevo_id = cur.lastrowid
    db.commit()
    db.close()
    return jsonify({"status": "ok", "id": nuevo_id}), 201


@app.route("/api/hidrantes/<int:id>", methods=["PUT"])
@requiere_login_api
def actualizar_hidrante(id):
    data = request.json or {}
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")

    db = get_db()
    db.execute("""
        UPDATE hidrantes SET
            codigo = ?,
            ubicacion = ?,
            barrio = ?,
            tipo = ?,
            estado = ?,
            observaciones = ?,
            ultima_revision = ?,
            revisado_por = ?
        WHERE id = ?
    """, (
        data.get("codigo", "").strip(),
        data.get("ubicacion", "").strip(),
        data.get("barrio", "").strip(),
        data.get("tipo", "Columna"),
        data.get("estado", "operativo"),
        data.get("observaciones", "").strip(),
        fecha_hoy,
        data.get("revisado_por", "").strip(),
        id
    ))
    db.commit()
    db.close()
    return jsonify({"status": "ok"})


@app.route("/api/hidrantes/<int:id>/estado", methods=["PATCH"])
@requiere_login_api
def cambio_rapido_estado(id):
    data = request.json or {}
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    db = get_db()
    db.execute(
        "UPDATE hidrantes SET estado = ?, ultima_revision = ? WHERE id = ?",
        (data["estado"], fecha_hoy, id)
    )
    db.commit()
    db.close()
    return jsonify({"status": "ok"})


@app.route("/api/hidrantes/<int:id>", methods=["DELETE"])
@requiere_login_api
def eliminar_hidrante(id):
    db = get_db()
    db.execute("DELETE FROM hidrantes WHERE id = ?", (id,))
    db.commit()
    db.close()
    return jsonify({"status": "ok"})


@app.route("/api/exportar", methods=["GET"])
@requiere_login_api
def exportar_hidrantes():
    formato = request.args.get("formato", "json").lower()
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")

    db = get_db()
    rows = db.execute("SELECT * FROM hidrantes ORDER BY id ASC").fetchall()
    db.close()

    datos = [dict(row) for row in rows]

    if formato == "csv":
        output = io.StringIO()
        campos = [
            "id", "codigo", "ubicacion", "barrio", "lat", "lng",
            "tipo", "estado", "observaciones", "ultima_revision", "revisado_por"
        ]
        writer = csv.DictWriter(output, fieldnames=campos, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(datos)

        return Response(
            output.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename=hidrantes_lgsm_{fecha_hoy}.csv"
            }
        )

    return Response(
        json.dumps(datos, indent=2, ensure_ascii=False),
        mimetype="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=hidrantes_lgsm_{fecha_hoy}.json"
        }
    )




if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
