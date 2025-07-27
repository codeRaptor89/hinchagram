import eventlet
eventlet.monkey_patch() 

from flask import Flask, render_template, request, url_for, redirect, session, jsonify
import json
import os
import time
import asyncio
from interceptar_m3u8 import capturar_m3u8
from datetime import datetime
from collections import defaultdict
import mysql.connector
import locale
import atexit
from playwright_manager import init_browser, close_browser
from flask_socketio import SocketIO, emit, join_room
from db_config_chat import get_connection

# Crear un nuevo event loop de asyncio y establecerlo como el actual
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Inicializar Playwright (abrir navegador) antes de iniciar Flask
loop.run_until_complete(init_browser())

# Registrar una función para cerrar Playwright cuando la app termine
atexit.register(lambda: loop.run_until_complete(close_browser()))

app = Flask(__name__, static_folder="templates")
socketio = SocketIO(app)

def get_user_by_ip(ip):
    conn = get_connection()
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT * FROM chat_users WHERE ip = %s", (ip,))
        user = cursor.fetchone()

    return user

def create_user(name, ip, timestamp):
    conn = get_connection()
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute("INSERT INTO chat_users (nombre, ip, timestamp) VALUES (%s, %s, %s)", (name, ip, timestamp))
        conn.commit()

from datetime import datetime

@app.route('/api/registrar_nombre', methods=['POST'])
def api_registrar_nombre():
    user_ip = request.remote_addr
    user = get_user_by_ip(user_ip)

    # Si el usuario ya está registrado
    if user:
        today = datetime.now().date()  # Obtener la fecha de hoy
        # Verificar si el usuario ya cambió su nombre hoy
        if user['timestamp'].date() == today:
            return {'status': 'ya_registrado', 'mensaje': 'Ya has cambiado tu nombre hoy.'}
        else:
            # Si el nombre puede ser cambiado, actualizamos el nombre
            data = request.get_json()
            nombre = data.get('nombre', '').strip()

            if not nombre:
                return {'status': 'error', 'mensaje': 'Nombre vacío'}, 400

            # Actualizar el nombre del usuario
            update_user_name(user['id'], nombre)
            return {'status': 'ok'}

    # Si el usuario no está registrado, lo registramos por primera vez
    data = request.get_json()
    nombre = data.get('nombre', '').strip()

    if not nombre:
        return {'status': 'error', 'mensaje': 'Nombre vacío'}, 400

    now = datetime.now()  # Capturar fecha y hora actual
    # Crear un nuevo usuario
    create_user(nombre, user_ip, now)
    return {'status': 'ok'}

def update_user_name(user_id, new_name):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("UPDATE chat_users SET nombre = %s WHERE id = %s", (new_name, user_id))
        conn.commit()
    cursor.close()
    conn.close()



@socketio.on('join')
def on_join(data):
    join_room(data['event_id'])

@socketio.on('message')
def handle_message(data):
    try:
        # Obtener la IP del usuario
        user_ip = request.remote_addr
        user = get_user_by_ip(user_ip)

        if not user:
            print(f"No se encontró usuario con la IP {user_ip}")
            return

        mensaje = data['message']
        event_id = data['event_id']

        # Guardar mensaje en la base de datos
        conn = get_connection()
        user_id = user['id']  
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                "INSERT INTO mensajes (usuario_id, evento_id, mensaje) VALUES (%s, %s, %s)",
                (user_id, event_id, mensaje)
            )
            conn.commit()  # Asegurarse de guardar los cambios

        cursor.close()
        conn.close()

        # Emitir el mensaje a todos los usuarios conectados al evento
        emit('message', {
            'user': user['nombre'],
            'message': mensaje,
            'event_id': event_id  # Este es crucial para que el mensaje llegue solo a los clientes correctos
        }, to=event_id)  # Emitir a todos los clientes escuchando este evento

    except Exception as e:
        print(f"Error al manejar el mensaje: {str(e)}")
        # Aquí puedes decidir cómo manejar el error, por ejemplo, mostrar un mensaje a los usuarios.


# Configurar localización para fechas en español
locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')

# Clave secreta para sesiones Flask (se genera aleatoria)
app.secret_key = os.urandom(24)

# Tiempo de expiración para caché en segundos (1 minuto para pruebas)
CACHE_EXPIRATION = 60 * 60

# Crear carpeta 'cache' si no existe para almacenar archivos JSON
if not os.path.exists("cache"):
    os.makedirs("cache")

# Función para verificar si el token de caché expiró para partidos
def token_expirado():
    canal_nombre = session.get('canal_nombre')
    filename = f"cache/{canal_nombre}.json"
    if not os.path.exists(filename):
        return True
    try:
        with open(filename, "r") as f:
            data = json.load(f)
            timestamp = data.get("timestamp", 0)
            # Compara el tiempo actual con timestamp guardado
            return time.time() - timestamp > CACHE_EXPIRATION
    except json.JSONDecodeError:
        return True

