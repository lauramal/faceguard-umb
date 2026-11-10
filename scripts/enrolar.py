"""Enrolamiento facial de una persona (CU-01).

Captura varias fotos desde la camara local, calcula sus codificaciones y las
promedia antes de guardarlas. Nunca se almacena la fotografia.

Uso:
    python scripts/enrolar.py --documento 1001 --capturas 5
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from app import repositorio                                  # noqa: E402
from app.db import inicializar_pool                          # noqa: E402
from app.servicios.reconocimiento_facial import (            # noqa: E402
    RostroNoDetectado, VariosRostros, codificar_rostro, promediar_codificaciones,
)


def argumentos():
    parser = argparse.ArgumentParser(description="Enrolamiento facial")
    parser.add_argument("--documento", required=True)
    parser.add_argument("--institucion", type=int, default=1)
    parser.add_argument("--capturas", type=int, default=5)
    parser.add_argument("--dispositivo", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = argumentos()
    inicializar_pool()

    persona = repositorio.obtener_persona_por_documento(args.institucion, args.documento)
    if persona is None:
        print(f"No existe una persona con documento {args.documento}")
        return 1
    if not persona["autoriza_biometria"]:
        print(f"{persona['nombres']} {persona['apellidos']} no autorizo el "
              "tratamiento de sus datos biometricos.")
        print("Puede ingresar con su credencial institucional.")
        return 2

    camara = cv2.VideoCapture(args.dispositivo)
    if not camara.isOpened():
        print("No se pudo abrir la camara")
        return 1

    print(f"Enrolando a {persona['nombres']} {persona['apellidos']}.")
    print("Mire a la camara y cambie levemente de angulo entre capturas.")

    codificaciones = []
    try:
        while len(codificaciones) < args.capturas:
            ok, fotograma = camara.read()
            if not ok:
                break
            cv2.putText(fotograma, f"Captura {len(codificaciones) + 1}/{args.capturas}"
                        " - espacio para tomar, q para salir", (12, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 180, 0), 2)
            cv2.imshow("FaceGuard - enrolamiento", fotograma)

            tecla = cv2.waitKey(1) & 0xFF
            if tecla == ord("q"):
                print("Enrolamiento cancelado")
                return 1
            if tecla == ord(" "):
                rgb = cv2.cvtColor(fotograma, cv2.COLOR_BGR2RGB)
                try:
                    codificaciones.append(codificar_rostro(rgb, estricto=True))
                    print(f"  captura {len(codificaciones)} tomada")
                except RostroNoDetectado:
                    print("  no se detecto ningun rostro, intente de nuevo")
                except VariosRostros:
                    print("  hay mas de una persona en el encuadre")
                time.sleep(0.3)
    finally:
        camara.release()
        cv2.destroyAllWindows()

    if not codificaciones:
        print("No se tomo ninguna captura valida")
        return 1

    vector = promediar_codificaciones(codificaciones)
    codificacion_id = repositorio.guardar_codificacion(persona["id"], vector)
    repositorio.registrar_auditoria(
        None, "enrolar_persona", "persona", persona["id"],
        f"{len(codificaciones)} capturas desde script",
    )
    print(f"Codificacion {codificacion_id} guardada a partir de "
          f"{len(codificaciones)} capturas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
