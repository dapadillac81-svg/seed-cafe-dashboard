"""Calcula los KPIs del día más reciente y genera docs/index.html con Plotly + Jinja2."""

from __future__ import annotations

import os
import re
import sys

import pandas as pd
import plotly.express as px
import plotly.io as pio
from jinja2 import Environment, FileSystemLoader

import data_loader as dl

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
DOCS_DIR = os.path.join(HERE, "docs")
TEMPLATES_DIR = os.path.join(HERE, "templates")

PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}
CHART_TEMPLATE = "plotly_white"

# Paleta fija para que cada categoría/tipo de leche tenga siempre el mismo
# color, sin importar el día (de lo contrario Plotly reasigna colores según
# el orden en que aparecen las categorías en cada día).
COLOR_PALETTE = px.colors.qualitative.Light24


def _build_color_map(values) -> dict:
    """Asigna un color fijo de COLOR_PALETTE a cada valor único, en orden
    alfabético, para que el mismo nombre siempre tenga el mismo color."""
    uniq = sorted({v for v in values if pd.notna(v)})
    return {val: COLOR_PALETTE[i % len(COLOR_PALETTE)] for i, val in enumerate(uniq)}


def _fig_to_html(fig, include_js=False):
    fig.update_layout(template=CHART_TEMPLATE, margin=dict(l=10, r=10, t=40, b=10))
    return pio.to_html(
        fig,
        full_html=False,
        include_plotlyjs="cdn" if include_js else False,
        config=PLOTLY_CONFIG,
    )


def compute_kpis(orders_df: pd.DataFrame, target_date) -> dict:
    day = orders_df[orders_df["fecha"] == target_date]
    sales = day[~day["es_reembolso"]]
    refunds = day[day["es_reembolso"]]

    total_ventas = sales["Monto total de orden"].sum()
    num_transacciones = len(sales)
    ticket_promedio = sales["Monto total de orden"].mean() if num_transacciones else 0.0
    total_reembolsado = refunds["Monto total de orden"].abs().sum()
    num_reembolsos = len(refunds)

    # Comparativa: promedio de ticket de los últimos 7 días anteriores (sin contar hoy)
    history = orders_df[(~orders_df["es_reembolso"]) & (orders_df["fecha"] < target_date)]
    daily_avg = history.groupby("fecha")["Monto total de orden"].mean()
    recent_avg = daily_avg.tail(7).mean() if not daily_avg.empty else None
    ticket_delta = (
        ticket_promedio - recent_avg if recent_avg is not None and not pd.isna(recent_avg) else None
    )

    return {
        "total_ventas": total_ventas,
        "num_transacciones": num_transacciones,
        "ticket_promedio": ticket_promedio,
        "ticket_delta": ticket_delta,
        "total_reembolsado": total_reembolsado,
        "num_reembolsos": num_reembolsos,
    }


def build_hourly_chart(orders_df: pd.DataFrame, target_date):
    day = orders_df[(orders_df["fecha"] == target_date) & (~orders_df["es_reembolso"])].copy()
    if day.empty:
        return None
    day["hora"] = day["Hora de orden"].dt.hour
    by_hour = (
        day.groupby("hora")["Monto total de orden"]
        .agg(ventas="sum", ordenes="count")
        .reindex(range(8, 21), fill_value=0)
        .reset_index()
    )
    by_hour["hora_label"] = by_hour["hora"].apply(lambda h: f"{h}:00")
    fig = px.bar(
        by_hour,
        x="hora_label",
        y="ventas",
        text=by_hour["ventas"].apply(lambda v: f"${v:,.0f}" if v > 0 else ""),
        labels={"hora_label": "Hora", "ventas": "Ventas ($)"},
        title="Ventas por hora (8 AM – 8 PM)",
    )
    fig.update_traces(textposition="outside", textfont_size=12)
    fig.update_layout(
        xaxis=dict(tickangle=0, tickfont=dict(size=8)),
        yaxis=dict(visible=False),
        bargap=0.3,
    )
    return _fig_to_html(fig, include_js=True)