# Función similar para verificar expiración de token para canales normales
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

# Manejador de error 404: redirige siempre al index
@app.errorhandler(404)
def not_found(error):
    return redirect(url_for('index'))

# Ruta principal (index) que muestra los eventos del día
@app.route("/")
def index():
    # Marcar usuario como "logueado" para permitir acceso
    session['logged_in'] = True

    fecha_actual = datetime.now()
    dia_actual = 8  # Hardcodeado (podrías usar fecha_actual.day si quieres)
    mes_actual = fecha_actual.month
    anio_actual = fecha_actual.year

    # Conectar a la base de datos MySQL
    conexion = mysql.connector.connect(
        host="miappdb.c7u6giqeygpc.us-east-2.rds.amazonaws.com",  # punto de enlace RDS
        user="admin",
        password="Lunita1808",
        database='futbol',
        charset='utf8mb4',
        port=3306  # puerto de MySQL, aunque mysql.connector lo pone por defecto
    )
    cursor = conexion.cursor(dictionary=True)

    # Consultar eventos y canales para el día actual
    cursor.execute("""
        SELECT e.id AS evento_id, e.evento, c.nombre, c.url
        FROM eventos e
        JOIN evento_canal ec ON e.id = ec.id_evento
        JOIN canales c ON ec.id_canal = c.id
        WHERE e.dia = %s AND e.mes = %s AND e.anio = %s
    """, (dia_actual, mes_actual, anio_actual))

    filas = cursor.fetchall()

    # Agrupar resultados por evento con sus canales asociados
    eventos_dict = defaultdict(lambda: {"evento": "", "canales": []})
    for fila in filas:
        evento_id = fila["evento_id"]
        eventos_dict[evento_id]["evento"] = fila["evento"]
        eventos_dict[evento_id]["canales"].append({
            "nombre_canal": fila["nombre"],
            "url": fila["url"]
        })

    # Convertir dict a lista para pasar al template
    resultado_final = [
        {"id": eid, "evento": datos["evento"], "canales": datos["canales"]}
        for eid, datos in eventos_dict.items()
    ]

    # Obtener lista completa de canales
    cursor.execute("SELECT * FROM canales")
    canales = cursor.fetchall()

    # Obtener IP del usuario y verificar si ya tiene un nombre registrado
    user_ip = request.remote_addr
    cursor.execute("SELECT nombre FROM chat_users WHERE ip = %s", (user_ip,))
    user = cursor.fetchone()

    if user:
        session['username'] = user['nombre']  # Guardar nombre en la sesión

    cursor.close()
    conexion.close()

    # Renderizar plantilla index.html con datos
    return render_template("sitio/index.html", fecha_actual=fecha_actual, partidos=resultado_final, canal=canales)

# Ruta para ver un partido y capturar stream m3u8
@app.route('/verPartido', methods=['GET', 'POST'])
def verPartido():
    if not session.get('logged_in'):
        return redirect(url_for('index'))

    # Guardamos datos en la sesión si viene por POST
    if request.method == 'POST':
        canal_url = request.form.get('canal_url')
        canal_nombre = request.form.get('canal')
        nombre_evento = request.form.get('nombre_evento')
        event_id = request.form.get('evento_id')  # importante

        session['source_url'] = canal_url
        session['canal_nombre'] = canal_nombre.lower().replace(" ", "_") if canal_nombre else None
        session['nombre_evento'] = nombre_evento
        session['evento_id'] = event_id

    # Recuperamos de sesión
    canal_url = session.get('source_url')
    canal_nombre = session.get('canal_nombre')
    nombre_evento = session.get('nombre_evento')
    event_id = session.get('evento_id')

    if not canal_url or not canal_nombre or not event_id:
        return "Faltan parámetros", 400
    
    user_ip = request.remote_addr
    user = get_user_by_ip(user_ip)

        # Recuperar el usuario desde la sesión
    if user:
        username = user['nombre']  # Si el usuario está registrado, obtenemos su nombre
        last_changed = user['timestamp'].date()  # Fecha de último cambio de nombre
    else:
        username = None  # Si el usuario no está registrado, el valor será None
        last_changed = None


    # 🔁 Ya no capturamos m3u8 aquí
    return render_template("sitio/verPartido.html", 
        evento=nombre_evento,
        user=user,
        username=username,
        event_id=event_id,
        )


# API para obtener URL m3u8 del stream actual
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

# Ruta para ver un canal y mostrar imagen
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

# API para obtener URL m3u8 de canal normal
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


#obtiene los mensajes del eventos
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


if __name__ == "__main__":

    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)



