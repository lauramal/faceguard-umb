"""Estacion de captura del punto de acceso (CU-02, CU-03).

Corre en el equipo del punto de acceso, no en el servidor. Aqui viven dlib y
YOLOv8, que son las librerias pesadas: el servidor solo recibe el vector de 128
numeros y el aviso de arma, de modo que cabe en un plan gratuito (RNF-11). Las
imagenes de los rostros no salen de este equipo; solo sale el fotograma de una
deteccion de arma, como evidencia para el guardia.

La estacion se autentica con la credencial de su camara, que el administrador
genera con POST /api/camaras/<id>/credencial:

    export FACEGUARD_TOKEN=1.xxxxxxxxxxxxxxxx
    python scripts/estacion_acceso.py --api https://su-servidor.onrender.com

Pulse q para salir.
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2        # noqa: E402
import requests   # noqa: E402

from app.servicios.deteccion_armas import DetectorArmas          # noqa: E402
from app.servicios.reconocimiento_facial import codificar_principal  # noqa: E402

INTERVALO_SEGUNDOS = 1.0
# Una misma arma frente a la camara no se reporta en cada fotograma. El
# servidor tambien agrupa las repetidas, pero no hace falta mandarlas todas.
PAUSA_ENTRE_AVISOS = 10.0
VERDE = (0, 180, 0)
AMBAR = (0, 170, 220)
ROJO = (0, 0, 220)


def argumentos():
    parser = argparse.ArgumentParser(description="Estacion de captura FaceGuard")
    parser.add_argument("--api", default=os.getenv("FACEGUARD_API", "http://localhost:5000"),
                        help="URL base del servidor de aplicacion")
    parser.add_argument("--token", default=os.getenv("FACEGUARD_TOKEN"),
                        help="credencial de la camara (o variable FACEGUARD_TOKEN)")
    parser.add_argument("--dispositivo", type=int, default=0,
                        help="indice de la camara del sistema")
    parser.add_argument("--sin-armas", action="store_true",
                        help="desactiva la deteccion de armas")
    return parser.parse_args()


class Servidor:
    def __init__(self, api: str, token: str):
        self.api = api.rstrip("/")
        self.sesion = requests.Session()
        self.sesion.headers["Authorization"] = f"Bearer {token}"

    def _post(self, ruta: str, payload: dict) -> dict | None:
        try:
            respuesta = self.sesion.post(f"{self.api}{ruta}", json=payload, timeout=10)
            if respuesta.status_code == 401:
                print("  [!] el servidor rechazo la credencial de la estacion")
                return None
            respuesta.raise_for_status()
            return respuesta.json()
        except requests.RequestException as exc:
            print(f"  [!] no se pudo enviar a {ruta}: {exc}")
            return None

    def evento(self, codificacion) -> dict | None:
        return self._post("/api/accesos/evento", {"codificacion": codificacion.tolist()})

    def alerta(self, payload: dict) -> dict | None:
        return self._post("/api/alertas", payload)


def jpeg_base64(fotograma) -> str:
    ok, buffer = cv2.imencode(".jpg", fotograma, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return base64.b64encode(buffer.tobytes()).decode() if ok else ""


def main() -> int:
    args = argumentos()
    if not args.token:
        print("Falta la credencial de la camara: use --token o FACEGUARD_TOKEN.")
        return 2

    servidor = Servidor(args.api, args.token)
    detector = None if args.sin_armas else DetectorArmas()

    camara = cv2.VideoCapture(args.dispositivo)
    if not camara.isOpened():
        print("No se pudo abrir la camara")
        return 1

    print(f"Estacion activa. API: {args.api}")
    ultimo_analisis = 0.0
    ultimo_aviso: dict[str, float] = {}
    mensaje, color = "Esperando...", VERDE

    try:
        while True:
            ok, fotograma = camara.read()
            if not ok:
                break

            ahora = time.time()
            if ahora - ultimo_analisis >= INTERVALO_SEGUNDOS:
                ultimo_analisis = ahora
                rgb = cv2.cvtColor(fotograma, cv2.COLOR_BGR2RGB)

                # ---- Identificacion facial ----------------------------
                registro_id = None
                codificacion, rostros = codificar_principal(rgb)
                if codificacion is None:
                    mensaje, color = "Sin rostro en el encuadre", AMBAR
                else:
                    respuesta = servidor.evento(codificacion)
                    if respuesta is None:
                        mensaje, color = "Servidor no disponible", ROJO
                    elif respuesta["identificado"]:
                        registro_id = respuesta["registro_id"]
                        mensaje = (f"{respuesta['nombre']} | {respuesta['tipo_evento']}"
                                   f" | d={respuesta['distancia']}"
                                   f" | {respuesta['milisegundos']:.0f} ms")
                        color = VERDE
                    else:
                        registro_id = respuesta.get("registro_id")
                        mensaje = "No identificado, verificar manualmente"
                        color = ROJO
                    print(mensaje)

                # ---- Deteccion de arma visible ------------------------
                if detector is not None:
                    hallazgo = detector.mas_probable(rgb)
                    if hallazgo is not None:
                        aviso = f"ALERTA: {hallazgo.tipo_arma} ({hallazgo.confianza:.2f})"
                        mensaje, color = aviso, ROJO
                        previo = ultimo_aviso.get(hallazgo.tipo_arma, 0.0)
                        if ahora - previo >= PAUSA_ENTRE_AVISOS:
                            ultimo_aviso[hallazgo.tipo_arma] = ahora
                            print(f"  {aviso}")
                            # Se envia el evento de acceso del mismo fotograma
                            # y cuantos rostros habia. La persona de ese evento
                            # es contexto: el servidor no la marca como
                            # portadora, eso lo decide el guardia.
                            servidor.alerta({
                                "tipo_arma": hallazgo.tipo_arma,
                                "confianza": hallazgo.confianza,
                                "registro_acceso_id": registro_id,
                                "rostros_en_escena": rostros,
                                "imagen": jpeg_base64(fotograma),
                            })

            cv2.putText(fotograma, mensaje[:70], (12, 32),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            cv2.imshow("FaceGuard - punto de acceso", fotograma)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camara.release()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
