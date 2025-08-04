from flask import Flask, render_template, request, url_for, redirect, session, jsonify, Response, stream_with_context
from flask_socketio import SocketIO, emit, join_room
from flask_cors import CORS
from collections import defaultdict
from datetime import datetime
import json
import os
import time
import asyncio
import mysql.connector
import locale
import atexit
import requests
from interceptar_m3u8 import capturar_m3u8
from playwright_manager import init_browser, close_browser
from db_config_chat import get_connection

app = Flask(__name__, static_folder="templates")
app.secret_key = os.urandom(24)
CORS(app)
socketio = SocketIO(app, async_mode='threading')
locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')

CACHE_EXPIRATION = 60 * 60
if not os.path.exists("cache"):
    os.makedirs("cache")

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.run_until_complete(init_browser())
atexit.register(lambda: loop.run_until_complete(close_browser()))

def get_user_by_ip(ip):
    conn = get_connection()
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT * FROM chat_users WHERE ip = %s", (ip,))
        user = cursor.fetchone()
    conn.close()
    return user

def create_user(name, ip, timestamp):
    conn = get_connection()
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute("INSERT INTO chat_users (nombre, ip, timestamp) VALUES (%s, %s, %s)", (name, ip, timestamp))
        conn.commit()
    conn.close()

def update_user_name(user_id, new_name):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("UPDATE chat_users SET nombre = %s WHERE id = %s", (new_name, user_id))
        conn.commit()
    cursor.close()
    conn.close()

def token_expirado():
    canal_nombre = session.get('canal_nombre')
    filename = f"cache/{canal_nombre}.json"
    if not os.path.exists(filename):
        return True
    try:
        with open(filename, "r") as f:
            data = json.load(f)
            timestamp = data.get("timestamp", 0)
            return time.time() - timestamp > CACHE_EXPIRATION
    except json.JSONDecodeError:
        return True

def token_canal_normal_expirado():
    canal_nombre = session.get('nombre_canal')
    filename = f"cache/{canal_nombre}.json"
    if not os.path.exists(filename):
        return True
    try:
        with open(filename, "r") as f:
            data = json.load(f)
            timestamp = data.get("timestamp", 0)
            return time.time() - timestamp > CACHE_EXPIRATION
    except json.JSONDecodeError:
        return True

@app.route("/")
def index():
    session['logged_in'] = True
    fecha_actual = datetime.now()
    dia_actual = 8
    mes_actual = 7
    anio_actual = fecha_actual.year

    conexion = mysql.connector.connect(
        host="miappdb.c7u6giqeygpc.us-east-2.rds.amazonaws.com",
        user="admin",
        password="Lunita1808",
        database='futbol',
        charset='utf8mb4',
        port=3306
    )
    cursor = conexion.cursor(dictionary=True)

    cursor.execute("""
        SELECT e.id AS evento_id, e.evento, c.nombre, c.url
        FROM eventos e
        JOIN evento_canal ec ON e.id = ec.id_evento
        JOIN canales c ON ec.id_canal = c.id
        WHERE e.dia = %s AND e.mes = %s AND e.anio = %s
    """, (dia_actual, mes_actual, anio_actual))

    filas = cursor.fetchall()
    eventos_dict = defaultdict(lambda: {"evento": "", "canales": []})
    for fila in filas:
        evento_id = fila["evento_id"]
        eventos_dict[evento_id]["evento"] = fila["evento"]
        eventos_dict[evento_id]["canales"].append({
            "nombre_canal": fila["nombre"],
            "url": fila["url"]
        })

    resultado_final = [
        {"id": eid, "evento": datos["evento"], "canales": datos["canales"]}
        for eid, datos in eventos_dict.items()
    ]

    cursor.execute("SELECT * FROM canales")
    canales = cursor.fetchall()

    user_ip = request.remote_addr
    cursor.execute("SELECT nombre FROM chat_users WHERE ip = %s", (user_ip,))
    user = cursor.fetchone()
    if user:
        session['username'] = user['nombre']

    cursor.close()
    conexion.close()
    return render_template("sitio/index.html", fecha_actual=fecha_actual, partidos=resultado_final, canal=canales)

@app.route('/verPartido', methods=['GET', 'POST'])
def verPartido():
    if not session.get('logged_in'):
        return redirect(url_for('index'))

    if request.method == 'POST':
        canal_url = request.form.get('canal_url')
        canal_nombre = request.form.get('canal')
        nombre_evento = request.form.get('nombre_evento')
        event_id = request.form.get('evento_id')

        session['source_url'] = canal_url
        session['canal_nombre'] = canal_nombre.lower().replace(" ", "_") if canal_nombre else None
        session['nombre_evento'] = nombre_evento
        session['evento_id'] = event_id

    canal_url = session.get('source_url')
    canal_nombre = session.get('canal_nombre')
    nombre_evento = session.get('nombre_evento')
    event_id = session.get('evento_id')

    if not canal_url or not canal_nombre or not event_id:
        return "Faltan parámetros", 400

    user_ip = request.remote_addr
    user = get_user_by_ip(user_ip)
    username = user['nombre'] if user else None

    return render_template("sitio/verPartido.html",
        evento=nombre_evento,
        user=user,
        username=username,
        event_id=event_id,
    )