def build_hourly_category_chart(orders_df: pd.DataFrame, items_df: pd.DataFrame, categoria_df: pd.DataFrame, target_date, color_map: dict):
    """Barras apiladas: piezas vendidas por hora (8 AM - 8 PM), desglosadas
    por categoría de producto."""
    if items_df.empty or categoria_df.empty:
        return None
    day_items = items_df[(items_df["fecha"] == target_date) & (~items_df["es_reembolso"])].copy()
    if day_items.empty:
        return None

    # Mapa producto base -> categoría, usando todo el histórico de categoria_df
    cat_map_df = categoria_df.copy()
    cat_map_df["nombre_base"] = cat_map_df["Nombre de producto"].apply(_nombre_base)
    cat_map = (
        cat_map_df.groupby("nombre_base")["Clasificación"]
        .agg(lambda s: s.mode().iloc[0] if not s.mode().empty else "OTROS")
        .to_dict()
    )

    day_items["nombre_base"] = day_items["Nombre de producto"].apply(_nombre_base)
    day_items["categoria"] = day_items["nombre_base"].map(cat_map).fillna("OTROS")

    day_items = day_items.merge(
        orders_df[["No. de orden", "Hora de orden"]], on="No. de orden", how="left"
    )
    day_items["hora"] = day_items["Hora de orden"].dt.hour

    by_hour_cat = day_items.groupby(["hora", "categoria"])["Cantidad"].sum().reset_index()

    categorias = sorted(by_hour_cat["categoria"].unique())
    full = pd.MultiIndex.from_product([range(8, 21), categorias], names=["hora", "categoria"]).to_frame(index=False)
    by_hour_cat = full.merge(by_hour_cat, on=["hora", "categoria"], how="left").fillna(0)
    by_hour_cat["hora_label"] = by_hour_cat["hora"].apply(lambda h: f"{h}:00")

    fig = px.bar(
        by_hour_cat,
        x="hora_label",
        y="Cantidad",
        color="categoria",
        color_discrete_map=color_map,
        labels={"hora_label": "Hora", "Cantidad": "Piezas vendidas", "categoria": "Categoría"},
        title="Pedidos por hora y categoría",
    )
    fig.update_layout(
        barmode="stack",
        xaxis=dict(tickangle=0, tickfont=dict(size=8)),
        yaxis=dict(visible=False),
        bargap=0.3,
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.15,
            xanchor="center",
            x=0.5,
            font=dict(size=9),
            title=None,
        ),
        margin=dict(b=120),
    )
    return _fig_to_html(fig)


# Productos que RecoPOS exportaba con un nombre "legado" (ej. en pedidos
# antiguos) y que corresponden al mismo producto que ahora se exporta con
# otro nombre. Se mapean a su nombre actual para que el histórico se agrupe
# correctamente (cantidades y categoría) sin importar de qué fecha venga.
_NOMBRE_ALIAS = {
    "Americano - Caliente": "AMERICANO CALIENTE/16 OZ",
    "Capuccino - Caliente": "CAPUCCINO CALIENTE/16 OZ",
    "Capuccino con Sabor de Amaret - Caliente": "CAPUCCINO CALIENTE AMARETTO/16 OZ",
    "Capuccino con Sabor de Avellana - Frappé": "AVELLANA CAPUCCINO FRAPPE/16 OZ",
    "Chai Guayaba": "CHAI GUAYABA/16 oz",
    "Chai Vainilla - Frio": "CHAI VAINILLA FRIO/16 OZ",
    "Chocomenta - Frappé": "CHOCOMENTA FRAPPE/16 OZ",
    "Coffee Tonic Mandarina": "COFFE TONIC/16 OZ",
    "Horchata Nuez - Frio": "HORCHATA FRIA/16 OZ",
    "Matcha - Frio": "MATCHA FRIO/16 OZ",
    "Matcha Menta - Frio": "MATCHA-MENTA FRIO/16 OZ",
    "Mazapán - Frio": "MAZAPAN FRIO/16 OZ",
    "Moka - Frappé": "MOKA CAPUCCINO FRAPPE/16 OZ",
    "Moka Blanco - Caliente": "MOKA BLANCO CAPUCCINO CALIENTE/16 OZ",
    "Molletes Naturales": "MOLLETES/2 PZAS",
    "Nutella - Frappé": "FRAPPE NUTELLA/16 OZ",
    "Smoothie Guayaba": "GUAYABA SMOOTHIE/16 OZ",
    "Taro sin Azúcar - Frio": "TARO S/A FRIO/16 OZ",
    "Té de Frutos Rojos - Frio": "TE FRUTOS ROJOS FRIO/16 OZ",
    "Wrap Omelette-Jamón y Queso": "WRAP DE OMELETTE JAMON Y QUESO/1 PZA",
}


