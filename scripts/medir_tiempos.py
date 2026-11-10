"""Medicion de los tiempos de respuesta en el equipo real (RNF-01 y RNF-02).

Las pruebas automatizadas miden solo la parte del servidor, que es rapida
porque unicamente compara vectores. El tiempo que exige el requisito es el
total, incluyendo la codificacion facial y la inferencia de YOLOv8, y eso solo
se puede medir aqui, en la estacion de captura.

Uso:
    python scripts/medir_tiempos.py --api http://localhost:5000 --repeticiones 30
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np   # noqa: E402

from app.config import Config   # noqa: E402

LIMITE_ROSTRO_MS = 3000     # RNF-01
LIMITE_ARMAS_MS = 2000      # RNF-02


def argumentos():
    parser = argparse.ArgumentParser(description="Tiempos de respuesta")
    parser.add_argument("--api", default="http://localhost:5000")
    parser.add_argument("--punto-acceso", type=int, default=1)
    parser.add_argument("--repeticiones", type=int, default=30)
    parser.add_argument("--dispositivo", type=int, default=0,
                        help="camara del sistema; -1 usa un fotograma sintetico")
    parser.add_argument("--salida", default="tiempos.json")
    return parser.parse_args()


def resumen(nombre: str, medidas: list[float], limite: float | None) -> dict:
    datos = {
        "mediana_ms": round(statistics.median(medidas), 1),
        "promedio_ms": round(statistics.mean(medidas), 1),
        "maximo_ms": round(max(medidas), 1),
        "minimo_ms": round(min(medidas), 1),
        "muestras": len(medidas),
    }
    if len(medidas) > 1:
        datos["desviacion_ms"] = round(statistics.stdev(medidas), 1)
    print(f"\n{nombre}")
    print(f"  mediana {datos['mediana_ms']:>8.1f} ms")
    print(f"  maximo  {datos['maximo_ms']:>8.1f} ms")
    if limite is not None:
        datos["limite_ms"] = limite
        datos["cumple"] = datos["mediana_ms"] < limite
        print(f"  limite  {limite:>8.0f} ms  -> "
              f"{'CUMPLE' if datos['cumple'] else 'NO CUMPLE'}")
    return datos


def obtener_fotograma(dispositivo: int) -> np.ndarray:
    if dispositivo < 0:
        return np.random.randint(
            0, 255,
            (Config.RESOLUCION_MINIMA_ALTO, Config.RESOLUCION_MINIMA_ANCHO, 3),
            dtype=np.uint8,
        )
    import cv2

    camara = cv2.VideoCapture(dispositivo)
    ok, fotograma = camara.read()
    camara.release()
    if not ok:
        raise SystemExit("No se pudo leer de la camara. Use --dispositivo -1.")
    return cv2.cvtColor(fotograma, cv2.COLOR_BGR2RGB)


def main() -> int:
    args = argumentos()
    informe = {"api": args.api, "fecha": time.strftime("%Y-%m-%d %H:%M")}

    print(f"Midiendo con {args.repeticiones} repeticiones...")
    fotograma = obtener_fotograma(args.dispositivo)

    # ---- 1. Codificacion facial en la estacion -------------------------
    from app.servicios.reconocimiento_facial import RostroNoDetectado, codificar_rostro

    medidas, vector = [], None
    for _ in range(args.repeticiones):
        inicio = time.perf_counter()
        try:
            vector = codificar_rostro(fotograma, estricto=False)
        except RostroNoDetectado:
            pass
        medidas.append((time.perf_counter() - inicio) * 1000)
    informe["codificacion_facial"] = resumen(
        "Codificacion facial (estacion)", medidas, None)

    # ---- 2. Respuesta del servidor -------------------------------------
    import requests

    if vector is None:
        vector = np.zeros(128)
    medidas = []
    for _ in range(args.repeticiones):
        inicio = time.perf_counter()
        requests.post(f"{args.api}/api/accesos/evento", json={
            "codificacion": vector.tolist(),
            "punto_acceso_id": args.punto_acceso,
        }, timeout=30)
        medidas.append((time.perf_counter() - inicio) * 1000)
    informe["respuesta_servidor"] = resumen("Respuesta del servidor", medidas, None)

    # ---- 3. Total del RNF-01 -------------------------------------------
    total = (informe["codificacion_facial"]["mediana_ms"]
             + informe["respuesta_servidor"]["mediana_ms"])
    informe["rnf01_total"] = {
        "mediana_ms": round(total, 1),
        "limite_ms": LIMITE_ROSTRO_MS,
        "cumple": total < LIMITE_ROSTRO_MS,
    }
    print(f"\nRNF-01 identificacion completa: {total:.0f} ms de "
          f"{LIMITE_ROSTRO_MS} -> "
          f"{'CUMPLE' if total < LIMITE_ROSTRO_MS else 'NO CUMPLE'}")

    # ---- 4. Deteccion de armas -----------------------------------------
    ruta_modelo = Path(Config.MODELO_YOLO)
    if ruta_modelo.exists():
        from app.servicios.deteccion_armas import DetectorArmas

        detector = DetectorArmas()
        detector.detectar(fotograma)      # descarta la primera, que carga el modelo
        medidas = []
        for _ in range(args.repeticiones):
            inicio = time.perf_counter()
            detector.detectar(fotograma)
            medidas.append((time.perf_counter() - inicio) * 1000)
        informe["rnf02_deteccion_armas"] = resumen(
            "Deteccion de armas (RNF-02)", medidas, LIMITE_ARMAS_MS)
    else:
        print(f"\nNo se midio la deteccion de armas: falta {ruta_modelo}")
        print("Entrene el modelo con scripts/entrenar_yolo.ipynb")
        informe["rnf02_deteccion_armas"] = {"medido": False}

    Path(args.salida).write_text(
        json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nInforme guardado en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