@app.route("/api/m3u8")
def obtener_m3u8():
    source_url = session.get('source_url')
    canal_nombre = session.get('canal_nombre')

    if not source_url:
        return {"error": "No se proporcionó URL"}, 400

    filename = f"cache/{canal_nombre}.json"

    if token_expirado() or not os.path.exists(filename):
        print("🔄 Token expirado o no existe. Renovando...")
        data = loop.run_until_complete(capturar_m3u8(source_url))
        if not data:
            return {"error": "❌ No se pudo capturar el stream"}, 500
        with open(filename, "w") as f:
            json.dump({**data, "timestamp": time.time()}, f)
    else:
        try:
            with open(filename, "r") as f:
                data = json.load(f)
                print("✅ Usando caché")
        except Exception as e:
            return {"error": f"❌ Error al leer caché: {e}"}, 500

    return {"url": data["url"]}

@app.route('/verCanal', methods=['GET', 'POST'])
def verCanal():
    if not session.get('logged_in'):
        return redirect(url_for('index'))

    if request.method == 'POST':
        canal_url = request.form.get('canal_url')
        canal_nombre = request.form.get('canal')
        canal_imagen = request.form.get('imagen')

        if canal_url and canal_nombre:
            session['url_canal'] = canal_url
            session['nombre_canal'] = canal_nombre.lower().replace(" ", "_")
            session['canal_imagen'] = canal_imagen

    canal_url = session.get('url_canal')
    canal_nombre = session.get('nombre_canal')
    canal_imagen = session.get('canal_imagen')

    if not canal_url or not canal_nombre:
        return "Faltan parámetros", 400

    return render_template("sitio/canal.html", imagen=canal_imagen)

@app.route("/canal_normal")
def obtener_canal_m3u8():
    canal_url = session.get('url_canal')
    canal_nombre = session.get('nombre_canal')

    if not canal_url:
        return {"error": "No se proporcionó URL"}, 400

    filename = f"cache/{canal_nombre}.json"

    if token_canal_normal_expirado() or not os.path.exists(filename):
        print("🔄 Token expirado o no existe. Renovando...")
        data = loop.run_until_complete(capturar_m3u8(canal_url))
        if not data:
            return {"error": "❌ No se pudo capturar el stream"}, 500
        with open(filename, "w") as f:
            json.dump({**data, "timestamp": time.time()}, f)
    else:
        try:
            with open(filename, "r") as f:
                data = json.load(f)
                print("✅ Usando caché")
        except Exception as e:
            return {"error": f"❌ Error al leer caché: {e}"}, 500

    return {"url": data["url"]}

@app.route("/api/mensajes")
def api_mensajes():
    evento_id = request.args.get('evento_id')
    if not evento_id:
        return jsonify({"error": "Falta evento_id"}), 400

    conn = get_connection()
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute("""
        SELECT m.mensaje, u.nombre
        FROM mensajes m
        LEFT JOIN chat_users u ON m.usuario_id = u.id
        WHERE m.evento_id = %s
        ORDER BY m.timestamp ASC
        LIMIT 100;
        """, (evento_id,))
        mensajes = cursor.fetchall()
    conn.close()
    return jsonify(mensajes)

@socketio.on('join')
def on_join(data):
    join_room(data['event_id'])

@socketio.on('mensaje')
def on_mensaje(data):
    user_ip = request.remote_addr
    user = get_user_by_ip(user_ip)
    user_id = user['id'] if user else None

    if not user_id:
        emit('error', {'msg': 'Usuario no encontrado'})
        return

    evento_id = data.get('event_id')
    mensaje = data.get('mensaje')

    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO mensajes (evento_id, usuario_id, mensaje, timestamp) VALUES (%s, %s, %s, NOW())",
                       (evento_id, user_id, mensaje))
        conn.commit()

    socketio.emit('nuevo_mensaje', {'mensaje': mensaje, 'usuario': user['nombre']}, room=evento_id)

@app.route('/proxy_stream')
def proxy_stream():
    canal_nombre = session.get("canal_nombre")
    if not canal_nombre:
        return {"error": "No se encontró el canal en la sesión"}, 400

    filename = f"cache/{canal_nombre}.json"
    if not os.path.exists(filename):
        return {"error": "No existe el archivo del canal"}, 404

    with open(filename, "r") as f:
        data = json.load(f)

    m3u8_url = data.get("url")
    headers = data.get("headers", {})

    if not m3u8_url:
        return {"error": "URL .m3u8 no válida"}, 500

    try:
        res = requests.get(m3u8_url, headers=headers, timeout=10)
        content = res.text

        # Reescribir URLs absolutas o relativas de segmentos a /proxy_ts
        base_url = m3u8_url.rsplit("/", 1)[0]
        modified_lines = []
        for line in content.splitlines():
            if line.strip().endswith(".ts"):
                if line.startswith("http"):
                    full_url = line
                else:
                    full_url = f"{base_url}/{line}"
                line = f"/proxy_ts?segment={full_url}"
            modified_lines.append(line)

        return Response("\n".join(modified_lines), content_type="application/vnd.apple.mpegurl")
    except Exception as e:
        return {"error": str(e)}, 500

@app.route("/proxy_ts")
def proxy_ts():
    segment_url = request.args.get("segment")
    canal_nombre = session.get("canal_nombre")
    if not segment_url or not canal_nombre:
        return {"error": "Datos faltantes"}, 400

    filename = f"cache/{canal_nombre}.json"
    if not os.path.exists(filename):
        return {"error": "Stream no encontrado"}, 404

    with open(filename, "r") as f:
        data = json.load(f)
    
    headers = data.get("headers", {})
    try:
        r = requests.get(segment_url, headers=headers, stream=True, timeout=10)
        return Response(stream_with_context(r.iter_content(1024)), content_type=r.headers.get("Content-Type"))
    except Exception as e:
        return {"error": str(e)}, 500


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
