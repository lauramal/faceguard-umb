"""Metricas del reconocimiento facial sobre los intentos reales (objetivo 5).

Calcula las cifras que van al Capitulo IV a partir de los intentos que se
ejecutan con los voluntarios (5 personas x 30 intentos). No inventa nada: lee
un CSV en el que cada fila es un intento y dice quien paso de verdad frente a
la camara y que respondio el sistema.

Como armar el CSV
-----------------
1. Durante las pruebas, anote por cada intento quien paso y en que condicion
   (luz normal, poca luz, perfil, gorra, tapabocas...).
2. Exporte los eventos de esa sesion desde el panel:
   GET /api/reportes/accesos.csv?desde=...&hasta=...
3. Agregue a ese archivo dos columnas: "documento_real" (documento de quien
   paso, o "desconocido" si era alguien no enrolado) y "condicion".

Columnas que usa el script: documento_real, condicion, resultado, documento
(el que identifico el sistema, vacio si no identifico) y distancia.

    python scripts/evaluar_reconocimiento.py intentos.csv

Como se cuenta cada intento
---------------------------
* acierto:            paso una persona enrolada y el sistema dijo quien era.
* falso rechazo:      paso una persona enrolada y el sistema no la identifico.
* falsa aceptacion:   el sistema identifico a alguien equivocado, o identifico
                      como enrolado a un desconocido. Es el error grave.
* rechazo correcto:   paso un desconocido y el sistema no lo identifico.

Las pruebas se repiten con las mismas cinco personas, de modo que estas cifras
describen el desempeno sobre esos participantes y en esas condiciones. No
permiten generalizar a toda la poblacion de una institucion.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

HIPOTESIS = 0.85
DESCONOCIDO = "desconocido"


def clasificar(fila: dict) -> str:
    real = (fila.get("documento_real") or "").strip()
    obtenido = (fila.get("documento") or "").strip()
    identificado = (fila.get("resultado") or "").strip() == "identificado" and obtenido

    if real.lower() == DESCONOCIDO:
        return "falsa_aceptacion" if identificado else "rechazo_correcto"
    if not identificado:
        return "falso_rechazo"
    return "acierto" if obtenido == real else "falsa_aceptacion"


def metricas(conteo: dict) -> dict:
    aciertos = conteo["acierto"]
    fr = conteo["falso_rechazo"]
    fa = conteo["falsa_aceptacion"]
    rc = conteo["rechazo_correcto"]
    total = aciertos + fr + fa + rc
    identificaciones = aciertos + fa
    precision = aciertos / identificaciones if identificaciones else 0.0
    exhaustividad = aciertos / (aciertos + fr) if (aciertos + fr) else 0.0
    f1 = (2 * precision * exhaustividad / (precision + exhaustividad)
          if (precision + exhaustividad) else 0.0)
    exactitud = (aciertos + rc) / total if total else 0.0
    return {
        "intentos": total,
        "aciertos": aciertos,
        "falsos_rechazos": fr,
        "falsas_aceptaciones": fa,
        "rechazos_correctos": rc,
        "exactitud": round(exactitud, 4),
        "precision": round(precision, 4),
        "exhaustividad": round(exhaustividad, 4),
        "f1": round(f1, 4),
        "tasa_falso_rechazo": round(fr / (aciertos + fr), 4) if (aciertos + fr) else 0.0,
    }


def evaluar(filas: list[dict]) -> dict:
    global_ = defaultdict(int)
    por_condicion: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    distancias = {"acierto": [], "falsa_aceptacion": []}

    for fila in filas:
        clase = clasificar(fila)
        global_[clase] += 1
        por_condicion[(fila.get("condicion") or "sin_dato").strip()][clase] += 1
        if clase in distancias and fila.get("distancia"):
            try:
                distancias[clase].append(float(fila["distancia"]))
            except ValueError:
                pass

    informe = {
        "global": metricas(global_),
        "por_condicion": {c: metricas(v) for c, v in sorted(por_condicion.items())},
        "distancia_media": {
            k: round(sum(v) / len(v), 4) if v else None for k, v in distancias.items()
        },
        "hipotesis": HIPOTESIS,
    }
    informe["cumple_hipotesis"] = informe["global"]["exactitud"] >= HIPOTESIS
    return informe


def imprimir(informe: dict) -> None:
    g = informe["global"]
    print("\n== Reconocimiento facial: resultado global ==")
    for clave in ("intentos", "aciertos", "falsos_rechazos", "falsas_aceptaciones",
                  "rechazos_correctos"):
        print(f"  {clave:<22}{g[clave]:>6}")
    for clave in ("exactitud", "precision", "exhaustividad", "f1", "tasa_falso_rechazo"):
        print(f"  {clave:<22}{g[clave]:>9.3f}")
    print(f"\n  Hipotesis (exactitud >= {HIPOTESIS:.0%}): "
          f"{'CUMPLE' if informe['cumple_hipotesis'] else 'NO CUMPLE'}")

    print("\n== Por condicion ==")
    print(f"  {'Condicion':<18}{'Intentos':>9}{'Exactitud':>11}{'F. rechazo':>12}{'F. acept.':>11}")
    for condicion, m in informe["por_condicion"].items():
        print(f"  {condicion:<18}{m['intentos']:>9}{m['exactitud']:>11.3f}"
              f"{m['falsos_rechazos']:>12}{m['falsas_aceptaciones']:>11}")

    print("\nRecuerde: son intentos repetidos con las mismas personas. Describen el")
    print("desempeno en estas condiciones, no el de toda una poblacion universitaria.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Metricas del reconocimiento facial")
    parser.add_argument("csv", help="archivo con los intentos")
    parser.add_argument("--salida", default="evaluacion_reconocimiento.json")
    args = parser.parse_args()

    with open(args.csv, encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo))
    faltan = {"documento_real", "resultado", "documento"} - set(filas[0] if filas else {})
    if faltan:
        print(f"Al CSV le faltan columnas: {', '.join(sorted(faltan))}")
        return 1

    informe = evaluar(filas)
    imprimir(informe)
    Path(args.salida).write_text(json.dumps(informe, indent=2, ensure_ascii=False),
                                 encoding="utf-8")
    print(f"\nInforme guardado en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
