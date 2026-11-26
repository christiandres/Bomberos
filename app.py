import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
DB_NAME = "hidrantes.db"

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
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
    
    cursor.execute("SELECT COUNT(*) FROM hidrantes")
    if cursor.fetchone()[0] == 0:
        ejemplos = [
            (
                "H-001", "Av. Presidente Perón y San Martín (Plaza Central)", "Centro",
                -23.8065, -64.7876, "Columna", "operativo",
                "Buena presión, acceso despejado.", "2026-11-22", "Guardia"
            ),
            (
                "H-002", "Av. Libertad y Wollmann", "Centro",
                -23.8038, -64.7912, "Subterráneo", "observacion",
                "Tapa pesada, llevar llave de cuadro y barreta.", "2026-11-22", "Guardia"
            ),
            (
                "H-003", "Av. Antártida Argentina y Jujuy", "Ledesma",
                -23.8115, -64.7845, "Columna", "fuera_servicio",
                "Vástago trabado / sin agua. Reclamo pendiente.", "2026-11-22", "Guardia"
            )
        ]
        cursor.executemany("""
            INSERT INTO hidrantes 
            (codigo, ubicacion, barrio, lat, lng, tipo, estado, observaciones, ultima_revision, revisado_por)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ejemplos)
    
    conn.commit()
    conn.close()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/hidrantes", methods=["GET"])
def listar_hidrantes():
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM hidrantes ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])

@app.route("/api/hidrantes", methods=["POST"])
def crear_hidrante():
    data = request.json
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
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
    conn.commit()
    nuevo_id = cursor.lastrowid
    conn.close()
    return jsonify({"status": "ok", "id": nuevo_id}), 201

@app.route("/api/hidrantes/<int:id>", methods=["PUT"])
def actualizar_hidrante(id):
    data = request.json
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    
    conn = get_db_connection()
    conn.execute("""
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
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/api/hidrantes/<int:id>/estado", methods=["PATCH"])
def cambio_rapido_estado(id):
    data = request.json
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    conn = get_db_connection()
    conn.execute(
        "UPDATE hidrantes SET estado = ?, ultima_revision = ? WHERE id = ?",
        (data["estado"], fecha_hoy, id)
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/api/hidrantes/<int:id>", methods=["DELETE"])
def eliminar_hidrante(id):
    conn = get_db_connection()
    conn.execute("DELETE FROM hidrantes WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/api/proximo-codigo", methods=["GET"])
def proximo_codigo():
    conn = get_db_connection()
    rows = conn.execute("SELECT codigo FROM hidrantes WHERE codigo IS NOT NULL AND codigo != ''").fetchall()
    conn.close()

    max_num = 0
    for row in rows:
        cod = row["codigo"].strip().upper()
        if cod.startswith("H-"):
            parte_num = cod[2:].strip()
            if parte_num.isdigit():
                num = int(parte_num)
                if num > max_num:
                    max_num = num

    siguiente = f"H-{max_num + 1:03d}"
    return jsonify({"codigo": siguiente})



if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000, ssl_context="adhoc")
