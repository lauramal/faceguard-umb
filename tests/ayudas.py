"""Utilidades compartidas por las pruebas.

Los vectores constantes permiten construir casos con una distancia
euclidiana exacta y conocida, que es lo que hace verificables las pruebas
del umbral de reconocimiento.
"""

from __future__ import annotations

import numpy as np


def vector(valor: float = 0.0) -> np.ndarray:
    """Codificacion de 128 dimensiones con todos sus componentes iguales.

    La distancia entre vector(a) y vector(b) es sqrt(128) * |a - b|.
    """
    return np.full(128, valor, dtype=np.float64)


def vector_a_distancia(base: float, distancia_objetivo: float) -> np.ndarray:
    """Devuelve un vector que dista exactamente lo pedido de vector(base)."""
    delta = distancia_objetivo / np.sqrt(128)
    return np.full(128, base + delta, dtype=np.float64)
