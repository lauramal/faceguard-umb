"""Modulo de deteccion de armas visibles (objetivo especifico 4).

Detecta armas que estan a la vista o empunadas. Una camara no ve lo que va
dentro de un bolso ni debajo de una chaqueta, de modo que el alcance del
modulo es exactamente ese y asi se declara en el documento.

El modelo se inyecta en el constructor para poder probar la logica de
filtrado y de traduccion de etiquetas sin cargar YOLOv8 ni sus pesos.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, List, Optional

import numpy as np

from ..config import Config

log = logging.getLogger(__name__)

# Vocabulario que entiende la base de datos (columna alerta_arma.tipo_arma).
ARMA_FUEGO = "arma_fuego"
ARMA_BLANCA = "arma_blanca"
INDETERMINADA = "indeterminada"

# Traduccion de las etiquetas del dataset de entrenamiento al vocabulario
# del sistema. Los datasets publicos usan nombres variados, asi que conviene
# centralizar la equivalencia en un solo sitio.
EQUIVALENCIAS = {
    "pistol": ARMA_FUEGO,
    "gun": ARMA_FUEGO,
    "handgun": ARMA_FUEGO,
    "rifle": ARMA_FUEGO,
    "firearm": ARMA_FUEGO,
    "arma_de_fuego": ARMA_FUEGO,
    "arma_fuego": ARMA_FUEGO,
    "knife": ARMA_BLANCA,
    "blade": ARMA_BLANCA,
    "machete": ARMA_BLANCA,
    "arma_blanca": ARMA_BLANCA,
}


@dataclass(frozen=True)
class Deteccion:
    tipo_arma: str
    confianza: float
    caja: tuple[int, int, int, int]      # x1, y1, x2, y2


def traducir_etiqueta(etiqueta: str) -> Optional[str]:
    """Convierte la clase del modelo al vocabulario del sistema.

    Devuelve None cuando la clase no corresponde a un arma, que es lo que
    ocurre con un celular, una sombrilla o cualquier otro objeto del dataset.
    """
    return EQUIVALENCIAS.get(str(etiqueta).strip().lower())


class DetectorArmas:
    """Envoltorio del modelo YOLOv8.

    La carga del modelo es diferida para no penalizar el arranque de la
    aplicacion mientras el modulo no este en uso.
    """

    def __init__(
        self,
        ruta_modelo: Optional[str] = None,
        umbral: Optional[float] = None,
        modelo: Any = None,
    ):
        self.ruta_modelo = ruta_modelo or Config.MODELO_YOLO
        self.umbral = umbral if umbral is not None else Config.UMBRAL_ARMA
        self._modelo = modelo

    def _cargar(self):
        if self._modelo is None:                      # pragma: no cover
            from ultralytics import YOLO  # type: ignore

            self._modelo = YOLO(self.ruta_modelo)
        return self._modelo

    def detectar(self, imagen_rgb: np.ndarray) -> List[Deteccion]:
        """Devuelve las armas visibles detectadas por encima del umbral.

        Descarta las clases que no son armas y las detecciones cuya confianza
        no alcanza el umbral. Subir el umbral reduce las falsas alarmas, que
        es el riesgo real del modulo: un guardia que recibe avisos
        equivocados termina por ignorarlos todos.
        """
        modelo = self._cargar()
        salida = modelo.predict(imagen_rgb, conf=self.umbral, verbose=False)

        detecciones: List[Deteccion] = []
        for resultado in salida:
            for caja in resultado.boxes:
                etiqueta = resultado.names[int(caja.cls)]
                tipo = traducir_etiqueta(etiqueta)
                if tipo is None:
                    log.debug("Clase ignorada por no ser arma: %s", etiqueta)
                    continue
                confianza = float(caja.conf)
                if confianza < self.umbral:
                    continue
                x1, y1, x2, y2 = (int(v) for v in caja.xyxy[0])
                detecciones.append(
                    Deteccion(tipo_arma=tipo, confianza=confianza, caja=(x1, y1, x2, y2))
                )
        return detecciones

    def mas_probable(self, imagen_rgb: np.ndarray) -> Optional[Deteccion]:
        """La deteccion de mayor confianza, que es la que genera la alerta."""
        detecciones = self.detectar(imagen_rgb)
        return max(detecciones, key=lambda d: d.confianza) if detecciones else None
