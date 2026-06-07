"""Automatiza el Centro de descargas de RecoPOS (Playwright):

  1. Inicia sesión en https://s.recoposmx.com con un usuario dedicado
  2. Genera el "Informe de pedidos por tienda" (Tipo A) y la
     "Comparación de informes de cierre diario" (Tipo B) para el día anterior
  3. Espera a que el estado de cada tarea pase a "Éxito" en el historial
  4. Descarga ambos archivos a la carpeta data/, con nombre predecible
     <fecha>_ordenes.xlsx / <fecha>_categorias.xlsx

Credenciales: se leen de las variables de entorno RECOPOS_USER / RECOPOS_PASSWORD
(en GitHub Actions vienen de Secrets). Nunca se deben escribir en el código.

NOTA PARA QUIEN AJUSTE ESTE SCRIPT:
Los selectores de abajo se basan en lo observado en una captura de pantalla del
Centro de descargas (https://s.recoposmx.com/#/downloadCenter/index) y en los
nombres de tarea vistos en el historial ("Informe de pedidos por tienda",
"Comparación de informes de cierre diario en cadena"). No se pudo probar contra
el sitio en vivo (sin credenciales). La PRIMERA ejecución debe hacerse con
DEBUG=1 (navegador visible, screenshots en cada paso) para confirmar/corregir
los selectores reales del sitio antes de dejarlo en automático.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

BASE_URL = "https://s.recoposmx.com"
LOGIN_URL = f"{BASE_URL}/#/login"
DOWNLOAD_CENTER_URL = f"{BASE_URL}/#/downloadCenter/index"

# Nombres de tarea tal como aparecen en la columna "Tipo" del historial
TASK_TYPE_ORDERS = "Informe de pedidos por tienda"
TASK_TYPE_CLOSING = "Comparación de informes de cierre diario en cadena"

SUCCESS_LABEL = "Éxito"
POLL_INTERVAL_SECONDS = 15
POLL_TIMEOUT_SECONDS = 10 * 60

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
DEBUG = os.environ.get("DEBUG") == "1"
DEBUG_DIR = os.path.join(HERE, "_debug_screens")


def _debug_shot(page: Page, name: str):
    if not DEBUG:
        return
    os.makedirs(DEBUG_DIR, exist_ok=True)
    page.screenshot(path=os.path.join(DEBUG_DIR, f"{name}.png"), full_page=True)


def login(page: Page, user: str, password: str):
    page.goto(LOGIN_URL)
    page.wait_for_load_state("networkidle")
    _debug_shot(page, "01_login_page")

    # Selectores genéricos: ajustar si el sitio usa nombres/ids distintos.
    page.fill("input[type='text'], input[name='username'], input[placeholder*='usuario' i]", user)
    page.fill("input[type='password']", password)
    _debug_shot(page, "02_login_filled")

    page.click("button:has-text('Iniciar'), button:has-text('Entrar'), button[type='submit']")
    page.wait_for_load_state("networkidle")
    _debug_shot(page, "03_after_login")

    if "login" in page.url.lower():
        raise RuntimeError("El login no tuvo éxito (seguimos en la página de login). Revisa selectores/credenciales.")


def open_download_center(page: Page):
    page.goto(DOWNLOAD_CENTER_URL)
    page.wait_for_load_state("networkidle")
    _debug_shot(page, "04_download_center")


def request_report(page: Page, task_label: str, target_date: datetime):
    """Genera un reporte para target_date, navegando el formulario correspondiente.

    NOTA: el formulario exacto para elegir tipo de reporte + rango de fechas no
    se pudo observar (solo el historial de tareas ya generadas). Este flujo
    asume que, dentro de "Informe de tienda individual", existe una opción/
    botón para generar cada tipo de reporte con un selector de rango de fechas,
    similar a otros paneles de RecoPOS. AJUSTAR tras inspeccionar el DOM real
    (correr con DEBUG=1 y revisar _debug_screens/ y el HTML de la página).
    """
    date_str = target_date.strftime("%d-%m-%Y")

    # Abrir la sección/menú correspondiente al tipo de reporte
    page.click(f"text={task_label}")
    page.wait_for_load_state("networkidle")
    _debug_shot(page, f"05_form_{_slug(task_label)}")

    # Selector de rango de fechas: se intenta con el patrón visto en el historial
    # ("Fecha:DD-MM-YYYY ~ DD-MM-YYYY"). Ajustar al control real (date picker, etc).
    date_inputs = page.locator("input[placeholder*='fecha' i], input[type='date']")
    if date_inputs.count() >= 2:
        date_inputs.nth(0).fill(date_str)
        date_inputs.nth(1).fill(date_str)
    elif date_inputs.count() == 1:
        date_inputs.first.fill(date_str)

    _debug_shot(page, f"06_dates_set_{_slug(task_label)}")

    # Botón para disparar la generación del reporte
    page.click("button:has-text('Generar'), button:has-text('Exportar'), button:has-text('Descargar')")
    page.wait_for_timeout(2000)
    _debug_shot(page, f"07_requested_{_slug(task_label)}")


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower())[:40]


def wait_for_success_and_download(page: Page, task_label: str, requested_after: datetime) -> str:
    """Recarga el historial hasta ver el reporte recién pedido en estado Éxito,
    y descarga el archivo. Devuelve la ruta local del archivo descargado."""
    open_download_center(page)
    deadline = time.time() + POLL_TIMEOUT_SECONDS

    while time.time() < deadline:
        page.click("button:has-text('Historial')")
        page.wait_for_load_state("networkidle")
        _debug_shot(page, f"08_history_{_slug(task_label)}")

        rows = page.locator("table tbody tr")
        for i in range(rows.count()):
            row = rows.nth(i)
            row_text = row.inner_text()
            if task_label not in row_text:
                continue
            if SUCCESS_LABEL not in row_text:
                continue
            # Encontramos una fila exitosa de este tipo de reporte.
            with page.expect_download() as dl_info:
                row.get_by_text("Descargar").click()
            download = dl_info.value
            os.makedirs(DATA_DIR, exist_ok=True)
            dest = os.path.join(DATA_DIR, download.suggested_filename)
            download.save_as(dest)
            return dest

        page.wait_for_timeout(POLL_INTERVAL_SECONDS * 1000)

    raise TimeoutError(
        f"Timeout esperando que '{task_label}' termine con estado '{SUCCESS_LABEL}'"
    )


def rename_for_date(path: str, target_date: datetime, kind: str) -> str:
    date_str = target_date.strftime("%Y-%m-%d")
    suffix = "ordenes" if kind == "A" else "categorias"
    new_path = os.path.join(DATA_DIR, f"{date_str}_{suffix}.xlsx")
    if os.path.abspath(path) != os.path.abspath(new_path):
        if os.path.exists(new_path):
            os.remove(new_path)
        os.rename(path, new_path)
    return new_path


def run(target_date: datetime | None = None):
    user = os.environ.get("RECOPOS_USER")
    password = os.environ.get("RECOPOS_PASSWORD")
    if not user or not password:
        raise SystemExit("Faltan las variables de entorno RECOPOS_USER / RECOPOS_PASSWORD")

    if target_date is None:
        target_date = datetime.now() - timedelta(days=1)

    os.makedirs(DATA_DIR, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not DEBUG)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        try:
            login(page, user, password)

            for task_label, kind in ((TASK_TYPE_ORDERS, "A"), (TASK_TYPE_CLOSING, "B")):
                requested_at = datetime.now()
                open_download_center(page)
                request_report(page, task_label, target_date)
                downloaded = wait_for_success_and_download(page, task_label, requested_at)
                final_path = rename_for_date(downloaded, target_date, kind)
                print(f"Descargado [{kind}] {task_label} -> {final_path}")

        except (PWTimeout, RuntimeError, TimeoutError) as exc:
            _debug_shot(page, "99_error")
            print(f"ERROR durante la descarga automática: {exc}", file=sys.stderr)
            raise
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    target = datetime.strptime(arg, "%Y-%m-%d") if arg else None
    run(target)
