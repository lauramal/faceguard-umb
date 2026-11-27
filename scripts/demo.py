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
  que aplica las mismas reglas que PostgreSQL) y la camara. Un hilo hace las
  veces de la estacion de captura y envia por HTTP, con la credencial de la
  camara, los mismos mensajes que enviaria la estacion real.

Detecciones de arma: tres niveles, del mas real al mas simple
--------------------------------------------------------------
1. Banco de escenas (recomendado). Si existe la carpeta datos_demo/ con
   imagenes/ y detecciones.json, la estacion simulada toma fotos reales del
   conjunto de prueba y envia lo que el modelo YOLOv8 entrenado detecto en
   ellas: la clase, la confianza y las cajas, dibujadas sobre la foto. El
   banco se genera en Colab con la seccion 9 de scripts/entrenar_yolo.ipynb,
   o en un equipo con Ultralytics con scripts/crear_banco_demo.py.
2. YOLO en vivo. Si hay fotos en datos_demo/imagenes/ pero no el JSON, y
   Ultralytics esta instalado, el modelo modelos/yolov8n-armas.pt se ejecuta
   sobre cada foto en el momento.
3. Fotograma sintetico. Si no hay fotos, se envia una imagen dibujada.

Los rostros siguen simulados: el reconocimiento facial necesita a los
voluntarios enrolados, y eso se evalua aparte con la estacion real.

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
BANCO = Path(os.getenv("DEMO_BANCO", str(RAIZ / "datos_demo")))
URL = f"http://127.0.0.1:{PUERTO}"
TOKEN = "1.secreto-de-prueba"           # credencial de la camara 1 de la demo
SEGUNDOS_ENTRE_EVENTOS = int(os.getenv("DEMO_SEGUNDOS", "15"))
RNG = np.random.default_rng(42)
# Dos visitantes que no estan enrolados y pasan varias veces por la porteria
DESCONOCIDOS = [RNG.normal(0, 0.06, 128) for _ in range(2)]


def preparar(fuente: str):
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
        DEMO_FUENTE = fuente
        MINUTOS_ESCALAMIENTO = 1          # para ver el escalamiento en la demo
        SEGUNDOS_REVISION_ESCALAMIENTO = 10
        EVIDENCIAS_DIR = os.environ["EVIDENCIAS_DIR"]
        SUPABASE_URL = ""

    Config.EVIDENCIAS_DIR = ConfigDemo.EVIDENCIAS_DIR
    Config.SUPABASE_URL = ""
    Config.MINUTOS_ESCALAMIENTO = ConfigDemo.MINUTOS_ESCALAMIENTO

    # ---- datos de ejemplo -------------------------------------------------
    repo.puntos[1]["nombre"] = "Porteria principal"
    for rol, nombre, correo, clave in (
        ("guardia", "Andrés Rojas", "guardia@demo.edu", "Guardia-2026"),
        ("administrador", "Paula Herrera", "admin@demo.edu", "Admin-2026"),
        ("consulta", "Diana Castro", "consulta@demo.edu", "Consulta-2026"),
    ):
        uid = repo.crear_usuario(nombre, correo, seguridad.hashear(clave), 1, rol=rol)
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
        # Codificacion de 128 valores con la escala de face_recognition: dos
        # personas distintas quedan a ~0.9 de distancia y la misma persona,
        # en otra toma, a ~0.3.
        vector = RNG.normal(0, 0.06, 128)
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


# ---------------------------------------------------------------------------
# Banco de escenas
# ---------------------------------------------------------------------------

