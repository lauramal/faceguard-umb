"""Modulo de deteccion de armas. Pendiente para el sprint 3.

La interfaz queda definida desde ahora para que el backend y la plataforma web
puedan integrarse sin reescribir codigo cuando el modelo YOLOv8 este
entrenado. Corresponde al objetivo especifico 4 del trabajo de grado.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np

from ..config import Config

CLASES_ARMA = ("arma_de_fuego", "arma_blanca")


@dataclass(frozen=True)
class Deteccion:
    tipo_arma: str
    confianza: float
    caja: tuple[int, int, int, int]  # x1, y1, x2, y2


class DetectorArmas:
    """Envoltorio del modelo YOLOv8.

    La carga del modelo es diferida para no penalizar el arranque de la
    aplicacion mientras el modulo no este en uso.
    """

    def __init__(self, ruta_modelo: str | None = None, umbral: float | None = None):
        self.ruta_modelo = ruta_modelo or Config.MODELO_YOLO
        self.umbral = umbral if umbral is not None else Config.UMBRAL_ARMA
        self._modelo = None

    def _cargar(self):
        if self._modelo is None:
            from ultralytics import YOLO  # type: ignore

            self._modelo = YOLO(self.ruta_modelo)
        return self._modelo

    def detectar(self, imagen_rgb: np.ndarray) -> List[Deteccion]:
        """Devuelve las armas detectadas por encima del umbral de confianza."""
        modelo = self._cargar()
        salida = modelo.predict(imagen_rgb, conf=self.umbral, verbose=False)

        detecciones: List[Deteccion] = []
        for resultado in salida:
            for caja in resultado.boxes:
                etiqueta = resultado.names[int(caja.cls)]
                if etiqueta not in CLASES_ARMA:
                    continue
                x1, y1, x2, y2 = (int(v) for v in caja.xyxy[0])
                detecciones.append(
                    Deteccion(
                        tipo_arma=etiqueta,
                        confianza=float(caja.conf),
                        caja=(x1, y1, x2, y2),
                    )
                )
        return detecciones
