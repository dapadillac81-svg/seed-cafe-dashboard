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
import os

import openpyxl
import pandas as pd

ORDER_DATETIME_FORMAT = "%d-%m-%Y %H:%M:%S"
REFUND_ORDER_TYPE = "Orden de devolución"


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


def discover_files(folder: str) -> list[str]:
    return sorted(glob.glob(os.path.join(folder, "*.xlsx")))


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

    for path in discover_files(folder):
        kind = classify_file(path)
        if kind == "A":
            orders, items = parse_type_a(path)
            orders_parts.append(orders)
            items_parts.append(items)
        elif kind == "B":
            try:
                categoria_parts.append(parse_type_b_categoria(path))
            except (KeyError, ValueError):
                # Algunos exports Tipo B podrían no traer la hoja de categoría.
                pass
        # kind is None -> archivo no reconocido, se ignora silenciosamente

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