class Banco:
    """Fotos reales con las detecciones del modelo YOLOv8 entrenado."""

    def __init__(self, carpeta: Path):
        import json

        self.carpeta = carpeta
        self.escenas: list[tuple[Path, list[dict]]] = []
        self.modo = "sintetico"
        self.detector = None

        imagenes = carpeta / "imagenes"
        indice = carpeta / "detecciones.json"
        fotos = sorted(p for p in imagenes.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png")) \
            if imagenes.is_dir() else []

        if indice.exists() and fotos:
            datos = json.loads(indice.read_text(encoding="utf-8"))
            for nombre, detecciones in datos.get("imagenes", {}).items():
                ruta = imagenes / nombre
                if ruta.exists():
                    self.escenas.append((ruta, detecciones))
            if self.escenas:
                self.modo = "banco"
        elif fotos:
            try:
                from ultralytics import YOLO  # type: ignore

                from app.config import Config
                self.detector = YOLO(os.getenv("MODELO_YOLO", str(RAIZ / Config.MODELO_YOLO)))
                self.escenas = [(ruta, []) for ruta in fotos]
                self.modo = "vivo"
            except Exception as exc:          # sin Ultralytics: se usa lo sintetico
                print(f"[demo] Hay fotos pero no se pudo cargar YOLO ({exc}); "
                      "se usara el fotograma sintetico.")

    def descripcion(self) -> str:
        if self.modo == "banco":
            return (f"Las alertas usan {len(self.escenas)} fotos reales del conjunto de prueba "
                    "con las detecciones del modelo YOLOv8 entrenado; los rostros y la camara "
                    "son simulados.")
        if self.modo == "vivo":
            return ("El modelo YOLOv8 entrenado analiza en vivo fotos del conjunto de prueba; "
                    "los rostros y la camara son simulados.")
        return "Base de datos en memoria y estacion de captura simulada."

    def detecciones(self, ruta: Path) -> list[dict]:
        if self.modo == "vivo":
            r = self.detector.predict(str(ruta), conf=0.25, verbose=False)[0]
            return [{"clase": r.names[int(c.cls)], "confianza": float(c.conf),
                     "caja": [float(v) for v in c.xyxy[0]]} for c in r.boxes]
        return next(d for p, d in self.escenas if p == ruta)

    def escena(self):
        """Una foto al azar y lo que el modelo vio en ella."""
        ruta, _ = random.choice(self.escenas)
        return ruta, self.detecciones(ruta)


def dibujar(ruta: Path, detecciones: list[dict], umbral: float) -> str:
    """Dibuja las cajas como lo haria la estacion y devuelve el JPEG en base64."""
    import base64

    from PIL import Image, ImageDraw

    from app.servicios.deteccion_armas import traducir_etiqueta

    imagen = Image.open(ruta).convert("RGB")
    dibujo = ImageDraw.Draw(imagen)
    grosor = max(2, imagen.width // 250)
    for d in detecciones:
        es_arma = traducir_etiqueta(d["clase"]) is not None
        if es_arma and d["confianza"] < umbral:
            continue
        if not es_arma and d["clase"] != "person":
            continue
        color = (220, 38, 38) if es_arma else (59, 130, 246)
        x1, y1, x2, y2 = d["caja"]
        dibujo.rectangle((x1, y1, x2, y2), outline=color, width=grosor)
        texto = f"{d['clase']} {d['confianza']:.2f}"
        ancho = dibujo.textlength(texto) + 8
        dibujo.rectangle((x1, max(0, y1 - 16), x1 + ancho, max(16, y1)), fill=color)
        dibujo.text((x1 + 4, max(0, y1 - 15)), texto, fill=(255, 255, 255))
    buffer = io.BytesIO()
    imagen.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode()


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


def aviso_de_arma(banco: Banco, umbral: float):
    """Lo que la estacion enviaria tras pasar un fotograma por YOLOv8.

    Devuelve None cuando el modelo no ve ningun arma por encima del umbral,
    que es lo que pasa con la mayoria de los fotogramas reales.
    """
    from app.servicios.deteccion_armas import traducir_etiqueta

    if banco.modo == "sintetico":
        tipo = random.choice(["arma_blanca", "arma_fuego"])
        return {"tipo_arma": tipo, "confianza": round(random.uniform(0.72, 0.95), 2),
                "rostros_en_escena": 1, "imagen": fotograma(tipo.replace("_", " "))}

    ruta, detecciones = banco.escena()
    armas = [d for d in detecciones
             if traducir_etiqueta(d["clase"]) and d["confianza"] >= umbral]
    if not armas:
        print(f"[estacion simulada] {ruta.name}: sin arma sobre el umbral, no se alerta")
        return None
    mejor = max(armas, key=lambda d: d["confianza"])
    personas = sum(1 for d in detecciones if d["clase"] == "person" and d["confianza"] >= 0.5)
    return {
        "tipo_arma": traducir_etiqueta(mejor["clase"]),
        "confianza": round(float(mejor["confianza"]), 3),
        "rostros_en_escena": max(1, personas),
        "imagen": dibujar(ruta, detecciones, umbral),
    }


def estacion_simulada(personas, banco: Banco):
    """Hace lo que haria la estacion de captura, por HTTP y con credencial."""
    from app.config import Config

    umbral = float(Config.UMBRAL_ARMA)
    sesion = requests.Session()
    sesion.headers["Authorization"] = f"Bearer {TOKEN}"
    time.sleep(3)
    ciclo = 0
    while True:
        ciclo += 1
        try:
            if ciclo % 6 == 0:
                # alguien que no esta enrolado: el servidor lo registra una
                # sola vez aunque pase varias veces seguidas
                vector = random.choice(DESCONOCIDOS) + RNG.normal(0, 0.02, 128)
                sesion.post(f"{URL}/api/accesos/evento", json={"codificacion": vector.tolist()},
                            timeout=10)
            else:
                pid, vector = random.choice(personas)
                ruido = vector + RNG.normal(0, 0.025, 128)
                respuesta = sesion.post(f"{URL}/api/accesos/evento",
                                        json={"codificacion": ruido.tolist()}, timeout=10).json()
                if ciclo % 3 == 0:
                    aviso = aviso_de_arma(banco, umbral)
                    if aviso:
                        aviso["registro_acceso_id"] = respuesta.get("registro_id")
                        for _ in range(2):    # la misma arma vista dos veces: una sola alerta
                            sesion.post(f"{URL}/api/alertas", json=aviso, timeout=30)
        except requests.RequestException as exc:
            print(f"[estacion simulada] sin respuesta del servidor: {exc}")
        time.sleep(SEGUNDOS_ENTRE_EVENTOS)


def main() -> int:
    banco = Banco(BANCO)
    app, repo, personas = preparar(banco.descripcion())
    threading.Thread(target=estacion_simulada, args=(personas, banco), daemon=True).start()
    print(__doc__)
    print(f"Detecciones de arma: modo {banco.modo.upper()}. {banco.descripcion()}\n")
    print(f"Abra {URL.replace('127.0.0.1', 'localhost')} en el navegador. Ctrl+C para salir.\n")
    app.run(host="0.0.0.0", port=PUERTO, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
