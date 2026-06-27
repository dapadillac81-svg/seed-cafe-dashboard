"""Extrae el cierre diario de RecoPOS sin navegador (para correr en GitHub Actions).

Replica el flujo del SKILL `recopos-cierre-diario`: resuelve el CAPTCHA via Telegram,
hace login, trae las órdenes del día y el detalle de productos por orden, y escribe
`data_txt/cierre_YYYY-MM-DD.txt` en el mismo formato que ya consume `data_loader.py`.

Variables de entorno requeridas:
  RECOPOS_SHOP_ID, RECOPOS_USER, RECOPOS_PASSWORD
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sys
import time

import requests

BASE_URL = "https://s.recoposmx.com"
SHOP_ID = os.environ["RECOPOS_SHOP_ID"]
USER = os.environ["RECOPOS_USER"]
PASSWORD = os.environ["RECOPOS_PASSWORD"]
TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT = os.environ["TELEGRAM_CHAT_ID"]

DIAS = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_txt")


def tg_send_message(text: str) -> None:
    requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT, "text": text},
        timeout=15,
    )


def tg_send_photo_b64(img_b64: str, caption: str) -> None:
    import base64

    photo = base64.b64decode(img_b64)
    requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
        data={"chat_id": TG_CHAT, "caption": caption, "parse_mode": "HTML"},
        files={"photo": ("captcha.jpg", photo, "image/jpeg")},
        timeout=15,
    )


def fail(mensaje: str) -> None:
    tg_send_message(f"❌ SEED CAFÉ — Error Cierre Diario\n\nError: {mensaje}\n⏰ {dt.datetime.now().isoformat()}")
    sys.exit(0)  # no se trata como fallo del workflow: simplemente no hubo cierre esta noche


CAPTCHA_CICLO_MIN = 15  # minutos que espera por cada imagen antes de mandar una nueva
CAPTCHA_MAX_MIN = 120  # tope total: ~2 horas (máx. 8 mensajes) reenviando captcha cada ciclo


def _offset_inicial() -> int:
    r = requests.get(
        f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
        params={"limit": 1, "offset": -1},
        timeout=15,
    )
    result = r.json().get("result", [])
    return result[-1]["update_id"] + 1 if result else 0


def resolver_captcha_por_telegram() -> tuple[str, str]:
    """Pide un CAPTCHA y espera respuesta por Telegram. Si no contestas a tiempo,
    pide uno nuevo (el anterior ya venció en RecoPOS) y vuelve a esperar — así, sin
    importar cuándo abras el chat, hay un CAPTCHA vigente listo para resolver.
    """
    offset = _offset_inicial()
    ciclos = CAPTCHA_MAX_MIN // CAPTCHA_CICLO_MIN

    for ciclo in range(ciclos):
        r = requests.get(f"{BASE_URL}/admin/captchaImage", timeout=15)
        data = r.json()
        img_b64, uuid = data["img"], data["uuid"]

        intro = "🔐 <b>SEED CAFÉ — Login Recopos</b>" if ciclo == 0 else "🔄 <b>SEED CAFÉ — Nuevo intento de login</b>\n(el código anterior ya venció)"
        tg_send_photo_b64(
            img_b64,
            f"{intro}\n\nEl proceso automático necesita acceso.\n"
            "<b>Responde con los caracteres que ves en esta imagen</b> para continuar.\n\n"
            f"⏰ Tienes {CAPTCHA_CICLO_MIN} minutos — si no contestas, te mando uno nuevo "
            "automáticamente y puedes resolverlo en cuanto lo veas.",
        )

        for _ in range(CAPTCHA_CICLO_MIN * 6):  # intervalos de 10s
            time.sleep(10)
            r = requests.get(
                f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                params={"offset": offset, "limit": 10},
                timeout=15,
            )
            for u in r.json().get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message", {})
                if str(msg.get("chat", {}).get("id")) == str(TG_CHAT):
                    txt = (msg.get("text") or "").strip()
                    if 3 <= len(txt) <= 6:
                        return txt.upper(), uuid

    fail(f"sin respuesta al CAPTCHA tras {CAPTCHA_MAX_MIN} minutos reenviando intentos")


def login() -> str:
    code, uuid = resolver_captcha_por_telegram()
    r = requests.post(
        f"{BASE_URL}/admin/typeLogin",
        json={
            "userName": USER,
            "shopId": SHOP_ID,
            "passWord": PASSWORD,
            "code": code,
            "codeUuid": uuid,
            "loginType": "01",
        },
        timeout=15,
    )
    data = r.json()
    token = data.get("data", {}).get("token")
    if not token:
        fail(f"login fallido: {data}")
    return token


def fecha_objetivo() -> dt.date:
    override = os.environ.get("FECHA_OBJETIVO", "").strip()
    if override:
        return dt.date.fromisoformat(override)

    # GitHub Actions corre en UTC; el SKILL de cowork corre con la hora local
    # de la PC (MX). Usamos siempre la hora real de Ciudad de México para que
    # la lógica "hoy si son >=9pm, si no ayer" sea consistente sin importar
    # dónde se ejecute el script.
    try:
        from zoneinfo import ZoneInfo
        ahora = dt.datetime.now(ZoneInfo("America/Mexico_City"))
    except Exception:
        ahora = dt.datetime.now()
    if ahora.hour >= 21:
        return ahora.date()
    return ahora.date() - dt.timedelta(days=1)


def extraer_ordenes(token: str, fecha: dt.date) -> list[dict]:
    fecha_api = fecha.strftime("%d-%m-%Y")
    r = requests.post(
        f"{BASE_URL}/admin/baigong/order/list",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "shopId": SHOP_ID,
            "beginTime": f"{fecha_api} 00:00:00",
            "endTime": f"{fecha_api} 23:59:59",
            "pageNum": 1,
            "pageSize": 500,
        },
        timeout=30,
    )
    return r.json().get("rows", [])


def extraer_items(token: str, orders: list[dict]) -> list[dict]:
    items = []
    for o in orders:
        # El monto de la orden (lista de pagos) es la fuente de verdad para saber
        # si es un reembolso: RecoPOS marca `refundOrderInfoList` en el detalle de
        # la orden ORIGINAL cuando luego se generó un reembolso asociado (común en
        # Uber Eats) — eso NO significa que esta orden sea el reembolso. La entrada
        # que realmente es el reembolso aparece aparte en la lista, con monto < 0.
        monto_orden = float(o.get("actualSum") or o.get("orderMoney") or o.get("totalSum") or 0)
        is_refund = monto_orden < 0

        r = requests.get(
            f"{BASE_URL}/admin/baigong/order/info/{o['orderId']}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        d = r.json()
        for oi in d.get("data", {}).get("orderInfoList", []):
            for p in oi.get("products", []):
                items.append({
                    "orden": o.get("orderNumber"),
                    "producto": p.get("productName"),
                    "opciones": p.get("options") or "",
                    "cantidad": p.get("count"),
                    "monto": p.get("totalAmount"),
                    "refund": is_refund,
                })
    return items


def resumen_pagos(orders: list[dict]) -> dict:
    montos = [float(o.get("actualSum") or o.get("orderMoney") or o.get("totalSum") or 0) for o in orders]
    total_ventas = round(sum(montos), 2)
    total_ordenes = len(orders)
    tiempos = sorted(o["orderCreateTime"] for o in orders if o.get("orderCreateTime"))
    by_pago: dict[str, dict] = {}
    for o, monto in zip(orders, montos):
        metodo = o.get("paymentName") or o.get("payTypeName") or "Desconocido"
        by_pago.setdefault(metodo, {"count": 0, "monto": 0.0})
        by_pago[metodo]["count"] += 1
        by_pago[metodo]["monto"] += monto
    return {
        "totalVentas": total_ventas,
        "totalOrdenes": total_ordenes,
        "ticketProm": round(total_ventas / total_ordenes, 2) if total_ordenes else 0,
        "ticketMin": min(montos) if montos else 0,
        "ticketMax": max(montos) if montos else 0,
        "horaInicio": tiempos[0][11:16] if tiempos else "—",
        "horaFin": tiempos[-1][11:16] if tiempos else "—",
        "byPago": by_pago,
    }


def construir_txt(fecha: dt.date, orders: list[dict], items: list[dict], r: dict) -> str:
    dia_idx = (fecha.weekday() + 1) % 7  # date.weekday(): Lunes=0..Domingo=6 -> DIAS[0]=Domingo
    fecha_texto = f"{DIAS[dia_idx]} {fecha.day} de {MESES[fecha.month - 1]} de {fecha.year}"

    pago_lines = "\n".join(
        f"{m}: {v['count']} órdenes — ${v['monto']:.2f} ({round(v['monto'] / r['totalVentas'] * 100) if r['totalVentas'] else 0}%)"
        for m, v in sorted(r["byPago"].items(), key=lambda x: -x[1]["monto"])
    )

    por_producto: dict[str, dict] = {}
    for it in items:
        monto = float(it["monto"] or 0)
        signo = -1 if it["refund"] else 1
        d = por_producto.setdefault(it["producto"], {"cantidad": 0, "monto": 0.0})
        d["cantidad"] += signo * it["cantidad"]
        d["monto"] += signo * monto
    top5 = sorted(por_producto.items(), key=lambda x: -x[1]["cantidad"])[:5]
    top5_lines = "\n".join(f"{n}: {v['cantidad']} uds — ${v['monto']:.2f}" for n, v in top5)

    ordenes_table = "\n".join(
        f"| {o.get('orderNumber')} | {float(o.get('actualSum') or o.get('orderMoney') or o.get('totalSum') or 0):.2f} "
        f"| {o.get('orderTable') or o.get('tableCode') or ''} | {o.get('orderCreateTime') or ''} "
        f"| {o.get('paymentName') or o.get('payTypeName') or ''} | Orden en TPV | orden |"
        for o in orders
    )
    productos_table = "\n".join(
        f"| {it['orden']} | {it['producto']} | {it['opciones']} | {it['cantidad']} "
        f"| {float(it['monto'] or 0):.2f} | {'Sí' if it['refund'] else 'No'} |"
        for it in items
    )

    total_items = sum((-1 if it["refund"] else 1) * float(it["monto"] or 0) for it in items)
    diff = abs(total_items - r["totalVentas"])
    match_str = "OK" if diff < 5 else f"DIFERENCIA ${diff:.2f}"

    return f"""# Cierre Diario — SEED CAFÉ
