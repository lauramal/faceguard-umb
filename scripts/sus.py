"""Calculo del puntaje System Usability Scale (RNF-05).

El SUS no se promedia directamente. Las preguntas impares son positivas y las
pares negativas, de modo que cada tipo se convierte distinto antes de sumar.
Hacerlo a mano es donde suele colarse el error.

Formato del archivo de entrada (CSV, una fila por participante):

    participante,p1,p2,p3,p4,p5,p6,p7,p8,p9,p10
    guardia_1,4,2,5,1,4,2,5,2,4,2
    guardia_2,5,1,4,2,5,1,4,1,5,1

Cada respuesta va de 1 (muy en desacuerdo) a 5 (muy de acuerdo).

Uso:
    python scripts/sus.py respuestas.csv
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

META = 68.0          # meta del RNF-05


def puntaje(respuestas: list[int]) -> float:
    """Convierte diez respuestas en un puntaje SUS de 0 a 100.

    Impares (positivas): se resta 1 al valor.
    Pares (negativas): se resta el valor a 5.
    La suma se multiplica por 2.5.
    """
    if len(respuestas) != 10:
        raise ValueError(f"se esperaban 10 respuestas y llegaron {len(respuestas)}")
    if any(not 1 <= r <= 5 for r in respuestas):
        raise ValueError("todas las respuestas deben estar entre 1 y 5")

    total = 0
    for indice, valor in enumerate(respuestas, start=1):
        total += (valor - 1) if indice % 2 else (5 - valor)
    return total * 2.5


def interpretar(valor: float) -> str:
    if valor >= 80:
        return "excelente"
    if valor >= META:
        return "por encima del promedio"
    if valor >= 51:
        return "por debajo del promedio"
    return "deficiente"


def main() -> int:
    parser = argparse.ArgumentParser(description="Puntaje SUS del panel web")
    parser.add_argument("archivo", help="CSV con las respuestas")
    args = parser.parse_args()

    ruta = Path(args.archivo)
    if not ruta.exists():
        print(f"No se encontro {ruta}")
        return 1

    puntajes: dict[str, float] = {}
    with ruta.open(encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            nombre = fila.get("participante") or f"p{len(puntajes) + 1}"
            try:
                respuestas = [int(fila[f"p{i}"]) for i in range(1, 11)]
                puntajes[nombre] = puntaje(respuestas)
            except (KeyError, ValueError) as exc:
                print(f"Fila '{nombre}' descartada: {exc}")

    if not puntajes:
        print("No se pudo calcular ningun puntaje. Revise el formato del CSV.")
        return 1

    print(f"\n{'Participante':<24}{'Puntaje':>9}  Lectura")
    print("-" * 62)
    for nombre, valor in puntajes.items():
        print(f"{nombre:<24}{valor:>9.1f}  {interpretar(valor)}")

    media = statistics.mean(puntajes.values())
    print("-" * 62)
    print(f"{'PROMEDIO':<24}{media:>9.1f}  {interpretar(media)}")
    if len(puntajes) > 1:
        print(f"{'Desviacion estandar':<24}{statistics.stdev(puntajes.values()):>9.1f}")
    print(f"{'Mediana':<24}{statistics.median(puntajes.values()):>9.1f}")

    print(f"\nRNF-05 (meta {META:.0f}): "
          f"{'CUMPLE' if media >= META else 'NO CUMPLE'}")
    if media < META:
        print("Revise donde se trabaron los participantes y ajuste la interfaz "
              "antes de repetir la medicion.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
