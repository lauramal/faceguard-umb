"""Estacion de captura del punto de acceso (CU-02, CU-03).

Corre en el equipo del punto de acceso, no en el servidor. Aqui si viven
dlib y YOLOv8, que son las librerias pesadas: el servidor solo recibe el
vector de 128 numeros y el aviso de arma, de modo que cabe en un plan
gratuito (RNF-11). Como efecto secundario, las imagenes de los rostros nunca
salen de este equipo.

Uso:
    python scripts/estacion_acceso.py 1 --api http://localhost:5000

Pulse q para salir.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2        # noqa: E402
import requests   # noqa: E402

from app.servicios.deteccion_armas import DetectorArmas          # noqa: E402
from app.servicios.reconocimiento_facial import (                # noqa: E402
    RostroNoDetectado, codificar_rostro,
)

INTERVALO_SEGUNDOS = 1.0
VERDE = (0, 180, 0)
AMBAR = (0, 170, 220)
ROJO = (0, 0, 220)


def argumentos():
    parser = argparse.ArgumentParser(description="Estacion de captura FaceGuard")
    parser.add_argument("punto_acceso_id", type=int)
    parser.add_argument("--api", default="http://localhost:5000",
                        help="URL base del servidor de aplicacion")
    parser.add_argument("--camara-id", type=int, default=None)
    parser.add_argument("--dispositivo", type=int, default=0,
                        help="indice de la camara del sistema")
    parser.add_argument("--sin-armas", action="store_true",
                        help="desactiva la deteccion de armas")
    return parser.parse_args()


def enviar_evento(api: str, payload: dict) -> dict | None:
    try:
        respuesta = requests.post(f"{api}/api/accesos/evento", json=payload, timeout=10)
        respuesta.raise_for_status()
        return respuesta.json()
    except requests.RequestException as exc:
        print(f"  [!] no se pudo enviar el evento: {exc}")
        return None


def enviar_alerta(api: str, payload: dict) -> None:
    try:
        requests.post(f"{api}/api/alertas", json=payload, timeout=10).raise_for_status()
    except requests.RequestException as exc:
        print(f"  [!] no se pudo enviar la alerta: {exc}")


def main() -> int:
    args = argumentos()
    detector = None if args.sin_armas else DetectorArmas()

    camara = cv2.VideoCapture(args.dispositivo)
    if not camara.isOpened():
        print("No se pudo abrir la camara")
        return 1

    print(f"Estacion activa en el punto {args.punto_acceso_id}. API: {args.api}")
    ultimo_analisis = 0.0
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
                registro_id = persona_id = None
                try:
                    codificacion = codificar_rostro(rgb, estricto=False)
                except RostroNoDetectado:
                    mensaje, color = "Sin rostro en el encuadre", AMBAR
                else:
                    respuesta = enviar_evento(args.api, {
                        "codificacion": codificacion.tolist(),
                        "punto_acceso_id": args.punto_acceso_id,
                        "camara_id": args.camara_id,
                    })
                    if respuesta is None:
                        mensaje, color = "Servidor no disponible", ROJO
                    elif respuesta["identificado"]:
                        registro_id = respuesta["registro_id"]
                        persona_id = respuesta["persona_id"]
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
                        aviso = (f"ALERTA: {hallazgo.tipo_arma} "
                                 f"({hallazgo.confianza:.2f})")
                        print(f"  {aviso}")
                        mensaje, color = aviso, ROJO
                        enviar_alerta(args.api, {
                            "camara_id": args.camara_id or 1,
                            "punto_acceso_id": args.punto_acceso_id,
                            "tipo_arma": hallazgo.tipo_arma,
                            "confianza": hallazgo.confianza,
                            "registro_acceso_id": registro_id,
                            "persona_id": persona_id,
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
