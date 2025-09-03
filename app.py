from flask import Flask, render_template, request, url_for, redirect, session, jsonify
from flask_socketio import SocketIO, emit, join_room
from collections import defaultdict
from datetime import datetime
import os
import mysql.connector
import locale
from db_config_chat import get_connection
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
load_dotenv()
from itsdangerous import URLSafeSerializer

# Usa una clave secreta (mantén esto en secreto en producción)
SECRET_KEY = 'mi_clave_ultra_secreta'

serializer = URLSafeSerializer(SECRET_KEY)


app = Flask(__name__, static_folder="templates")
app.secret_key = os.urandom(24)
socketio = SocketIO(app, async_mode='eventlet')
locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
# Agrega ProxyFix indicando 1 proxy delante (Nginx)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

def generar_token(event_id, canal_nombre):
    """
    Genera un token único a partir del ID del evento y el nombre del canal.
    """
    data = {
        'event_id': str(event_id),
        'canal_nombre': canal_nombre.lower().replace(" ", "_")
    }
    return serializer.dumps(data)

def obtener_datos_desde_token(token):
    """
    Decodifica el token para obtener el diccionario con event_id y canal_nombre.
    """
    return serializer.loads(token)

def get_user_by_ip(ip):
    conn = get_connection()
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT * FROM chat_users WHERE ip = %s", (ip,))
        user = cursor.fetchone()
    conn.close()
    return user

@app.route("/verip")
def ver_ip():
    return f"IP del cliente es: {request.remote_addr}"


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


@app.route('/verPartido', methods=['POST'])
def verPartido():
    if not session.get('logged_in'):
        return redirect(url_for('index'))

    canal_url = request.form.get('canal_url')
    canal_nombre = request.form.get('canal')
    nombre_evento = request.form.get('nombre_evento')
    event_id = request.form.get('evento_id')

    # Guardar en sesión
    session['source_url'] = canal_url
    session['canal_nombre'] = canal_nombre.lower().replace(" ", "_") if canal_nombre else None
    session['nombre_evento'] = nombre_evento
    session['evento_id'] = event_id

    # ✅ Generar token único por evento y canal
    token = generar_token(event_id, canal_nombre)

    # Redirigir a la ruta con token
    return redirect(url_for('ver_evento', token=token))

@app.route('/evento/<token>')
def ver_evento(token):
    if not session.get('logged_in'):
        return redirect(url_for('index'))

    try:
        datos = obtener_datos_desde_token(token)
        event_id = datos['event_id']
        canal_nombre = datos['canal_nombre']
    except Exception:
        return "Token inválido o alterado", 400

    canal_url = session.get('source_url')
    nombre_evento = session.get('nombre_evento')

    if not canal_url or not event_id or not nombre_evento:
        return "Faltan datos", 400
    
    
    # Incrementar la vista aquí
    incrementar_vista(event_id)

    user_ip = request.remote_addr
    user = get_user_by_ip(user_ip)
    username = user['nombre'] if user else None

    return render_template("sitio/verPartido.html",
        evento=nombre_evento,
        user=user,
        username=username,
        event_id=event_id,
        canal_url=canal_url,
        canal_nombre=canal_nombre  # lo puedes usar en el template
    )

#aumenta vistas cada vez que un usuario abre un EVENTO
def incrementar_vista(event_id):
    conexion = mysql.connector.connect(
        host=os.environ.get("DB_HOST"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        database=os.environ.get("DB_NAME"),
        charset='utf8mb4',
        port=int(os.environ.get("DB_PORT", 3306))
    )
    cursor = conexion.cursor()

    try:
        sql = "UPDATE eventos SET vistas = vistas + 1 WHERE id = %s"
        cursor.execute(sql, (event_id,))
        conexion.commit()
    except mysql.connector.Error as err:
        print(f"Error al actualizar vistas: {err}")
    finally:
        cursor.close()
        conexion.close()

#aumenta vistas cada vez que un usuario abre un CANAL
def incrementar_vista_Canal(nombre_canal):
    conexion = mysql.connector.connect(
        host=os.environ.get("DB_HOST"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        database=os.environ.get("DB_NAME"),
        charset='utf8mb4',
        port=int(os.environ.get("DB_PORT", 3306))
    )
    cursor = conexion.cursor()

    try:
        sql = "UPDATE canales SET vistas = vistas + 1 WHERE nombre = %s"
        cursor.execute(sql, (nombre_canal,))
        conexion.commit()
    except mysql.connector.Error as err:
        print(f"Error al actualizar vistas: {err}")
    finally:
        cursor.close()
        conexion.close()


@app.route('/verCanal', methods=['POST'])
def verCanal():
    if not session.get('logged_in'):
        return redirect(url_for('index'))

    # Recuperar datos del formulario POST
    canal_url = request.form.get('canal_url')
    canal_nombre = request.form.get('canal')
    canal_imagen = request.form.get('imagen')

    if not canal_url or not canal_nombre:
        return "Faltan parámetros", 400

        # Incrementar la vista aquí
    incrementar_vista_Canal(canal_nombre)

    # Convertir el nombre del canal a slug para la URL
    slug = canal_nombre.lower().replace(" ", "_")

    # Guardar los datos en sesión
    session['url_canal'] = canal_url
    session['nombre_canal'] = slug
    session['canal_imagen'] = canal_imagen

    # Redirigir a la ruta con el canal como parte de la URL
    return redirect(url_for('mostrar_canal', canal_nombre=slug))

@app.route('/verCanal/<canal_nombre>', methods=['GET'])
def mostrar_canal(canal_nombre):
    if not session.get('logged_in'):
        return redirect(url_for('index'))

    # Obtener datos guardados en sesión
    canal_url = session.get('url_canal')
    canal_imagen = session.get('canal_imagen')
    canal_slug = session.get('nombre_canal')

    # Validar que la URL y el slug coincidan
    if canal_nombre != canal_slug or not canal_url:
        return "Datos no válidos", 400
    

    # Renderizar plantilla con los datos
    return render_template("sitio/canal.html",
                           canal_url=canal_url,
                           imagen=canal_imagen,
                           canal_nombre=canal_nombre)



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
