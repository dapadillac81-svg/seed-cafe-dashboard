# Dashboard de KPIs — Seed Café

Cada mañana, este proyecto revisa solo una carpeta de Google Drive, detecta si
hay un reporte nuevo de RecoPOS, lo procesa y publica un dashboard con los
KPIs de la cafetería en una página web que puedes abrir desde tu celular.

## Cómo funciona

1. **Tú (o quien tú decidas) exporta el reporte de RecoPOS** como hasta ahora
   (entrando a `s.recoposmx.com`, generándolo y descargándolo — este paso no
   se puede automatizar porque el login pide resolver un CAPTCHA) y lo sube a
   una carpeta de Google Drive designada para esto.
2. **GitHub Actions** despierta cada mañana automáticamente (también se puede
   correr manualmente desde la pestaña "Actions" del repositorio → "Run workflow").
3. **`drive_watcher.py`** usa una cuenta de servicio de Google para revisar esa
   carpeta, detecta archivos `.xlsx` que aún no se han procesado y los descarga
   a `data/`.
4. **`data_loader.py`** lee y combina todos los archivos descargados (el de
   hoy y todo el histórico acumulado).
5. **`generate_report.py`** calcula los KPIs y genera `docs/index.html`.
6. El workflow publica el dashboard actualizado; **GitHub Pages** lo sirve en
   una URL pública que puedes abrir desde tu celular.

## KPIs incluidos

- Ventas totales del día y número de transacciones
- Productos más vendidos
- Ventas por hora del día
- Ticket promedio, con comparación contra el promedio de los últimos días
- Reembolsos (mostrados aparte, sin mezclarlos con las ventas)

## Configuración inicial (una sola vez)

### 1. Crear la carpeta en Google Drive
Crea una carpeta dedicada (ej. "Reportes RecoPOS") donde subirás cada día el
`.xlsx` exportado de RecoPOS. Puedes seguir usando ambos tipos de reporte
("Informe de pedidos por tienda" y "Comparación de informes de cierre diario")
— el sistema los reconoce automáticamente por su contenido.

### 2. Crear una cuenta de servicio de Google (para que el robot pueda leer la carpeta)
1. Ve a [Google Cloud Console](https://console.cloud.google.com/) y crea un
   proyecto (o usa uno existente).
2. Habilita la **Google Drive API** (`APIs & Services` → `Library` → busca
   "Google Drive API" → `Enable`).
3. Crea una **cuenta de servicio** (`APIs & Services` → `Credentials` →
   `Create credentials` → `Service account`). No necesita ningún rol especial
   del proyecto.
4. Genera una **clave en formato JSON** para esa cuenta de servicio
   (`Keys` → `Add key` → `Create new key` → `JSON`) y descárgala. Este archivo
   contiene credenciales — guárdalo en un lugar seguro y no lo subas a ningún
   repositorio.
5. Copia el **correo de la cuenta de servicio** (algo como
   `nombre@proyecto.iam.gserviceaccount.com`).
6. **Comparte la carpeta de Drive del paso 1 con ese correo**, dándole acceso
   de "Lector" (solo lectura) — así el robot puede ver y descargar los
   archivos, pero no modificarlos.
7. Copia el **ID de la carpeta**: ábrela en el navegador y toma la parte final
   de la URL (`https://drive.google.com/drive/folders/`**`ESTE_ES_EL_ID`**).

### 3. Configurar los secretos del repositorio en GitHub
En el repo → `Settings` → `Secrets and variables` → `Actions` →
`New repository secret`:
- `GDRIVE_SERVICE_ACCOUNT_JSON`: pega el **contenido completo** del archivo
  JSON descargado en el paso 2.4
- `GDRIVE_FOLDER_ID`: el ID de la carpeta del paso 2.7

### 4. Activar GitHub Pages
`Settings` → `Pages` → en "Source" selecciona la rama `main` y la carpeta
`/docs` → Save.

### 5. Probar manualmente
Sube un `.xlsx` de prueba a la carpeta de Drive, luego ve a la pestaña
`Actions` → `Reporte diario Seed Café` → `Run workflow`. Revisa que termine en
verde y que la URL de Pages muestre el reporte actualizado con los datos de
ese archivo.

## Tu rutina diaria (lo único manual)

1. Entra a `s.recoposmx.com`, genera el "Informe de pedidos por tienda" y la
   "Comparación de informes de cierre diario" del día anterior (resolviendo el
   CAPTCHA de inicio de sesión — esto no se puede evitar).
2. Descarga ambos archivos y súbelos a la carpeta de Google Drive designada.
3. A la mañana siguiente, el dashboard ya estará actualizado solo — ábrelo
   desde tu celular en la URL de GitHub Pages.

## Ejecutar todo localmente (para probar)

```
pip install -r requirements.txt

set GDRIVE_SERVICE_ACCOUNT_JSON={"contenido": "del json..."}
set GDRIVE_FOLDER_ID=el_id_de_la_carpeta

python drive_watcher.py     # busca y descarga archivos nuevos a data/
python generate_report.py   # genera docs/index.html
```

Luego abre `docs/index.html` en tu navegador.

## Privacidad (modo piloto)

El repositorio es **público**, así que el **dashboard agregado**
(`docs/index.html` con los KPIs del día) queda visible en la URL de GitHub
Pages, aunque el link no esté listado en ningún buscador.

Para no exponer datos más sensibles, **los archivos `.xlsx` con el detalle de
cada orden NUNCA se suben al repositorio** (están en `.gitignore`). En su
lugar, el workflow los conserva entre ejecuciones usando el **caché de GitHub
Actions**, que es privado del repositorio — así se mantiene el histórico
necesario para las comparativas sin publicar transacciones individuales.

Cuando quieras, podemos migrar todo a un repositorio privado (requiere GitHub
Pro, ~$4 USD/mes) sin cambiar nada del resto del flujo.
