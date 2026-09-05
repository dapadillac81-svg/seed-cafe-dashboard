"""Prueba de login a RecoPOS DESDE TU PROPIA COMPUTADORA (no desde GitHub Actions).

Sirve para saber si el problema es que RecoPOS bloquea los intentos de login
que vienen de un servidor de GitHub (EE. UU.) en vez de tu red normal.

Cómo correrlo:
  1. Abre una terminal (PowerShell) en esta carpeta.
  2. Corre:  python test_login_local.py
  3. Te va a pedir shop id, usuario y contraseña — se escriben aquí, en tu
     propia compu, y no se guardan ni se mandan a ningún lado más que a
     RecoPOS directamente.
  4. Te va a abrir la imagen del CAPTCHA en el visor de imágenes de Windows.
     Ciérrala, escribe el código en la terminal y dale Enter.
  5. Te dice si el login funcionó o no, y si no, te muestra el error exacto
     que regresó RecoPOS.
"""

import base64
import getpass
import os
import subprocess
import sys
import tempfile

import requests

BASE_URL = "https://s.recoposmx.com"


def main() -> None:
    shop_id = input("RECOPOS_SHOP_ID: ").strip()
    user = input("RECOPOS_USER: ").strip()
    password = getpass.getpass("RECOPOS_PASSWORD (no se ve al escribir): ")

    session = requests.Session()

    r = session.get(f"{BASE_URL}/admin/captchaImage", timeout=15)
    data = r.json()
    img_b64, uuid = data["img"], data["uuid"]

    img_path = os.path.join(tempfile.gettempdir(), "recopos_captcha.jpg")
    with open(img_path, "wb") as f:
        f.write(base64.b64decode(img_b64))

    print(f"\nAbriendo el CAPTCHA... ({img_path})")
    try:
        os.startfile(img_path)  # Windows
    except AttributeError:
        subprocess.run(["xdg-open", img_path], check=False)

    code = input("\nEscribe EXACTAMENTE los caracteres que ves (respeta mayúsculas/minúsculas): ").strip()

    r = session.post(
        f"{BASE_URL}/admin/typeLogin",
        json={
            "userName": user,
            "shopId": shop_id,
            "passWord": password,
            "code": code,
            "codeUuid": uuid,
            "loginType": "01",
        },
        timeout=15,
    )
    result = r.json()
    token = result.get("data", {}).get("token")

    print("\n--- Resultado ---")
    if token:
        print("✅ LOGIN EXITOSO desde esta computadora.")
        print("Esto confirma que RecoPOS bloquea los intentos desde el servidor de GitHub,")
        print("no que las credenciales o el CAPTCHA estén mal.")
    else:
        print("❌ LOGIN FALLÓ, incluso desde tu propia red.")
        print(f"Respuesta completa de RecoPOS: {result}")
        print("Esto apunta a un problema real de usuario/contraseña o de la cuenta,")
        print("no a un bloqueo por IP del servidor de GitHub.")


if __name__ == "__main__":
    sys.exit(main())