def _nombre_base(nombre: str) -> str:
    """Quita las variantes entre paréntesis (ej. tipo de leche, shots extra)
    del nombre del producto, para agrupar 'CAPUCCINO/16 OZ (LECHE LIGHT)' y
    'CAPUCCINO/16 OZ（02 LECHE DESLACTOSADA）, （SHOT EXTRA CAFE+15）' bajo
    'CAPUCCINO/16 OZ'. Quita los grupos entre paréntesis al final del nombre
    de uno en uno (puede haber varios separados por comas). También traduce
    nombres "legados" a su nombre actual (ver _NOMBRE_ALIAS)."""
    s = str(nombre)
    while True:
        # Acepta un sufijo opcional "*N" después del paréntesis, ej.
        # "...（Shot Extra Cafe+15）*2" (combo duplicado).
        nuevo = re.sub(r"\s*[,，]?\s*[（(][^（()）]*[）)](?:\s*\*\d+)?\s*$", "", s)
        if nuevo == s:
            break
        s = nuevo
    s = s.strip()
    return _NOMBRE_ALIAS.get(s, s)


def _slug(texto: str) -> str:
    """Convierte un texto en un identificador simple para usar como
    data-chart-id (para recordar la posición de scroll entre días)."""
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", str(texto)).strip("-").lower()
    return texto or "cat"


def _tipo_leche(nombre: str) -> str | None:
    """Extrae el tipo de leche del nombre del producto, revisando cada
    variante entre paréntesis (puede haber varias, ej. tipo de leche y shots
    extra por separado) y devolviendo la que mencione "LECHE".
    Ej. '...（02 LECHE DESLACTOSADA）, （SHOT EXTRA CAFE+15）' -> 'Leche Deslactosada'.
    Devuelve None si el producto no trae variante de leche (ej. agua, panes)."""
    grupos = re.findall(r"[（(]([^（()）]*)[）)]", str(nombre))
    for variante in grupos:
        variante = variante.strip()
        # Quita prefijos numéricos tipo "01 ", "02 ", "13 ", "14 +12"
        variante = re.sub(r"^\d+\s*", "", variante)
        variante = re.sub(r"\+\d+$", "", variante).strip()
        if "LECHE" in variante.upper():
            return variante.title()
    return None


