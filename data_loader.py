"""Descubre, clasifica y combina los reportes .xlsx exportados de RecoPOS.

Hay dos tipos de archivo, distinguibles por el nombre de sus hojas (no por el
nombre del archivo, que lleva un hash aleatorio):

  Tipo A — "Informe de pedidos por tienda": hojas 'orden' + 'Detalles del pedido'.
           Es la única fuente con hora exacta por orden.
  Tipo B — "Comparación de informes de cierre diario": hoja que empieza con
           'Estadísticas de orden' + 'Detalle de estadísticas de categoría'.
           Es la única fuente con categoría de producto.
"""

from __future__ import annotations

import glob
import json
import os
import re

import openpyxl
import pandas as pd

ORDER_DATETIME_FORMAT = "%d-%m-%Y %H:%M:%S"
REFUND_ORDER_TYPE = "Orden de devolución"
SIN_CLASIFICAR = "SIN CLASIFICAR"

_PRODUCT_CATEGORY_MAP_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "product_category_map.json"
)
with open(_PRODUCT_CATEGORY_MAP_PATH, encoding="utf-8") as _f:
    PRODUCT_CATEGORY_MAP: dict[str, str] = json.load(_f)


def _sheet_names(path: str) -> list[str]:
    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        return wb.sheetnames
    finally:
        wb.close()


def classify_file(path: str) -> str | None:
    """Devuelve 'A', 'B' o None si no se reconoce el archivo."""
    names = _sheet_names(path)
    if "orden" in names:
        return "A"
    if any(name.startswith("Estadísticas de orden") for name in names):
        return "B"
    return None


