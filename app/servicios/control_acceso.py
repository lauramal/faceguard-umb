"""Orquestacion del proceso P2, registro de ingreso y salida.

Este servicio es el que une el modulo de reconocimiento facial con la base de
datos. Recibe un fotograma, obtiene la codificacion, la compara contra el
catalogo y decide si el evento es un ingreso o una salida.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..config import Config
from .reconocimiento_facial import (
    Identificacion,
    RostroNoDetectado,
    codificar_rostro,
    identificar,
)

log = logging.getLogger(__name__)


@dataclass
class ResultadoAcceso:
    """Lo que el punto de acceso devuelve tras procesar un fotograma."""

    identificado: bool
    estudiante_id: Optional[int] = None
    nombre: Optional[str] = None
    tipo_evento: Optional[str] = None
    confianza: float = 0.0
    registro_id: Optional[int] = None
    motivo: Optional[str] = None
    milisegundos: float = 0.0

    def a_dict(self) -> dict:
        return {
            "identificado": self.identificado,
            "estudiante_id": self.estudiante_id,
            "nombre": self.nombre,
            "tipo_evento": self.tipo_evento,
            "confianza": round(self.confianza, 4),
            "registro_id": self.registro_id,
            "motivo": self.motivo,
            "milisegundos": round(self.milisegundos, 1),
        }


def _siguiente_evento(ultimo: Optional[str]) -> str:
    """Alterna entre ingreso y salida.

    Si no hay registro previo el evento es un ingreso. Si el ultimo fue un
    ingreso, el siguiente es una salida, y viceversa. Es la regla que describe
    el diagrama de estados de la clase RegistroAcceso.
    """
    return "salida" if ultimo == "ingreso" else "ingreso"


def procesar_fotograma(
    imagen_rgb: np.ndarray,
    punto_acceso_id: int,
    repositorio=None,
) -> ResultadoAcceso:
    """Procesa un fotograma capturado en un punto de acceso.

    El parametro repositorio se inyecta para poder sustituirlo en las pruebas.
    Cuando no se pasa, se usa el repositorio real contra PostgreSQL.
    """
    if repositorio is None:
        from .. import repositorio as repositorio_real

        repositorio = repositorio_real

    inicio = time.perf_counter()

    try:
        codificacion = codificar_rostro(imagen_rgb, estricto=False)
    except RostroNoDetectado:
        return ResultadoAcceso(
            identificado=False,
            motivo="sin_rostro",
            milisegundos=(time.perf_counter() - inicio) * 1000,
        )

    catalogo = repositorio.cargar_catalogo()
    resultado: Identificacion = identificar(
        codificacion,
        catalogo,
        umbral_confianza=Config.UMBRAL_CONFIANZA,
        umbral_distancia=Config.UMBRAL_DISTANCIA,
    )

    if not resultado.identificado:
        # El sistema no adivina. Deja el evento sin registrar y lo pasa al
        # guardia, que es quien verifica. Esa es la logica de apoyo al rol
        # humano que sostiene todo el proyecto.
        log.info("Rostro no identificado en el punto %s", punto_acceso_id)
        return ResultadoAcceso(
            identificado=False,
            confianza=resultado.confianza,
            motivo="confianza_insuficiente",
            milisegundos=(time.perf_counter() - inicio) * 1000,
        )

    estudiante = repositorio.obtener_estudiante(resultado.estudiante_id)
    if estudiante is None:
        return ResultadoAcceso(
            identificado=False,
            motivo="estudiante_inexistente",
            milisegundos=(time.perf_counter() - inicio) * 1000,
        )

    ultimo = repositorio.ultimo_evento(resultado.estudiante_id)
    tipo_evento = _siguiente_evento(ultimo)

    registro_id = repositorio.registrar_acceso(
        estudiante_id=resultado.estudiante_id,
        punto_acceso_id=punto_acceso_id,
        tipo_evento=tipo_evento,
        confianza=resultado.confianza,
    )

    return ResultadoAcceso(
        identificado=True,
        estudiante_id=resultado.estudiante_id,
        nombre=f"{estudiante['nombres']} {estudiante['apellidos']}",
        tipo_evento=tipo_evento,
        confianza=resultado.confianza,
        registro_id=registro_id,
        milisegundos=(time.perf_counter() - inicio) * 1000,
    )
