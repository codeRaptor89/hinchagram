# capturar_m3u8.py
import json
import time
import asyncio
from playwright_manager import get_new_page

async def capturar_m3u8(url):
    """
    Función asíncrona que abre una página web con Playwright y captura la URL del
    stream .m3u8 junto con sus cabeceras HTTP.

    Args:
        url (str): La URL de la página donde se intentará capturar el stream .m3u8.

    Returns:
        dict o None: Retorna un diccionario con la URL del .m3u8, los headers HTTP
        usados y un timestamp si se captura exitosamente. Si no se captura, retorna None.
    """
    # Crear una nueva página de navegador
    page = await get_new_page()

    # Variables para almacenar la URL y cabeceras del .m3u8 cuando se detecten
    m3u8_url = None
    headers = {}

    # Función que se ejecuta en cada solicitud que hace la página
    async def on_request(request):
        nonlocal m3u8_url, headers
        # Filtramos las solicitudes que contienen ".m3u8" y que aún no hayamos capturado
        if ".m3u8" in request.url and m3u8_url is None:
            m3u8_url = request.url
            headers = dict(request.headers)

    # Registramos el evento para interceptar solicitudes HTTP
    page.on("request", on_request)
    # Navegamos a la URL objetivo
    await page.goto(url)

    try:
        # Esperamos hasta que aparezca el selector del reproductor de video para asegurar que cargó
        await page.wait_for_selector("video, #player", timeout=5000)
    except:
        # Si no aparece el selector, seguimos igual (no bloqueamos)
        pass

    # Esperamos un máximo de 8 segundos (80*0.1s) para que se capture el .m3u8
    for _ in range(80):
        if m3u8_url:
            break
        await asyncio.sleep(0.1)

    # Cerramos solo la pestaña actual, no el navegador entero
    await page.close()

    # Si capturamos la URL .m3u8, devolvemos los datos y el timestamp actual
    if m3u8_url:
        #print(m3u8_url)
        return {
            "url": m3u8_url,
            "headers": headers,
            "timestamp": time.time()
        }
    else:
        # Si no encontramos ninguna URL .m3u8, devolvemos None
        return None

