"""Modo demostracion de FaceGuard: el sistema completo, sin base de datos ni camara.

Sirve para mostrar el funcionamiento del servidor y del panel en cualquier
equipo, o en GitHub Codespaces, con solo:

    pip install -r requirements.txt
    python scripts/demo.py

y abrir http://localhost:5000 (usuarios al final de este texto).

Que es real y que es simulado
-----------------------------
* REAL: todo el servidor. La API, el panel, la autenticacion por roles, la
  credencial de la estacion, la maquina de estados de las alertas, el
  escalamiento automatico, la deduplicacion de detecciones, el ingreso y la
  salida, la evidencia y la bitacora son el mismo codigo que corre en
  produccion.
* SIMULADO: la base de datos (se usa el repositorio en memoria de las pruebas,
  que aplica las mismas reglas que PostgreSQL) y la estacion de captura. En
  lugar de una camara con face_recognition y YOLOv8, un hilo envia por HTTP,
  con la credencial de la camara, los mismos mensajes que enviaria la estacion
  real: codificaciones faciales y detecciones de arma con su fotograma.

Por eso el panel muestra una franja que dice "Modo demostracion". Las cifras
de la demostracion no son resultados de evaluacion y no deben reportarse
como tales.

Usuarios:
    guardia@demo.edu        / Guardia-2026
    admin@demo.edu          / Admin-2026
    consulta@demo.edu       / Consulta-2026
"""

from __future__ import annotations

import io
import os
import random
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import numpy as np                 # noqa: E402
import requests                    # noqa: E402

PUERTO = int(os.getenv("PORT", "5000"))
URL = f"http://127.0.0.1:{PUERTO}"
TOKEN = "1.secreto-de-prueba"           # credencial de la camara 1 de la demo
SEGUNDOS_ENTRE_EVENTOS = int(os.getenv("DEMO_SEGUNDOS", "15"))


def preparar():
    """Monta la aplicacion real sobre el repositorio en memoria."""
    os.environ.setdefault("EVIDENCIAS_DIR", str(RAIZ / "evidencias_demo"))

    from app import crear_app, repositorio, seguridad
    from app.config import Config
    from tests.conftest import RepositorioFalso

    repo = RepositorioFalso()
    for nombre in dir(repo):
        if not nombre.startswith("_") and hasattr(repositorio, nombre):
            setattr(repositorio, nombre, getattr(repo, nombre))

    class ConfigDemo(Config):
        SECRET_KEY = os.getenv("SECRET_KEY", "clave-solo-para-la-demo")
        APP_ENV = "demo"
        DEMO = True
        MINUTOS_ESCALAMIENTO = 1          # para ver el escalamiento en la demo
        SEGUNDOS_REVISION_ESCALAMIENTO = 10
        EVIDENCIAS_DIR = os.environ["EVIDENCIAS_DIR"]
        SUPABASE_URL = ""

    Config.EVIDENCIAS_DIR = ConfigDemo.EVIDENCIAS_DIR
    Config.SUPABASE_URL = ""
    Config.MINUTOS_ESCALAMIENTO = ConfigDemo.MINUTOS_ESCALAMIENTO

    # ---- datos de ejemplo -------------------------------------------------
    repo.puntos[1]["nombre"] = "Porteria principal"
    for rol, correo, clave in (
        ("guardia", "guardia@demo.edu", "Guardia-2026"),
        ("administrador", "admin@demo.edu", "Admin-2026"),
        ("consulta", "consulta@demo.edu", "Consulta-2026"),
    ):
        uid = repo.crear_usuario(f"Usuario {rol}", correo, seguridad.hashear(clave), 1, rol=rol)
        repo.usuarios[uid]["permisos"] = {
            "guardia": ["acceso:consultar", "acceso:verificar", "alerta:atender"],
            "consulta": ["acceso:consultar", "reporte:generar"],
        }.get(rol, [])

    personas = []
    for i, (nombres, apellidos, tipo) in enumerate((
        ("Ana", "Ruiz", "estudiante"),
        ("Carlos", "Mejia", "docente"),
        ("Lucia", "Pardo", "administrativo"),
        ("Jorge", "Nieto", "visitante"),
    )):
        pid = repo.crear_persona(documento=str(1001 + i), tipo_persona=tipo,
                                 nombres=nombres, apellidos=apellidos,
                                 autoriza_biometria=True, estado="activo")
        vector = np.full(128, float(i), dtype=np.float64)   # una codificacion por persona
        repo.guardar_codificacion(pid, vector)
        personas.append((pid, vector))

    # Historial previo, para que la consulta y el reporte tengan datos
    for horas, (pid, _) in zip((8, 6, 4), personas[:3]):
        repo.registrar_acceso(punto_acceso_id=1, camara_id=1, persona_id=pid,
                              tipo_evento="ingreso", resultado="identificado",
                              distancia=0.31, confianza=0.48,
                              fecha_hora=datetime.now() - timedelta(hours=horas))

    app = crear_app(ConfigDemo)
    return app, repo, personas


def fotograma(texto: str) -> str:
    """Imagen sintetica que hace las veces del fotograma de la estacion."""
    import base64

    from PIL import Image, ImageDraw

    imagen = Image.new("RGB", (640, 360), (40, 44, 52))
    dibujo = ImageDraw.Draw(imagen)
    dibujo.rectangle((230, 120, 410, 250), outline=(220, 40, 40), width=4)
    dibujo.text((20, 20), "FaceGuard - fotograma simulado (modo demostracion)", fill=(255, 255, 255))
    dibujo.text((240, 255), texto, fill=(255, 120, 120))
    buffer = io.BytesIO()
    imagen.save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode()


def estacion_simulada(personas):
    """Hace lo que haria la estacion de captura, por HTTP y con credencial."""
    sesion = requests.Session()
    sesion.headers["Authorization"] = f"Bearer {TOKEN}"
    time.sleep(3)
    ciclo = 0
    while True:
        ciclo += 1
        try:
            if ciclo % 4 == 0:
                # alguien que no esta enrolado
                vector = np.full(128, 50.0 + ciclo)
                sesion.post(f"{URL}/api/accesos/evento", json={"codificacion": vector.tolist()},
                            timeout=10)
            else:
                pid, vector = random.choice(personas)
                ruido = vector + np.random.normal(0, 0.01, 128)
                respuesta = sesion.post(f"{URL}/api/accesos/evento",
                                        json={"codificacion": ruido.tolist()}, timeout=10).json()
                if ciclo % 3 == 0:
                    tipo = random.choice(["arma_blanca", "arma_fuego"])
                    for _ in range(2):        # la misma arma vista dos veces: una sola alerta
                        sesion.post(f"{URL}/api/alertas", json={
                            "tipo_arma": tipo,
                            "confianza": round(random.uniform(0.72, 0.95), 2),
                            "registro_acceso_id": respuesta.get("registro_id"),
                            "rostros_en_escena": 1,
                            "imagen": fotograma(tipo.replace("_", " ")),
                        }, timeout=10)
        except requests.RequestException as exc:
            print(f"[estacion simulada] sin respuesta del servidor: {exc}")
        time.sleep(SEGUNDOS_ENTRE_EVENTOS)


def main() -> int:
    app, repo, personas = preparar()
    threading.Thread(target=estacion_simulada, args=(personas,), daemon=True).start()
    print(__doc__)
    print(f"Abra {URL.replace('127.0.0.1', 'localhost')} en el navegador. Ctrl+C para salir.\n")
    app.run(host="0.0.0.0", port=PUERTO, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
