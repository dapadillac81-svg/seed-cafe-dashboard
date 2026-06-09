"""Calcula los KPIs del día más reciente y genera docs/index.html con Plotly + Jinja2."""

from __future__ import annotations

import os
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


def build_top_products_chart(items_df: pd.DataFrame, target_date, top_n=10):
    if items_df.empty:
        return None
    day = items_df[(items_df["fecha"] == target_date) & (~items_df["es_reembolso"])]
    if day.empty:
        return None
    by_product = (
        day.groupby("Nombre de producto")
        .agg(cantidad=("Cantidad", "sum"), monto=("Precio total después del descuento (modificado)", "sum"))
        .sort_values("monto", ascending=False)
        .head(top_n)
        .reset_index()
        .sort_values("monto")
    )
    fig = px.bar(
        by_product,
        x="monto",
        y="Nombre de producto",
        orientation="h",
        text=by_product["monto"].apply(lambda v: f"${v:,.0f}"),
        labels={"monto": "Ventas ($)", "Nombre de producto": ""},
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


def render_report(target_date=None):
    data = dl.load_all_data(DATA_DIR)
    orders_df, items_df, categoria_df = data["orders"], data["items"], data["categoria"]

    if orders_df.empty:
        raise SystemExit("No hay datos de órdenes en la carpeta 'data'. Nada que reportar.")

    if target_date is None:
        target_date = dl.latest_date(orders_df)

    kpis = compute_kpis(orders_df, target_date)
    charts = {
        "hourly": build_hourly_chart(orders_df, target_date),
        "top_products": build_top_products_chart(items_df, target_date),
        "category": build_category_chart(categoria_df, target_date),
        "comparativa": build_comparativa_chart(orders_df, target_date),
    }

    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("report_template.html")
    html = template.render(
        store_name="Seed Café",
        target_date=target_date.strftime("%d-%m-%Y"),
        generated_at=pd.Timestamp.now(tz="America/Mexico_City").strftime("%d-%m-%Y %H:%M"),
        kpis=kpis,
        charts=charts,
    )

    os.makedirs(DOCS_DIR, exist_ok=True)
    out_path = os.path.join(DOCS_DIR, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Reporte generado: {out_path} (fecha: {target_date})")
    return out_path


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    target = pd.to_datetime(arg).date() if arg else None
    render_report(target)