def parse_type_a(path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parsea un reporte 'Informe de pedidos por tienda'.

    Devuelve (orders_df, items_df).
    """
    orders = pd.read_excel(path, sheet_name="orden")
    orders["Hora de orden"] = pd.to_datetime(
        orders["Hora de orden"], format=ORDER_DATETIME_FORMAT
    )
    orders["fecha"] = orders["Hora de orden"].dt.date
    orders["es_reembolso"] = orders["Tipo de orden"] == REFUND_ORDER_TYPE
    orders["source_file"] = os.path.basename(path)

    items = pd.read_excel(path, sheet_name="Detalles del pedido")
    items["source_file"] = os.path.basename(path)
    # Las líneas de producto no traen fecha propia: la heredan de su orden.
    items = items.merge(
        orders[["No. de orden", "fecha", "es_reembolso"]],
        on="No. de orden",
        how="left",
    )
    return orders, items


def _find_sheet(path: str, prefix: str) -> str:
    """Busca una hoja por prefijo (Excel trunca nombres de hoja a 31 caracteres)."""
    for name in _sheet_names(path):
        if name.startswith(prefix):
            return name
    raise KeyError(f"No se encontró ninguna hoja que empiece con {prefix!r} en {path}")


def parse_type_b_categoria(path: str) -> pd.DataFrame:
    """Parsea la hoja 'Detalle de estadísticas de categoría' de un reporte Tipo B."""
    sheet = _find_sheet(path, "Detalle de estadísticas de cate")
    df = pd.read_excel(path, sheet_name=sheet, header=1)
    df = df.dropna(subset=["Nombre de producto"])
    df["fecha"] = pd.to_datetime(df["Fecha"], format="%d-%m-%Y").dt.date
    df["source_file"] = os.path.basename(path)
    return df


def _parse_md_table(lines: list[str], header_idx: int) -> tuple[list[str], list[list[str]]]:
    """Parsea una tabla markdown cuyo encabezado está en lines[header_idx].

    La línea separadora (|---|---|) está en header_idx + 1; las filas de datos
    siguen hasta la primera línea que no empiece con '|'.
    """
    header = [c.strip() for c in lines[header_idx].strip().strip("|").split("|")]
    rows = []
    i = header_idx + 2
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith("|"):
            break
        rows.append([c.strip() for c in line.strip().strip("|").split("|")])
        i += 1
    return header, rows


def _find_table_header(lines: list[str], section_heading: str) -> int | None:
    """Devuelve el índice de la línea de encabezado de la tabla bajo `## section_heading`."""
    for idx, line in enumerate(lines):
        if line.strip().startswith("## ") and section_heading in line:
            for j in range(idx + 1, len(lines)):
                if lines[j].strip().startswith("|"):
                    return j
                if lines[j].strip().startswith("##") or lines[j].strip().startswith("---"):
                    return None
            return None
    return None


def _to_float(value: str) -> float | None:
    cleaned = value.replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_cierre_txt(path: str) -> dict[str, pd.DataFrame]:
    """Parsea un `cierre_YYYY-MM-DD.txt` generado por el SKILL de cowork.

    Devuelve un dict con 'orders', 'items' y 'categoria' (DataFrames que
    pueden venir vacíos si las secciones correspondientes no están presentes
    o dicen "No disponible").
    """
    basename = os.path.basename(path)
    match = re.search(r"(\d{4}-\d{2}-\d{2})", basename)
    fecha = pd.to_datetime(match.group(1)).date()

    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    orders_rows = []
    header_idx = _find_table_header(lines, "DETALLE DE ÓRDENES")
    if header_idx is not None:
        header, rows = _parse_md_table(lines, header_idx)
        for cells in rows:
            d = dict(zip(header, cells))
            monto = _to_float(d.get("Monto", ""))
            try:
                hora = pd.to_datetime(d.get("Hora", ""), format=ORDER_DATETIME_FORMAT)
            except ValueError:
                hora = pd.NaT
            if monto is None or pd.isna(hora):
                continue
            tipo = d.get("Tipo", "orden")
            orders_rows.append({
                "No. de orden": d.get("No. Orden"),
                "Monto total de orden": monto,
                "Folio/Mesa": d.get("Folio/Mesa"),
                "Hora de orden": hora,
                "Método de pago": d.get("Pago"),
                "Fuente de la orden": d.get("Fuente"),
                "Tipo de orden": tipo,
                "fecha": fecha,
                "es_reembolso": tipo == REFUND_ORDER_TYPE,
                "source_file": basename,
            })

    items_rows = []
    header_idx = _find_table_header(lines, "DETALLE DE PRODUCTOS")
    if header_idx is not None:
        header, rows = _parse_md_table(lines, header_idx)
        for cells in rows:
            d = dict(zip(header, cells))
            cantidad = _to_float(d.get("Cantidad", ""))
            monto = _to_float(d.get("Monto", ""))
            if cantidad is None or monto is None:
                continue
            es_reembolso = d.get("Reembolso", "No").strip().lower() in ("sí", "si", "true", "yes")
            producto_base = (d.get("Producto") or "").strip()
            opciones = (d.get("Opciones") or "").strip()
            # Empaqueta las opciones (tipo de leche, shots extra) como un grupo
            # entre paréntesis, igual que el formato de "Nombre de producto" de
            # los .xlsx Tipo A — así _nombre_base()/_tipo_leche() en
            # generate_report.py funcionan igual para filas de .txt.
            nombre_completo = f"{producto_base}（{opciones}）" if opciones else producto_base
            items_rows.append({
                "No. de orden": d.get("No. Orden"),
                "Nombre de producto": nombre_completo,
                "producto_base": producto_base,
                "Cantidad": cantidad,
                "Precio total después del descuento (modificado)": monto,
                "fecha": fecha,
                "es_reembolso": es_reembolso,
                "source_file": basename,
            })

    orders_df = pd.DataFrame(orders_rows)
    items_df = pd.DataFrame(items_rows)

    categoria_rows = []
    if not items_df.empty:
        ventas = items_df[~items_df["es_reembolso"]]
        grouped = ventas.groupby("producto_base", as_index=False).agg(
            Cantidad=("Cantidad", "sum"),
            Monto=("Precio total después del descuento (modificado)", "sum"),
        )
        for _, row in grouped.iterrows():
            producto = row["producto_base"]
            categoria_rows.append({
                "Fecha": fecha.strftime("%d-%m-%Y"),
                "Clasificación": PRODUCT_CATEGORY_MAP.get(producto, SIN_CLASIFICAR),
                "Nombre de producto": producto,
                "Cantidad": row["Cantidad"],
                "Monto": row["Monto"],
                "fecha": fecha,
                "source_file": basename,
            })
    categoria_df = pd.DataFrame(categoria_rows)

    return {"orders": orders_df, "items": items_df, "categoria": categoria_df}


def discover_files(folder: str) -> list[str]:
    return sorted(glob.glob(os.path.join(folder, "*.xlsx")))


def discover_txt_files(folder: str) -> list[str]:
    """Busca `cierre_*.txt` en `data_txt/`, hermana de `folder` (normalmente `data/`)."""
    txt_folder = os.path.join(os.path.dirname(os.path.normpath(folder)), "data_txt")
    return sorted(glob.glob(os.path.join(txt_folder, "cierre_*.txt")))


def load_all_data(folder: str) -> dict[str, pd.DataFrame]:
    """Lee todos los .xlsx de la carpeta, los clasifica, parsea y combina.

    Devuelve un dict con tres DataFrames maestros (pueden estar vacíos si no
    hay archivos de ese tipo todavía):
      - 'orders':    una fila por orden (Tipo A)
      - 'items':     una fila por producto vendido (Tipo A)
      - 'categoria': una fila por producto/categoría/día (Tipo B)
    """
    orders_parts: list[pd.DataFrame] = []
    items_parts: list[pd.DataFrame] = []
    categoria_parts: list[pd.DataFrame] = []
    xlsx_dates: set = set()

    for path in discover_files(folder):
        kind = classify_file(path)
        if kind == "A":
            orders, items = parse_type_a(path)
            orders_parts.append(orders)
            items_parts.append(items)
            xlsx_dates.update(orders["fecha"].unique())
        elif kind == "B":
            try:
                categoria_parts.append(parse_type_b_categoria(path))
            except (KeyError, ValueError):
                # Algunos exports Tipo B podrían no traer la hoja de categoría.
                pass
        # kind is None -> archivo no reconocido, se ignora silenciosamente

    # Los .txt de cowork solo se usan para fechas que no tengan ya un .xlsx
    # (más granular y confiable) — evita duplicar/diluir esos días.
    for path in discover_txt_files(folder):
        parsed = parse_cierre_txt(path)
        if parsed["orders"].empty:
            continue
        fecha = parsed["orders"]["fecha"].iloc[0]
        if fecha in xlsx_dates:
            continue
        orders_parts.append(parsed["orders"])
        items_parts.append(parsed["items"])
        if not parsed["categoria"].empty:
            categoria_parts.append(parsed["categoria"])

    orders_df = (
        pd.concat(orders_parts, ignore_index=True).drop_duplicates(subset=["No. de orden"])
        if orders_parts
        else pd.DataFrame()
    )
    items_df = (
        pd.concat(items_parts, ignore_index=True)
        if items_parts
        else pd.DataFrame()
    )
    categoria_df = (
        pd.concat(categoria_parts, ignore_index=True).drop_duplicates(
            subset=["fecha", "Clasificación", "Nombre de producto"]
        )
        if categoria_parts
        else pd.DataFrame()
    )

    return {"orders": orders_df, "items": items_df, "categoria": categoria_df}


def available_dates(orders_df: pd.DataFrame) -> list:
    """Lista de fechas disponibles, ordenadas de más antigua a más reciente."""
    if orders_df.empty:
        return []
    return sorted(orders_df["fecha"].unique())


def latest_date(orders_df: pd.DataFrame):
    dates = available_dates(orders_df)
    return dates[-1] if dates else None


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    data = load_all_data(os.path.join(here, "data"))
    for name, df in data.items():
        print(f"{name}: {len(df)} filas")
    print("fechas disponibles:", available_dates(data["orders"]))
