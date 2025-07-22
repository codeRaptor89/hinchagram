# playwright_manager.py
from playwright.async_api import async_playwright

# Variables globales para manejar la instancia de Playwright y el navegador
_playwright = None
_browser = None

async def init_browser():
    """
    Inicializa Playwright y lanza un navegador Chromium si aún no está iniciado.

    Esta función es asíncrona y debe ser llamada antes de crear nuevas páginas.
    """
    global _playwright, _browser
    if _browser is None:
        # Inicia Playwright
        _playwright = await async_playwright().start()
        # Lanza un navegador Chromium (headless=False muestra la ventana, poner True para producción)
        _browser = await _playwright.chromium.launch(headless=True)  # o True para producción

async def get_new_page():
    """
    Crea y retorna una nueva página (pestaña) del navegador.

    Si el navegador no está inicializado, lo inicia automáticamente.

    Configura un nuevo contexto con:
    - user_agent personalizado,
    - viewport de 1280x720,
    - locale español (España).

    Returns:
        Página nueva de Playwright lista para usar.
    """
    global _browser
    if _browser is None:
        # Iniciar el navegador si no está iniciado
        await init_browser()
    # Crear un nuevo contexto de navegador con configuración personalizada
    context = await _browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
        viewport={"width": 1280, "height": 720},
        locale="es-ES"
    )
    # Abrir y retornar una nueva pestaña (página)
    return await context.new_page()

async def close_browser():
    """
    Cierra el navegador y detiene Playwright si están activos.

    Esta función es asíncrona y debe ser llamada para liberar recursos al finalizar.
    """
    global _browser, _playwright
    if _browser:
        await _browser.close()
        _browser = None
    if _playwright:
        await _playwright.stop()
        _playwright = None
