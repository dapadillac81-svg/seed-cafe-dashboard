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


def _nombre_base(nombre: str) -> str:
    """Quita la variante entre paréntesis (ej. tipo de leche) del nombre del
    producto, para agrupar 'CAPUCCINO/16 OZ (LECHE LIGHT)' y
    'CAPUCCINO/16 OZ（02 LECHE DESLACTOSADA）' bajo 'CAPUCCINO/16 OZ'."""
    return re.sub(r"\s*[（(].*?[）)]\s*$", "", str(nombre)).strip()


def _slug(texto: str) -> str:
    """Convierte un texto en un identificador simple para usar como
    data-chart-id (para recordar la posición de scroll entre días)."""
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", str(texto)).strip("-").lower()
    return texto or "cat"


def _tipo_leche(nombre: str) -> str | None:
    """Extrae el tipo de leche de la variante entre paréntesis, si existe.
    Ej. '...（02 LECHE DESLACTOSADA）' -> 'LECHE DESLACTOSADA'.
    Devuelve None si el producto no trae variante de leche (ej. agua, panes)."""
    m = re.search(r"[（(](.*?)[）)]\s*$", str(nombre))
    if not m:
        return None
    variante = m.group(1).strip()
    # Quita prefijos numéricos tipo "01 ", "02 ", "13 ", "14 +12"
    variante = re.sub(r"^\d+\s*", "", variante)
    variante = re.sub(r"\+\d+$", "", variante).strip()
    if "LECHE" not in variante.upper():
        return None
    return variante.title()


def build_milk_chart(items_df: pd.DataFrame, target_date):
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
    )
    fig = px.pie(
        by_leche,
        names="tipo_leche",
        values="Cantidad",
        title="Tipos de leche pedidos",
        hole=0.4,
    )
    fig.update_traces(textinfo="label+value")
    fig.update_layout(showlegend=False)
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


def build_category_chart(categoria_df: pd.DataFrame, target_date):
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


def _render_one(template, data, target_date, all_dates, generated_at):
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
        "top_products": build_top_products_chart(items_df, target_date),
        "milk": build_milk_chart(items_df, target_date),
        "category": build_category_chart(categoria_df, target_date),
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

    # Genera una página por cada fecha disponible
    for d in all_dates:
        html = _render_one(template, data, d, all_dates, generated_at)
        out_path = os.path.join(DOCS_DIR, f"{d}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  Generado: {out_path}")

    # index.html = día más reciente (sin botón → para no ir al futuro)
    html_latest = _render_one(template, data, latest, all_dates, generated_at)
    # Quita el link "siguiente" en index.html (ya es el más reciente)
    idx_path = os.path.join(DOCS_DIR, "index.html")
    with open(idx_path, "w", encoding="utf-8") as f:
        f.write(html_latest)
    print(f"Reporte principal: {idx_path} (fecha: {latest})")
    return idx_path


if __name__ == "__main__":
    render_report()
