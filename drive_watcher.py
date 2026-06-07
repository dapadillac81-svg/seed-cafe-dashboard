"""Detecta y descarga archivos nuevos desde una carpeta de Google Drive.

Flujo:
  1. Cada día, alguien exporta manualmente el reporte de RecoPOS (requiere
     resolver un CAPTCHA, así que no se puede automatizar ese paso) y lo sube
     a una carpeta compartida de Google Drive.
  2. Este script usa una CUENTA DE SERVICIO de Google (sin login interactivo)
     para listar los archivos .xlsx de esa carpeta, identificar cuáles no se
     han procesado todavía (comparando contra un manifiesto local), y
     descargarlos a data/.
  3. data_loader.py / generate_report.py hacen el resto, igual que si los
     archivos hubieran llegado por cualquier otro medio.

Credenciales: la cuenta de servicio se configura una sola vez en Google Cloud
y se comparte (solo lectura) con la carpeta de Drive. Su clave JSON se guarda
como secreto de GitHub (GDRIVE_SERVICE_ACCOUNT_JSON) y NUNCA en el código.
El ID de la carpeta se guarda como secreto/variable (GDRIVE_FOLDER_ID).

Manifiesto: data/.procesados.json — lista de IDs de archivo de Drive ya
descargados, para no volver a bajarlos cada noche. Vive junto a los .xlsx en
el caché privado de Actions (no se publica).
"""

from __future__ import annotations

import io
import json
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
MANIFEST_PATH = os.path.join(DATA_DIR, ".procesados.json")


def _load_manifest() -> set[str]:
    if not os.path.exists(MANIFEST_PATH):
        return set()
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return set(json.load(f))


def _save_manifest(processed_ids: set[str]):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(processed_ids), f, ensure_ascii=False, indent=2)


def _build_drive_service():
    raw_credentials = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON")
    if not raw_credentials:
        raise SystemExit("Falta la variable de entorno GDRIVE_SERVICE_ACCOUNT_JSON")
    info = json.loads(raw_credentials)
    credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _list_xlsx_files(service, folder_id: str) -> list[dict]:
    query = f"'{folder_id}' in parents and mimeType='{XLSX_MIME}' and trashed=false"
    results = []
    page_token = None
    while True:
        response = (
            service.files()
            .list(
                q=query,
                fields="nextPageToken, files(id, name, modifiedTime)",
                pageToken=page_token,
            )
            .execute()
        )
        results.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return results


def _download_file(service, file_id: str, dest_path: str):
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    with open(dest_path, "wb") as f:
        f.write(buffer.getvalue())


def sync_new_files() -> list[str]:
    """Descarga los .xlsx nuevos de la carpeta de Drive a data/.

    Devuelve la lista de rutas locales de los archivos recién descargados.
    """
    folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    if not folder_id:
        raise SystemExit("Falta la variable de entorno GDRIVE_FOLDER_ID")

    os.makedirs(DATA_DIR, exist_ok=True)
    service = _build_drive_service()
    processed = _load_manifest()
    files = _list_xlsx_files(service, folder_id)

    new_paths = []
    for meta in files:
        if meta["id"] in processed:
            continue
        dest = os.path.join(DATA_DIR, meta["name"])
        print(f"Descargando archivo nuevo: {meta['name']} ({meta['modifiedTime']})")
        _download_file(service, meta["id"], dest)
        new_paths.append(dest)
        processed.add(meta["id"])

    _save_manifest(processed)

    if not new_paths:
        print("No se encontraron archivos nuevos en la carpeta de Drive.")
    return new_paths


if __name__ == "__main__":
    descargados = sync_new_files()
    for path in descargados:
        print(f"  -> {path}")
