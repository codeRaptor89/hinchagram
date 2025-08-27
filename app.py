from flask import Flask, render_template, request, url_for, redirect, session, jsonify
from flask_socketio import SocketIO, emit, join_room
from collections import defaultdict
from datetime import datetime
import os
import mysql.connector
import locale
from db_config_chat import get_connection
from dotenv import load_dotenv
load_dotenv()


app = Flask(__name__, static_folder="templates")
app.secret_key = os.urandom(24)
socketio = SocketIO(app, async_mode='eventlet')
locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')


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


@app.route("/")
def index():
    session['logged_in'] = True
    fecha_actual = datetime.now()
    dia_actual = 8
    mes_actual = 7
    anio_actual = fecha_actual.year

    conexion = mysql.connector.connect(
        host=os.environ.get("DB_HOST"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        database=os.environ.get("DB_NAME"),
        charset='utf8mb4',
        port=int(os.environ.get("DB_PORT", 3306))
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

    user_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    cursor.execute("SELECT nombre FROM chat_users WHERE ip = %s", (user_ip,))
    user = cursor.fetchone()
    #print(user)
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
    nombre_evento = session.get('nombre_evento')
    event_id = session.get('evento_id')

    if not canal_url or not event_id:
        return "Faltan parámetros", 400

    user_ip = request.remote_addr
    user = get_user_by_ip(user_ip)
    username = user['nombre'] if user else None
    #print(username)

    return render_template("sitio/verPartido.html",
        evento=nombre_evento,
        user=user,
        username=username,
        event_id=event_id,
        canal_url=canal_url
    )


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
    canal_imagen = session.get('canal_imagen')

    if not canal_url:
        return "Faltan parámetros", 400

    return render_template("sitio/canal.html", imagen=canal_imagen, canal_url=canal_url)


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
        ORDER BY m.timestamp DESC
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
    print(f"IP del usuario: {user_ip}")
    print(f"Usuario obtenido: {user}")

    user_id = user['id'] if user else None
    if not user_id:
        emit('error', {'msg': 'Usuario no encontrado'})
        print("No se encontró usuario para la IP")
        return

    evento_id = data.get('event_id')
    mensaje = data.get('mensaje')

    print(f"Evento ID recibido: {evento_id}")
    print(f"Mensaje recibido: {mensaje}")

    if not evento_id or not mensaje:
        emit('error', {'msg': 'Faltan datos: evento_id o mensaje'})
        print("Faltan datos para insertar el mensaje")
        return

    fecha_actual = datetime.now()  # 2. Obtener la fecha y hora actual

    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO mensajes (evento_id, usuario_id, mensaje, timestamp) VALUES (%s, %s, %s, %s)",
                (evento_id, user_id, mensaje, fecha_actual)
            )
            conn.commit()
        print("Mensaje insertado correctamente en la base de datos")
    except Exception as e:
        print(f"Error al insertar el mensaje en la base de datos: {e}")
        emit('error', {'msg': 'Error al guardar el mensaje'})
        return

    socketio.emit('nuevo_mensaje', {'mensaje': mensaje, 'usuario': user['nombre']}, room=evento_id)

from flask import jsonify, request
from datetime import datetime, timedelta

@app.route("/api/registrar_nombre", methods=["POST"])
def registrar_nombre():
    data = request.get_json()
    nombre = data.get("nombre", "").strip()
    user_ip = request.remote_addr

    if not nombre:
        return jsonify({"status": "error", "mensaje": "El nombre no puede estar vacío"}), 400

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Verifica si el nombre ya existe para otro usuario
        cursor.execute("SELECT * FROM chat_users WHERE nombre = %s AND ip != %s", (nombre, user_ip))
        nombre_existente = cursor.fetchone()
        if nombre_existente:
            return jsonify({"status": "error", "mensaje": "Este nombre ya está en uso por otro usuario"}), 400

        # Obtiene el usuario actual por IP
        cursor.execute("SELECT * FROM chat_users WHERE ip = %s", (user_ip,))
        user = cursor.fetchone()

        hoy = datetime.now().date()

        if user:
            # Ya hay usuario registrado. Verifica si cambió nombre hoy.
            timestamp = user["timestamp"]
            if timestamp.date() == hoy:
                return jsonify({"status": "error", "mensaje": "Ya cambiaste tu nombre hoy"}), 400

            # Actualiza nombre y timestamp
            cursor.execute("UPDATE chat_users SET nombre = %s, timestamp = %s WHERE id = %s",
                           (nombre, datetime.now(), user["id"]))
        else:
            # Nuevo usuario
            cursor.execute("INSERT INTO chat_users (nombre, ip, timestamp) VALUES (%s, %s, %s)",
                           (nombre, user_ip, datetime.now()))

        conn.commit()
        session['username'] = nombre

        return jsonify({"status": "ok"})

    except Exception as e:
        print(f"Error al registrar nombre: {e}")
        return jsonify({"status": "error", "mensaje": "Fallo al registrar nombre"}), 500
    finally:
        cursor.close()
        conn.close()



if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
