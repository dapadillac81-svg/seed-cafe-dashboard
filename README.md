# Dashboard de KPIs — Seed Café

Cada noche, este proyecto entra solo a RecoPOS, descarga las ventas del día
anterior y publica un reporte con los KPIs de la cafetería en una página web
que puedes abrir desde tu celular.

## Cómo funciona

1. **GitHub Actions** despierta automáticamente cada madrugada (también se puede
   correr manualmente desde la pestaña "Actions" del repositorio → "Run workflow").
2. **`scraper.py`** entra a `s.recoposmx.com` con un usuario dedicado, genera y
   descarga el "Informe de pedidos por tienda" y la "Comparación de informes de
   cierre diario" del día anterior, y los guarda en `data/`.
3. **`data_loader.py`** lee y combina todos los archivos de `data/` (el de ayer
   y todo el histórico acumulado).
4. **`generate_report.py`** calcula los KPIs y genera `docs/index.html`.
5. El workflow guarda los cambios en el repositorio; **GitHub Pages** publica
   automáticamente `docs/index.html` en una URL pública.

## KPIs incluidos

- Ventas totales del día y número de transacciones
- Productos más vendidos
- Ventas por hora del día
- Ticket promedio, con comparación contra el promedio de los últimos días
- Reembolsos (mostrados aparte, sin mezclarlos con las ventas)

## Configuración inicial (una sola vez)

1. **Crear un usuario dedicado en RecoPOS** para la automatización (no usar tu
   cuenta personal — así queda trazabilidad de qué hace el robot).
2. **Subir esta carpeta a un repositorio de GitHub.**
3. **Configurar los secretos del repositorio** (`Settings` → `Secrets and
   variables` → `Actions` → `New repository secret`):
   - `RECOPOS_USER`: el usuario dedicado
   - `RECOPOS_PASSWORD`: su contraseña
4. **Activar GitHub Pages** (`Settings` → `Pages`): fuente = rama `main`,
   carpeta `/docs`.
5. **Probar manualmente**: pestaña `Actions` → `Reporte diario Seed Café` →
   `Run workflow`. Revisa que termine en verde y que la URL de Pages muestre
   el reporte actualizado.

## Primera ejecución del scraper — ajustar selectores

`scraper.py` se escribió a partir de una captura de pantalla del Centro de
descargas (no se pudo probar en vivo, sin credenciales). **La primera vez**
conviene correrlo localmente con `DEBUG=1` (abre el navegador visible y guarda
capturas en `_debug_screens/`) para confirmar o ajustar los selectores reales:

```
set RECOPOS_USER=usuario_dedicado
set RECOPOS_PASSWORD=contraseña
set DEBUG=1
python scraper.py
```

Revisa `_debug_screens/` paso a paso y ajusta los selectores en `scraper.py`
según lo que veas en el sitio real.

## Ejecutar todo localmente (para probar)

```
pip install -r requirements.txt
python -m playwright install chromium

python scraper.py            # descarga el reporte de ayer a data/
python generate_report.py    # genera docs/index.html
```

Luego abre `docs/index.html` en tu navegador.

## Privacidad (modo piloto)

Por ahora el repositorio es **público**, así que las cifras de ventas quedan
visibles en la URL de GitHub Pages (aunque el link no esté listado en ningún
buscador). Cuando quieras, podemos migrar a un repositorio privado (requiere
GitHub Pro, ~$4 USD/mes) sin cambiar nada del resto del flujo.
