"""Extrae el cierre diario de RecoPOS sin navegador (para correr en GitHub Actions).

Hace login (con CAPTCHA resuelto vía Telegram SOLO cuando hace falta — ver
`obtener_token`), trae las órdenes del día y el detalle de productos por
orden, y escribe `data_txt/cierre_YYYY-MM-DD.txt` en el mismo formato que ya
consume `data_loader.py`.

Corre automático en cada tick del schedule — YA NO espera que nadie escriba
"cierre" en Telegram. El token de sesión se guarda en TOKEN_FILE (persistido
entre corridas por el workflow vía actions/cache) y se reutiliza mientras
siga vigente; el CAPTCHA solo se pide cuando el token guardado ya no sirve.

Variables de entorno requeridas:
  RECOPOS_SHOP_ID, RECOPOS_USER, RECOPOS_PASSWORD
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import datetime as dt
import json
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
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", ".recopos_token.json")

# Sesión compartida para todo el flujo de login: RecoPOS liga la validez del
# CAPTCHA a la cookie de sesión con la que se pidió la imagen, no solo al
# codeUuid. Pedir la imagen y mandar el login con peticiones sueltas (sin
# cookies en común) hace que el login falle siempre, sin importar si el
# código se leyó bien.
SESSION = requests.Session()


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
        r = SESSION.get(f"{BASE_URL}/admin/captchaImage", timeout=15)
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
                        return txt, uuid

    fail(f"sin respuesta al CAPTCHA tras {CAPTCHA_MAX_MIN} minutos reenviando intentos")


def leer_token_guardado() -> str | None:
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("token")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


def guardar_token(token: str) -> None:
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump({"token": token, "guardado": dt.datetime.now().isoformat()}, f)


def token_valido(token: str) -> bool:
    """Prueba el token guardado con una llamada barata (rango de fechas absurdo,
    0 filas esperadas) — evita gastar una consulta real solo para validar."""
    try:
        r = requests.post(
            f"{BASE_URL}/admin/baigong/order/list",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "shopId": SHOP_ID,
                "beginTime": "01-01-2000 00:00:00",
                "endTime": "01-01-2000 00:00:01",
                "pageNum": 1,
                "pageSize": 1,
            },
            timeout=15,
        )
        if r.status_code in (401, 403):
            return False
        data = r.json()
        # RecoPOS a veces responde 200 HTTP con un código de error de sesión en el body.
        code = data.get("code")
        return code is None or code == 200
    except Exception:
        return False


def login() -> str:
    """Reutiliza el token guardado de una corrida anterior si sigue vigente —
    así el CAPTCHA solo se pide cuando de verdad hace falta, no en cada corrida."""
    guardado = leer_token_guardado()
    if guardado and token_valido(guardado):
        print("Token de RecoPOS guardado sigue vigente — se reutiliza, sin CAPTCHA.")
        return guardado

    code, uuid = resolver_captcha_por_telegram()
    r = SESSION.post(
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
    guardar_token(token)
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


MARCADOR_LIQUIDACION = "CONSUMO SEMANAL"
UMBRAL_REVISAR_MXN = 50  # abajo de esto no vale la pena avisar: es ruido de operación


def explicar_diferencias(orders: list[dict], items: list[dict]) -> tuple[list[str], float]:
    """Clasifica por qué el detalle de productos no cuadra con el total de la orden.

    El total de la orden y la suma de sus productos casi nunca coinciden, y
    hasta ahora eso disparaba la misma alerta genérica TODOS los días — con lo
    que dejó de significar nada. Las causas conocidas son legítimas:

      • Propina: el total queda exactamente 10% o 15% arriba de los productos.
      • Liquidación semanal (Farmacadel): se registra un producto de monto fijo
        por el acuerdo de alimentos para su personal, pero se cobra lo que de
        verdad consumieron esa semana, que casi siempre es menos.
      • Cortesía / programa de lealtad: la orden trae un producto en $0.
      • Uber Eats: el precio en la plataforma no es el de mostrador, así que el
        cobro casi nunca coincide con la suma de los productos.

    Lo que queda fuera de esas cuatro se reporta aparte, separando si se cobró
    de MENOS (descuento) o de MÁS. Eso es lo único que amerita revisarse.
    """
    por_orden: dict[str, float] = {}
    productos_de: dict[str, list[dict]] = {}
    for it in items:
        oid = str(it["orden"])
        signo = -1 if it["refund"] else 1
        por_orden[oid] = por_orden.get(oid, 0.0) + signo * float(it["monto"] or 0)
        productos_de.setdefault(oid, []).append(it)

    causas: dict[str, list[float]] = {
        "propina": [], "liquidación": [], "cortesía": [], "uber": [],
        "cobrado de menos": [], "cobrado de más": [],
    }
    for o in orders:
        oid = str(o.get("orderNumber"))
        total = float(o.get("actualSum") or o.get("orderMoney") or o.get("totalSum") or 0)
        prods = por_orden.get(oid)
        if prods is None or abs(total - prods) < 0.01:
            continue
        dif = total - prods
        nombres = " ".join((p.get("producto") or "").upper() for p in productos_de.get(oid, []))
        pago = (o.get("paymentName") or o.get("payTypeName") or "").upper()
        if prods and any(abs(total - prods * f) < 0.02 for f in (1.10, 1.15)):
            causas["propina"].append(dif)
        elif MARCADOR_LIQUIDACION in nombres:
            causas["liquidación"].append(dif)
        elif any(float(p.get("monto") or 0) == 0 for p in productos_de.get(oid, [])):
            causas["cortesía"].append(dif)
        elif "UBER" in pago:
            causas["uber"].append(dif)
        else:
            causas["cobrado de menos" if dif < 0 else "cobrado de más"].append(dif)

    etiquetas = {
        "propina": "🪙 Propinas",
        "liquidación": "🧾 Liquidación semanal",
        "cortesía": "🎁 Cortesías/lealtad",
        "uber": "🛵 Uber Eats (precio de plataforma)",
        "cobrado de menos": "🔻 Cobrado de menos",
        "cobrado de más": "🔺 Cobrado de más",
    }
    lineas = [
        f"{etiquetas[k]}: {len(v)} orden(es), ${sum(v):+,.2f}"
        for k, v in causas.items()
        if v
    ]
    revisar = sum(causas["cobrado de menos"]) + sum(causas["cobrado de más"])
    return lineas, revisar


def notificar_telegram(fecha: dt.date, r: dict, items: list[dict], archivo: str, orders: list[dict] | None = None) -> None:
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
    dif_total = r["totalVentas"] - total_items

    # Solo se avisa de lo que NO tiene explicación conocida. Antes se comparaba
    # el total a secas, así que la alerta saltaba todos los días por propinas y
    # liquidaciones normales y acabó siendo ruido. Con el umbral en $50, de 57
    # días de histórico solo 7 habrían levantado la mano.
    if orders:
        lineas_dif, revisar = explicar_diferencias(orders, items)
        if abs(revisar) >= UMBRAL_REVISAR_MXN:
            bloque = f"⚠️ Revisar ${abs(revisar):,.2f} sin explicación:\n" + "\n".join(f"  {l}" for l in lineas_dif)
        elif lineas_dif:
            bloque = "✅ Diferencias, todas normales:\n" + "\n".join(f"  {l}" for l in lineas_dif)
        else:
            bloque = "✅ Órdenes y productos cuadran"
    else:
        bloque = f"{'✅' if abs(dif_total) < 5 else '⚠️'} Match órdenes/productos: {'OK' if abs(dif_total) < 5 else 'revisar diff'}"

    msg = (
        f"✅ SEED CAFÉ — Cierre Diario\n📅 {fecha.isoformat()}\n\n"
        f"💰 Total ventas: ${r['totalVentas']:,.2f}\n"
        f"📦 Órdenes: {r['totalOrdenes']} | Ticket prom: ${r['ticketProm']:.2f}\n"
        f"⏰ Operación: {r['horaInicio']} – {r['horaFin']}\n\n"
        f"🏆 Top 5 productos:\n{top_lines}\n\n"
        f"💳 Por forma de pago:\n{pago_lines}\n\n"
        f"{bloque}\n"
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


BACKFILL_VENTANA_DIAS_SIN_HISTORIAL = 7  # si no hay ningún cierre_*.txt todavía


def fechas_a_procesar(objetivo: dt.date) -> list[dt.date]:
    """Día objetivo + cualquier día faltante (sin cierre_*.txt todavía), desde
    el PRIMER día existente hasta el objetivo — revisa huecos en todo ese
    rango, no solo después del último archivo, porque puede haber días
    intermedios sin archivo aunque ya existan días más recientes (p.ej. si una
    corrida falló a mitad de un backfill anterior). Si se pidió una fecha
    explícita (FECHA_OBJETIVO), solo se procesa esa, sin backfill.
    """
    if os.environ.get("FECHA_OBJETIVO", "").strip():
        return [objetivo]

    existentes = fechas_existentes()
    inicio = min(existentes) if existentes else objetivo - dt.timedelta(days=BACKFILL_VENTANA_DIAS_SIN_HISTORIAL)

    faltantes = []
    cursor = inicio
    while cursor <= objetivo:
        # Domingo: Seed Café siempre cierra — ni se procesa ni se cuenta como
        # hueco, así se evita pedirle a la API un día que nunca va a tener
        # órdenes (y que además, antes de este fix, se reintentaba para
        # siempre porque nunca se marcaba como "ya resuelto").
        if cursor not in existentes and cursor.weekday() != 6:
            faltantes.append(cursor)
        cursor += dt.timedelta(days=1)
    return faltantes  # vacío = nada pendiente, no re-extraer


def procesar_fecha(token: str, fecha: dt.date) -> bool:
    """Extrae y guarda el cierre de una fecha. Devuelve True si hubo órdenes.

    Si no hubo órdenes (día abierto pero sin ventas — no debería pasar salvo
    algo raro, ya que domingo se filtra antes de llegar aquí) igual se
    escribe un archivo marcador: sin esto, un día vacío nunca queda
    "resuelto" y se reintenta en cada corrida para siempre.
    """
    orders = extraer_ordenes(token, fecha)
    nombre_archivo = f"cierre_{fecha.isoformat()}.txt"
    ruta = os.path.join(OUT_DIR, nombre_archivo)

    if not orders:
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(
                f"# Cierre Diario — SEED CAFÉ\n## {fecha.isoformat()}\n\n"
                "Sin órdenes registradas este día (tienda cerrada o sin ventas).\n"
                f"Generado: {dt.datetime.now().isoformat()} (recopos_extractor.py)\n"
            )
        tg_send_message(f"ℹ️ SEED CAFÉ — {fecha.isoformat()}: sin órdenes (café cerrado o sin ventas).")
        return False

    items = extraer_items(token, orders)
    r = resumen_pagos(orders)
    contenido = construir_txt(fecha, orders, items, r)

    with open(ruta, "w", encoding="utf-8") as f:
        f.write(contenido)

    notificar_telegram(fecha, r, items, nombre_archivo, orders)
    print(f"OK: {ruta} ({r['totalOrdenes']} órdenes, ${r['totalVentas']:.2f})")
    return True


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    objetivo = fecha_objetivo()
    pendientes = fechas_a_procesar(objetivo)

    if not pendientes:
        print(f"OK — cierre de {objetivo.isoformat()} ya existe, nada que hacer.")
        sys.exit(0)

    if len(pendientes) > 1:
        tg_send_message(
            f"🔄 SEED CAFÉ — Rescatando {len(pendientes)} días sin cierre: "
            + ", ".join(f.isoformat() for f in pendientes)
        )

    # "Éxito" aquí significa "se procesaron las fechas pendientes sin que
    # tronara el script" — un día sin órdenes también es un resultado válido
    # (ver procesar_fecha), no una falla. Si algo truena de verdad (login,
    # CAPTCHA sin respuesta, error de red), fail() ya corta la ejecución
    # antes de llegar aquí.
    token = login()
    for fecha in pendientes:
        procesar_fecha(token, fecha)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write("exito=true\n")


if __name__ == "__main__":
    main()
