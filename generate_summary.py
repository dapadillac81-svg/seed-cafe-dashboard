"""Genera docs/resumen_analitico.json — resumen estructurado de todos los datos
históricos de Seed Café para análisis en Claude Projects u otras herramientas.

Corre después de generate_report.py en el pipeline de GitHub Actions.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, timedelta

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import data_loader as dl

DATA_DIR = os.path.join(HERE, "data")
TXT_DIR = os.path.join(HERE, "data_txt")
OUT = os.path.join(HERE, "docs", "resumen_analitico.json")

# ── helpers ──────────────────────────────────────────────────────────────────

LECHE_MAP = [
    ("Light",        re.compile(r"leche\s*light|deslc\s*light|light", re.I)),
    ("Deslactosada", re.compile(r"deslact|deslc", re.I)),
    ("Entera",       re.compile(r"entera", re.I)),
    ("Avena",        re.compile(r"avena|oat", re.I)),
    ("Soya",         re.compile(r"soya|soja", re.I)),
    ("Coco",         re.compile(r"coco", re.I)),
    ("Almendra",     re.compile(r"almendra", re.I)),
]
LECHE_ANY = re.compile(r"leche|milk|avena|oat|soya|coco|almendra", re.I)


def _tipo_leche(opciones: str) -> str | None:
    if not LECHE_ANY.search(opciones):
        return None
    for nombre, pat in LECHE_MAP:
        if pat.search(opciones):
            return nombre
    return "Otra"


def _leches_desde_txt() -> dict[str, int]:
    conteo: dict[str, int] = {}
    for fn in sorted(os.listdir(TXT_DIR)):
        if not fn.startswith("cierre_2026") or not fn.endswith(".txt"):
            continue
        with open(os.path.join(TXT_DIR, fn), encoding="utf-8") as f:
            for line in f:
                if not line.startswith("|"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 6:
                    continue
                opciones = parts[3]
                if not opciones or opciones in ("Opciones", "---"):
                    continue
                tipo = _tipo_leche(opciones)
                if tipo:
                    try:
                        cantidad = int(float(parts[4]))
                    except Exception:
                        cantidad = 1
                    conteo[tipo] = conteo.get(tipo, 0) + cantidad
    return conteo


# ── cálculos principales ──────────────────────────────────────────────────────

def resumen_diario(orders: pd.DataFrame) -> list[dict]:
    """Una fila por día con ventas, órdenes y ticket promedio."""
    ventas = orders[~orders["es_reembolso"]]
    por_dia = (
        ventas.groupby("fecha")
        .agg(
            ventas_totales=("Monto total de orden", "sum"),
            num_ordenes=("Monto total de orden", "count"),
            ticket_promedio=("Monto total de orden", "mean"),
        )
        .reset_index()
        .sort_values("fecha")
    )
    reembolsos = (
        orders[orders["es_reembolso"]]
        .groupby("fecha")["Monto total de orden"]
        .agg(reembolsos_monto="sum", reembolsos_count="count")
        .reset_index()
    )
    por_dia = por_dia.merge(reembolsos, on="fecha", how="left")
    por_dia["reembolsos_monto"] = por_dia["reembolsos_monto"].fillna(0).abs()
    por_dia["reembolsos_count"] = por_dia["reembolsos_count"].fillna(0).astype(int)

    rows = []
    for _, r in por_dia.iterrows():
        fecha = r["fecha"]
        dia_semana = fecha.strftime("%A") if hasattr(fecha, "strftime") else str(fecha)
        rows.append({
            "fecha": str(fecha),
            "dia_semana": dia_semana,
            "ventas_totales": round(float(r["ventas_totales"]), 2),
            "num_ordenes": int(r["num_ordenes"]),
            "ticket_promedio": round(float(r["ticket_promedio"]), 2),
            "reembolsos_monto": round(float(r["reembolsos_monto"]), 2),
            "reembolsos_count": int(r["reembolsos_count"]),
        })
    return rows


def resumen_por_dia_semana(diario: list[dict]) -> list[dict]:
    """Promedios agrupados por día de la semana."""
    from collections import defaultdict
    acum: dict[str, dict] = defaultdict(lambda: {"ventas": [], "ordenes": [], "ticket": []})
    for d in diario:
        ds = d["dia_semana"]
        acum[ds]["ventas"].append(d["ventas_totales"])
        acum[ds]["ordenes"].append(d["num_ordenes"])
        acum[ds]["ticket"].append(d["ticket_promedio"])

    orden = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    result = []
    for dia in orden:
        if dia not in acum:
            continue
        v = acum[dia]
        result.append({
            "dia_semana": dia,
            "dias_registrados": len(v["ventas"]),
            "ventas_promedio": round(sum(v["ventas"]) / len(v["ventas"]), 2),
            "ordenes_promedio": round(sum(v["ordenes"]) / len(v["ordenes"]), 1),
            "ticket_promedio": round(sum(v["ticket"]) / len(v["ticket"]), 2),
        })
    return result


def top_productos(items: pd.DataFrame, top_n=20) -> list[dict]:
    ventas = items[~items["es_reembolso"]] if "es_reembolso" in items.columns else items
    col_nombre = "nombre_base" if "nombre_base" in ventas.columns else "Nombre de producto"
    col_cant = "Cantidad"
    col_monto = "Precio total después del descuento"

    agg = (
        ventas.groupby(col_nombre)
        .agg(
            unidades=(col_cant, "sum"),
            ingreso=(col_monto, "sum"),
        )
        .reset_index()
        .sort_values("unidades", ascending=False)
        .head(top_n)
    )
    return [
        {
            "producto": str(r[col_nombre]),
            "unidades": int(r["unidades"]),
            "ingreso": round(float(r["ingreso"]), 2),
        }
        for _, r in agg.iterrows()
    ]


def top_por_categoria(categoria: pd.DataFrame, top_n=10) -> list[dict]:
    col_cat = [c for c in categoria.columns if "clasif" in c.lower() or "categor" in c.lower()][0]
    col_nombre = [c for c in categoria.columns if "nombre" in c.lower() and "producto" in c.lower()]
    col_nombre = col_nombre[0] if col_nombre else "Nombre de producto"
    col_cant = "Cantidad"

    agg = (
        categoria.groupby([col_cat, col_nombre])[col_cant]
        .sum()
        .reset_index()
        .sort_values(col_cant, ascending=False)
    )

    result = []
    for cat, grupo in agg.groupby(col_cat):
        top = grupo.head(top_n)
        result.append({
            "categoria": str(cat),
            "top_productos": [
                {"producto": str(r[col_nombre]), "unidades": int(r[col_cant])}
                for _, r in top.iterrows()
            ],
        })
    return result


def tendencia_ticket(diario: list[dict]) -> dict:
    """Tendencia lineal del ticket promedio (últimos 30 días)."""
    import math
    ultimos = diario[-30:] if len(diario) >= 30 else diario
    if len(ultimos) < 2:
        return {}
    tickets = [d["ticket_promedio"] for d in ultimos]
    n = len(tickets)
    x = list(range(n))
    mx, my = sum(x) / n, sum(tickets) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, tickets))
    den = sum((xi - mx) ** 2 for xi in x)
    slope = num / den if den else 0
    return {
        "slope_por_dia": round(slope, 4),
        "tendencia": "baja" if slope < -0.5 else "sube" if slope > 0.5 else "estable",
        "ticket_inicio_periodo": round(tickets[0], 2),
        "ticket_fin_periodo": round(tickets[-1], 2),
        "dias_analizados": n,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("Cargando datos...")
    data = dl.load_all_data(DATA_DIR)
    orders = data["orders"]
    items = data["items"]
    categoria = data["categoria"]

    # Fechas
    ventas = orders[~orders["es_reembolso"]]
    fecha_min = str(ventas["fecha"].min())
    fecha_max = str(ventas["fecha"].max())
    total_dias = int(ventas["fecha"].nunique())

    # Bloques
    diario = resumen_diario(orders)
    por_dia_semana = resumen_por_dia_semana(diario)
    productos = top_productos(items)
    por_categoria = top_por_categoria(categoria)
    leches = _leches_desde_txt()
    total_leches = sum(leches.values())
    leches_pct = {
        k: {"unidades": v, "pct": round(v / total_leches * 100, 1)}
        for k, v in sorted(leches.items(), key=lambda x: -x[1])
    } if total_leches else {}

    tendencia = tendencia_ticket(diario)

    # KPIs globales
    total_ventas_global = sum(d["ventas_totales"] for d in diario)
    ticket_global = total_ventas_global / sum(d["num_ordenes"] for d in diario) if diario else 0
    mejor_dia = max(diario, key=lambda d: d["ventas_totales"]) if diario else {}
    peor_dia = min(diario, key=lambda d: d["ventas_totales"]) if diario else {}

    resumen = {
        "generado": date.today().isoformat(),
        "negocio": "Seed Café",
        "periodo": {"inicio": fecha_min, "fin": fecha_max, "dias_con_ventas": total_dias},
        "kpis_globales": {
            "ventas_totales": round(total_ventas_global, 2),
            "ticket_promedio_global": round(ticket_global, 2),
            "total_ordenes": sum(d["num_ordenes"] for d in diario),
            "mejor_dia": mejor_dia,
            "peor_dia": peor_dia,
        },
        "tendencia_ticket_promedio": tendencia,
        "ventas_por_dia_semana": por_dia_semana,
        "historico_diario": diario,
        "top_20_productos": productos,
        "top_productos_por_categoria": por_categoria,
        "uso_de_leches": {
            "total_bebidas_registradas": total_leches,
            "nota": "Solo desde jun-12 (inicio de cierres individuales vía API)",
            "desglose": leches_pct,
        },
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2, default=str)

    size_kb = os.path.getsize(OUT) / 1024
    print(f"OK — {OUT} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