def build_milk_chart(items_df: pd.DataFrame, target_date, color_map: dict):
    if items_df.empty:
        return None
    day = items_df[(items_df["fecha"] == target_date) & (~items_df["es_reembolso"])].copy()
    if day.empty:
        return None
    day["tipo_leche"] = day["Nombre de producto"].apply(_tipo_leche)
    day = day.dropna(subset=["tipo_leche"])
    if day.empty:
        return None
    by_leche = (
        day.groupby("tipo_leche")["Cantidad"]
        .sum()
        .reset_index()
        .sort_values("Cantidad", ascending=False)
        .sort_values("Cantidad")
    )
    fig = px.bar(
        by_leche,
        x="Cantidad",
        y="tipo_leche",
        orientation="h",
        text=by_leche["Cantidad"].apply(lambda v: f"{v:,.0f}"),
        color="tipo_leche",
        color_discrete_map=color_map,
        labels={"Cantidad": "Piezas pedidas", "tipo_leche": ""},
        title="Tipos de leche pedidos",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(
        font=dict(size=11),
        yaxis=dict(tickfont=dict(size=9), autorange="reversed"),
        xaxis=dict(visible=False),
        showlegend=False,
        height=max(160, 35 * len(by_leche) + 60),
    )
    return _fig_to_html(fig)


def build_top_products_chart(items_df: pd.DataFrame, target_date, top_n=10):
    if items_df.empty:
        return None
    day = items_df[(items_df["fecha"] == target_date) & (~items_df["es_reembolso"])].copy()
    if day.empty:
        return None
    day["Nombre de producto"] = day["Nombre de producto"].apply(_nombre_base)
    by_product = (
        day.groupby("Nombre de producto")
        .agg(cantidad=("Cantidad", "sum"), monto=("Precio total después del descuento (modificado)", "sum"))
        .sort_values("cantidad", ascending=False)
        .head(top_n)
        .reset_index()
        .sort_values("cantidad")
    )
    fig = px.bar(
        by_product,
        x="cantidad",
        y="Nombre de producto",
        orientation="h",
        text=by_product["cantidad"].apply(lambda v: f"{v:,.0f}"),
        labels={"cantidad": "Piezas vendidas", "Nombre de producto": ""},
        title=f"Top {top_n} productos del día",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(
        font=dict(size=11),
        yaxis=dict(tickfont=dict(size=9)),
        xaxis=dict(visible=False),
        height=300,
    )
    return _fig_to_html(fig)


def build_category_chart(categoria_df: pd.DataFrame, target_date, color_map: dict):
    if categoria_df.empty:
        return None
    day = categoria_df[categoria_df["fecha"] == target_date]
    if day.empty:
        return None
    by_cat = day.groupby("Clasificación")["Monto"].sum().reset_index()
    fig = px.pie(
        by_cat,
        names="Clasificación",
        values="Monto",
        title="Ventas por categoría",
        hole=0.4,
        color="Clasificación",
        color_discrete_map=color_map,
    )
    return _fig_to_html(fig)


def build_top_categoria_charts(categoria_df: pd.DataFrame, target_date, top_n=10):
    """Devuelve una lista de (nombre_categoria, html_grafico) — un top N de
    productos por cada categoría con ventas ese día, ordenadas de mayor a
    menor venta total."""
    if categoria_df.empty:
        return []
    day = categoria_df[categoria_df["fecha"] == target_date]
    if day.empty:
        return []

    # Orden de categorías por venta total del día (de mayor a menor)
    orden_categorias = (
        day.groupby("Clasificación")["Monto"].sum().sort_values(ascending=False).index.tolist()
    )

    resultados = []
    for categoria in orden_categorias:
        sub = day[day["Clasificación"] == categoria]
        by_product = (
            sub.groupby("Nombre de producto")
            .agg(cantidad=("Cantidad", "sum"))
            .reset_index()
            .sort_values("cantidad", ascending=False)
            .head(top_n)
            .sort_values("cantidad")
        )
        if by_product.empty:
            continue
        fig = px.bar(
            by_product,
            x="cantidad",
            y="Nombre de producto",
            orientation="h",
            text=by_product["cantidad"].apply(lambda v: f"{v:,.0f}"),
            labels={"cantidad": "Piezas vendidas", "Nombre de producto": ""},
            title=f"Top {top_n} — {categoria.title()}",
        )
        fig.update_traces(textposition="outside")
        height = max(160, 35 * len(by_product) + 60)
        fig.update_layout(
            font=dict(size=11),
            yaxis=dict(tickfont=dict(size=9)),
            xaxis=dict(visible=False),
            height=height,
        )
        resultados.append((f"cat-{_slug(categoria)}", _fig_to_html(fig)))
    return resultados


def build_comparativa_chart(orders_df: pd.DataFrame, target_date, days=14):
    history = orders_df[~orders_df["es_reembolso"]]
    daily = (
        history.groupby("fecha")["Monto total de orden"]
        .agg(ticket_promedio="mean", ventas_totales="sum")
        .reset_index()
        .sort_values("fecha")
        .tail(days)
    )
    if len(daily) < 2:
        return None
    daily["fecha"] = daily["fecha"].astype(str)
    fig = px.line(
        daily,
        x="fecha",
        y="ticket_promedio",
        markers=True,
        labels={"fecha": "", "ticket_promedio": "Ticket promedio ($)"},
        title=f"Ticket promedio — últimos {len(daily)} días",
    )
    return _fig_to_html(fig)


DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def compute_forecast(items_df: pd.DataFrame, categoria_df: pd.DataFrame, forecast_date) -> dict:
    """Calcula cantidades sugeridas de producción para `forecast_date`.

    Para cada producto, usa el promedio de piezas vendidas en días con el
    mismo día de la semana que `forecast_date` (si hay al menos 2
    registrados); si no, usa el promedio general de todos los días con
    historial. Devuelve un dict con metadatos + lista de (categoria,
    [productos]) ordenada por categoría y cantidad descendente.
    """
    forecast_ts = pd.Timestamp(forecast_date)
    dia_semana = DIAS_SEMANA[forecast_ts.dayofweek]

    if items_df.empty:
        return {
            "categorias": [],
            "dia_semana": dia_semana,
            "dias_mismo_dia": 0,
            "dias_totales": 0,
        }

    df = items_df[~items_df["es_reembolso"]].copy()
    df["nombre_base"] = df["Nombre de producto"].apply(_nombre_base)
    df["fecha_dt"] = pd.to_datetime(df["fecha"])
    df["dia_semana"] = df["fecha_dt"].dt.dayofweek

    daily = df.groupby(["fecha_dt", "dia_semana", "nombre_base"])["Cantidad"].sum().reset_index()

    dias_totales = daily["fecha_dt"].nunique()
    same_dow = daily[daily["dia_semana"] == forecast_ts.dayofweek]
    dias_mismo_dia = same_dow["fecha_dt"].nunique()

    avg_overall = daily.groupby("nombre_base")["Cantidad"].mean()
    avg_same_dow = same_dow.groupby("nombre_base")["Cantidad"].mean()

    productos = sorted(daily["nombre_base"].unique())
    rows = []
    for p in productos:
        if dias_mismo_dia >= 2 and p in avg_same_dow.index:
            valor = avg_same_dow[p]
        else:
            valor = avg_overall.get(p, 0)
        cantidad = max(0, round(valor))
        if cantidad > 0:
            rows.append({"producto": p, "cantidad_sugerida": cantidad})

    fc = pd.DataFrame(rows)

    # Mapa producto base -> categoría (usando todo el histórico)
    if not categoria_df.empty and not fc.empty:
        cat_map_df = categoria_df.copy()
        cat_map_df["nombre_base"] = cat_map_df["Nombre de producto"].apply(_nombre_base)
        cat_map = (
            cat_map_df.groupby("nombre_base")["Clasificación"]
            .agg(lambda s: s.mode().iloc[0] if not s.mode().empty else "OTROS")
            .to_dict()
        )
        fc["categoria"] = fc["producto"].map(cat_map).fillna("OTROS")
    elif not fc.empty:
        fc["categoria"] = "OTROS"

    categorias = []
    if not fc.empty:
        for categoria, grupo in fc.groupby("categoria"):
            grupo = grupo.sort_values("cantidad_sugerida", ascending=False)
            categorias.append((categoria, grupo.to_dict("records")))
        # Ordena las categorías por la cantidad total sugerida (mayor a menor),
        # pero ALIMENTOS siempre va primero (referencia rápida para producción).
        categorias.sort(key=lambda c: sum(p["cantidad_sugerida"] for p in c[1]), reverse=True)
        categorias.sort(key=lambda c: c[0] != "ALIMENTOS")

    return {
        "categorias": categorias,
        "dia_semana": dia_semana,
        "dias_mismo_dia": dias_mismo_dia,
        "dias_totales": dias_totales,
    }


def _render_pronostico(env, data, latest_date, generated_at):
    """Genera docs/pronostico.html y docs/pronostico.json con el plan de
    producción sugerido para el día siguiente al más reciente."""
    items_df, categoria_df = data["items"], data["categoria"]
    forecast_date = pd.Timestamp(latest_date) + pd.Timedelta(days=1)
    # La cafetería no abre domingo: si el día siguiente es domingo, el plan
    # de producción es para el lunes.
    if forecast_date.dayofweek == 6:
        forecast_date += pd.Timedelta(days=1)

    forecast = compute_forecast(items_df, categoria_df, forecast_date)

    template = env.get_template("pronostico_template.html")
    html = template.render(
        store_name="Seed Café",
        fecha_objetivo=forecast_date.strftime("%d-%m-%Y"),
        generated_at=generated_at,
        categorias=forecast["categorias"],
        dia_semana=forecast["dia_semana"],
        dias_mismo_dia=forecast["dias_mismo_dia"],
        dias_totales=forecast["dias_totales"],
    )
    out_path = os.path.join(DOCS_DIR, "pronostico.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Generado: {out_path}")

    # JSON para integración futura con la app de inventario
    productos_json = []
    for categoria, productos in forecast["categorias"]:
        for p in productos:
            productos_json.append({
                "producto": p["producto"],
                "categoria": categoria,
                "cantidad_sugerida": int(p["cantidad_sugerida"]),
            })
    payload = {
        "fecha_objetivo": forecast_date.strftime("%Y-%m-%d"),
        "dia_semana": forecast["dia_semana"],
        "generado": generated_at,
        "dias_historial_mismo_dia": forecast["dias_mismo_dia"],
        "dias_historial_total": forecast["dias_totales"],
        "productos": productos_json,
    }
    json_path = os.path.join(DOCS_DIR, "pronostico.json")
    with open(json_path, "w", encoding="utf-8") as f:
        import json
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"  Generado: {json_path}")


def _render_one(template, data, target_date, all_dates, generated_at, category_color_map, milk_color_map):
    """Genera el HTML de un día y lo guarda en docs/YYYY-MM-DD.html."""
    orders_df, items_df, categoria_df = data["orders"], data["items"], data["categoria"]
    idx = list(all_dates).index(target_date)

    prev_date = all_dates[idx - 1] if idx > 0 else None
    next_date = all_dates[idx + 1] if idx < len(all_dates) - 1 else None

    prev_url = f"{prev_date}.html" if prev_date else None
    next_url = f"{next_date}.html" if next_date else "index.html" if next_date is None and idx < len(all_dates) - 1 else None

    kpis = compute_kpis(orders_df, target_date)
    charts = {
        "hourly": build_hourly_chart(orders_df, target_date),
        "hourly_category": build_hourly_category_chart(orders_df, items_df, categoria_df, target_date, category_color_map),
        "top_products": build_top_products_chart(items_df, target_date),
        "milk": build_milk_chart(items_df, target_date, milk_color_map),
        "category": build_category_chart(categoria_df, target_date, category_color_map),
        "comparativa": build_comparativa_chart(orders_df, target_date),
    }

    top_categoria_charts = build_top_categoria_charts(categoria_df, target_date)

    html = template.render(
        store_name="Seed Café",
        target_date=target_date.strftime("%d-%m-%Y"),
        generated_at=generated_at,
        kpis=kpis,
        charts=charts,
        top_categoria_charts=top_categoria_charts,
        prev_url=prev_url,
        next_url=next_url,
    )
    return html


def render_report(target_date=None):
    data = dl.load_all_data(DATA_DIR)
    orders_df, items_df, categoria_df = data["orders"], data["items"], data["categoria"]

    if orders_df.empty:
        raise SystemExit("No hay datos de órdenes en la carpeta 'data'. Nada que reportar.")

    all_dates = dl.available_dates(orders_df)
    latest = dl.latest_date(orders_df)
    generated_at = pd.Timestamp.now(tz="America/Mexico_City").strftime("%d-%m-%Y %H:%M")

    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("report_template.html")

    os.makedirs(DOCS_DIR, exist_ok=True)

    # Mapas de color fijos (mismo color para la misma categoría/tipo de leche
    # en todos los días, calculados sobre todo el histórico disponible)
    category_color_map = _build_color_map(categoria_df["Clasificación"]) if not categoria_df.empty else {}
    milk_color_map = (
        _build_color_map(items_df["Nombre de producto"].apply(_tipo_leche)) if not items_df.empty else {}
    )

    # Genera una página por cada fecha disponible
    for d in all_dates:
        html = _render_one(template, data, d, all_dates, generated_at, category_color_map, milk_color_map)
        out_path = os.path.join(DOCS_DIR, f"{d}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  Generado: {out_path}")

    # index.html = día más reciente (sin botón → para no ir al futuro)
    html_latest = _render_one(template, data, latest, all_dates, generated_at, category_color_map, milk_color_map)
    # Quita el link "siguiente" en index.html (ya es el más reciente)
    idx_path = os.path.join(DOCS_DIR, "index.html")
    with open(idx_path, "w", encoding="utf-8") as f:
        f.write(html_latest)
    print(f"Reporte principal: {idx_path} (fecha: {latest})")

    # Plan de producción / pronóstico para el día siguiente
    _render_pronostico(env, data, latest, generated_at)

    return idx_path


if __name__ == "__main__":
    render_report()
