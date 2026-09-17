"""Estacion de captura del punto de acceso (CU-02).

Uso:
    python scripts/estacion_acceso.py 1

Abre la camara, analiza un fotograma por segundo y muestra en pantalla el
resultado de la identificacion. No decide nada por su cuenta cuando la
confianza es baja, solo avisa para que el guardia verifique.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from app.db import inicializar_pool  # noqa: E402
from app.servicios.control_acceso import procesar_fotograma  # noqa: E402

INTERVALO_SEGUNDOS = 1.0
VERDE = (0, 180, 0)
ROJO = (0, 0, 220)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1

    punto_acceso_id = int(sys.argv[1])
    inicializar_pool()

    camara = cv2.VideoCapture(0)
    if not camara.isOpened():
        print("No se pudo abrir la camara")
        return 1

    print(f"Estacion activa en el punto de acceso {punto_acceso_id}. Pulse q para salir.")
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
                resultado = procesar_fotograma(rgb, punto_acceso_id)

                if resultado.identificado:
                    mensaje = (
                        f"{resultado.nombre} | {resultado.tipo_evento} | "
                        f"{resultado.confianza:.2f} | {resultado.milisegundos:.0f} ms"
                    )
                    color = VERDE
                else:
                    mensaje = f"No identificado ({resultado.motivo})"
                    color = ROJO
                print(mensaje)

            cv2.putText(
                fotograma, mensaje, (12, 32),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2,
            )
            cv2.imshow("FaceGuard UMB - punto de acceso", fotograma)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camara.release()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