## {fecha_texto}

---

## RESUMEN DEL DÍA

Tienda: SEED CAFÉ ({SHOP_ID})
Horario operativo: {r['horaInicio']} – {r['horaFin']}
Total de órdenes: {r['totalOrdenes']}
Total ventas: ${r['totalVentas']:.2f}
Ticket promedio: ${r['ticketProm']:.2f}
Ticket mínimo: ${r['ticketMin']:.2f}
Ticket máximo: ${r['ticketMax']:.2f}

---

## POR MÉTODO DE PAGO

{pago_lines}
TOTAL: {r['totalOrdenes']} órdenes — ${r['totalVentas']:.2f}

---

## TOP 5 PRODUCTOS

{top5_lines}

---

## DETALLE DE ÓRDENES

| No. Orden | Monto | Folio/Mesa | Hora | Pago | Fuente | Tipo |
|---|---|---|---|---|---|---|
{ordenes_table}

---

## DETALLE DE PRODUCTOS

| No. Orden | Producto | Opciones | Cantidad | Monto | Reembolso |
|---|---|---|---|---|---|
{productos_table}

---

## NOTAS

- Datos: API de órdenes (`/admin/baigong/order/list`) + detalle de productos por orden (`/admin/baigong/order/info`)
- El Cierre formal no fue ejecutado por el cajero
- Match órdenes vs productos: {match_str}
- Generado: {dt.datetime.now().isoformat()} (recopos_extractor.py / GitHub Actions)
"""


def notificar_telegram(fecha: dt.date, r: dict, items: list[dict], archivo: str) -> None:
    por_producto: dict[str, dict] = {}
    for it in items:
        monto = float(it["monto"] or 0)
        signo = -1 if it["refund"] else 1
        d = por_producto.setdefault(it["producto"], {"cantidad": 0, "monto": 0.0})
        d["cantidad"] += signo * it["cantidad"]
        d["monto"] += signo * monto
    top5 = sorted(por_producto.items(), key=lambda x: -x[1]["cantidad"])[:5]
    top_lines = "\n".join(f"• {n}: {v['cantidad']} uds — ${v['monto']:.2f}" for n, v in top5)
    pago_lines = "\n".join(
        f"• {m}: {v['count']} órdenes — ${v['monto']:.2f} ({round(v['monto'] / r['totalVentas'] * 100) if r['totalVentas'] else 0}%)"
        for m, v in sorted(r["byPago"].items(), key=lambda x: -x[1]["monto"])
    )
    total_items = sum((-1 if it["refund"] else 1) * float(it["monto"] or 0) for it in items)
    match_ok = abs(total_items - r["totalVentas"]) < 5

    msg = (
        f"✅ SEED CAFÉ — Cierre Diario\n📅 {fecha.isoformat()}\n\n"
        f"💰 Total ventas: ${r['totalVentas']:,.2f}\n"
        f"📦 Órdenes: {r['totalOrdenes']} | Ticket prom: ${r['ticketProm']:.2f}\n"
        f"⏰ Operación: {r['horaInicio']} – {r['horaFin']}\n\n"
        f"🏆 Top 5 productos:\n{top_lines}\n\n"
        f"💳 Por forma de pago:\n{pago_lines}\n\n"
        f"{'✅' if match_ok else '⚠️'} Match órdenes/productos: {'OK' if match_ok else 'revisar diff'}\n"
        f"📁 {archivo} guardado (vía GitHub Actions ☁️)"
    )
    tg_send_message(msg)


def fechas_existentes() -> set[dt.date]:
    existentes = set()
    if os.path.isdir(OUT_DIR):
        for fn in os.listdir(OUT_DIR):
            m = re.match(r"cierre_(\d{4}-\d{2}-\d{2})\.txt$", fn)
            if m:
                existentes.add(dt.date.fromisoformat(m.group(1)))
    return existentes


def fechas_a_procesar(objetivo: dt.date) -> list[dt.date]:
    """Día objetivo + cualquier día faltante anterior (sin cierre_*.txt todavía),
    desde el último día existente hasta el objetivo. Si se pidió una fecha
    explícita (FECHA_OBJETIVO), solo se procesa esa, sin backfill.
    """
    if os.environ.get("FECHA_OBJETIVO", "").strip():
        return [objetivo]

    existentes = fechas_existentes()
    if not existentes:
        return [objetivo]

    ultimo = max(existentes)
    faltantes = []
    cursor = ultimo + dt.timedelta(days=1)
    while cursor <= objetivo:
        if cursor not in existentes:
            faltantes.append(cursor)
        cursor += dt.timedelta(days=1)
    return faltantes or [objetivo]


def procesar_fecha(token: str, fecha: dt.date) -> bool:
    """Extrae y guarda el cierre de una fecha. Devuelve True si hubo órdenes
    (día procesado) o False si el café no abrió ese día (se omite sin error).
    """
    orders = extraer_ordenes(token, fecha)
    if not orders:
        tg_send_message(f"ℹ️ SEED CAFÉ — {fecha.isoformat()}: sin órdenes (café cerrado o sin ventas), se omite.")
        return False

    items = extraer_items(token, orders)
    r = resumen_pagos(orders)
    contenido = construir_txt(fecha, orders, items, r)

    nombre_archivo = f"cierre_{fecha.isoformat()}.txt"
    ruta = os.path.join(OUT_DIR, nombre_archivo)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(contenido)

    notificar_telegram(fecha, r, items, nombre_archivo)
    print(f"OK: {ruta} ({r['totalOrdenes']} órdenes, ${r['totalVentas']:.2f})")
    return True


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    objetivo = fecha_objetivo()
    pendientes = fechas_a_procesar(objetivo)

    if len(pendientes) > 1:
        tg_send_message(
            f"🔄 SEED CAFÉ — Rescatando {len(pendientes)} días sin cierre: "
            + ", ".join(f.isoformat() for f in pendientes)
        )

    token = login()
    algun_exito = False
    for fecha in pendientes:
        if procesar_fecha(token, fecha):
            algun_exito = True

    if not algun_exito:
        fail(f"sin órdenes en ninguna de las fechas pendientes: {', '.join(f.isoformat() for f in pendientes)}")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write("exito=true\n")


if __name__ == "__main__":
    main()
