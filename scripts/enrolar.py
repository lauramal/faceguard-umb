"""Enrolamiento facial de un estudiante desde la camara del equipo (CU-01).

Uso:
    python scripts/enrolar.py 202012345

Toma cinco capturas espaciadas, calcula la codificacion de cada una, promedia
las validas y guarda el vector resultante. Las imagenes no se almacenan.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from app.db import inicializar_pool  # noqa: E402
from app import repositorio  # noqa: E402
from app.servicios.reconocimiento_facial import (  # noqa: E402
    RostroNoDetectado,
    VariosRostros,
    codificar_rostro,
    promediar_codificaciones,
)

CAPTURAS = 5
PAUSA_SEGUNDOS = 1.5


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1

    codigo = sys.argv[1]

    inicializar_pool()
    estudiante = repositorio.obtener_estudiante_por_codigo(codigo)
    if estudiante is None:
        print(f"No existe un estudiante con codigo {codigo}")
        return 1
    if not estudiante["consentimiento_firmado"]:
        print("El estudiante no ha firmado el consentimiento informado")
        return 1

    camara = cv2.VideoCapture(0)
    if not camara.isOpened():
        print("No se pudo abrir la camara")
        return 1

    print(f"Enrolando a {estudiante['nombres']} {estudiante['apellidos']}")
    print("Mire a la camara y cambie levemente el angulo entre capturas.")

    codificaciones = []
    try:
        for i in range(1, CAPTURAS + 1):
            time.sleep(PAUSA_SEGUNDOS)
            ok, fotograma = camara.read()
            if not ok:
                print(f"  captura {i}: no se pudo leer el fotograma")
                continue

            rgb = cv2.cvtColor(fotograma, cv2.COLOR_BGR2RGB)
            try:
                codificaciones.append(codificar_rostro(rgb))
                print(f"  captura {i}: correcta")
            except RostroNoDetectado:
                print(f"  captura {i}: no se detecto rostro")
            except VariosRostros:
                print(f"  captura {i}: hay mas de una persona en cuadro")
    finally:
        camara.release()

    if not codificaciones:
        print("No se obtuvo ninguna codificacion valida")
        return 1

    vector = promediar_codificaciones(codificaciones)
    codificacion_id = repositorio.guardar_codificacion(estudiante["id"], vector)
    print(
        f"Codificacion {codificacion_id} guardada a partir de "
        f"{len(codificaciones)} de {CAPTURAS} capturas"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
