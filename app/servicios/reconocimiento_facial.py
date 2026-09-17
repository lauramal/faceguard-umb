"""Modulo de reconocimiento facial de FaceGuard UMB.

Cubre el objetivo especifico 3 del trabajo de grado. Se apoya en la libreria
face_recognition (construida sobre dlib) para obtener la codificacion de 128
dimensiones de un rostro, y resuelve la identificacion comparando esa
codificacion contra el catalogo almacenado en la base de datos.

La comparacion se implementa con numpy y no depende de dlib, de manera que
puede probarse de forma aislada. Esa separacion responde al RNF-08, que exige
una arquitectura modular.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

import numpy as np

log = logging.getLogger(__name__)

# Distancia euclidiana maxima admitida entre dos codificaciones para
# considerarlas de la misma persona. 0.6 es el valor recomendado por los
# autores de dlib y el que se usara como punto de partida en las pruebas.
UMBRAL_DISTANCIA = 0.6

# Confianza minima para aceptar una identificacion y registrar el acceso.
# Se corresponde con el umbral de 85 % planteado en la hipotesis.
UMBRAL_CONFIANZA = 0.85

DIMENSIONES = 128


@dataclass(frozen=True)
class Candidato:
    """Codificacion facial de un estudiante ya enrolado."""

    estudiante_id: int
    vector: np.ndarray


@dataclass(frozen=True)
class Identificacion:
    """Resultado de comparar un rostro contra el catalogo."""

    estudiante_id: Optional[int]
    confianza: float
    distancia: float

    @property
    def identificado(self) -> bool:
        return self.estudiante_id is not None


class RostroNoDetectado(Exception):
    """Se lanza cuando en el fotograma no aparece ningun rostro."""


class VariosRostros(Exception):
    """Se lanza cuando el fotograma contiene mas de un rostro."""


def _cargar_face_recognition():
    """Importa face_recognition solo cuando se necesita.

    El enrolamiento y la identificacion en produccion requieren dlib, que es
    una dependencia pesada. Mantener la importacion diferida permite ejecutar
    las pruebas de la logica de comparacion en entornos sin dlib instalado.
    """
    try:
        import face_recognition  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "face_recognition no esta instalado. Ejecute "
            "pip install -r requirements.txt"
        ) from exc
    return face_recognition


def codificar_rostro(imagen_rgb: np.ndarray, *, estricto: bool = True) -> np.ndarray:
    """Devuelve la codificacion de 128 dimensiones del rostro de la imagen.

    Args:
        imagen_rgb: arreglo de la imagen en formato RGB.
        estricto: si es True exige que la imagen contenga exactamente un
            rostro. Se usa asi durante el enrolamiento (CU-01), donde una foto
            con dos personas invalidaria la codificacion.

    Raises:
        RostroNoDetectado: no se encontro ningun rostro.
        VariosRostros: se encontro mas de uno y estricto es True.
    """
    fr = _cargar_face_recognition()

    ubicaciones = fr.face_locations(imagen_rgb)
    if not ubicaciones:
        raise RostroNoDetectado("No se detecto ningun rostro en el fotograma")
    if estricto and len(ubicaciones) > 1:
        raise VariosRostros(f"Se detectaron {len(ubicaciones)} rostros")

    codificaciones = fr.face_encodings(imagen_rgb, ubicaciones[:1])
    return np.asarray(codificaciones[0], dtype=np.float64)


def promediar_codificaciones(codificaciones: Sequence[np.ndarray]) -> np.ndarray:
    """Combina varias capturas del mismo estudiante en una sola codificacion.

    El enrolamiento toma varias fotos con distintos angulos e iluminacion. El
    promedio de sus codificaciones es mas estable frente a las variaciones que
    documenta el marco teorico.
    """
    if not codificaciones:
        raise ValueError("Se requiere al menos una codificacion")
    matriz = np.vstack([np.asarray(c, dtype=np.float64) for c in codificaciones])
    if matriz.shape[1] != DIMENSIONES:
        raise ValueError(f"Las codificaciones deben tener {DIMENSIONES} dimensiones")
    return matriz.mean(axis=0)


def distancia(a: np.ndarray, b: np.ndarray) -> float:
    """Distancia euclidiana entre dos codificaciones."""
    return float(np.linalg.norm(np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)))


def confianza_desde_distancia(dist: float, umbral: float = UMBRAL_DISTANCIA) -> float:
    """Convierte una distancia en un valor de confianza entre 0 y 1.

    Una distancia de cero equivale a confianza 1. Una distancia igual al
    umbral equivale a confianza 0. El valor resultante es el que se guarda en
    registro_acceso.confianza y el que se contrasta contra el umbral de la
    hipotesis.
    """
    if umbral <= 0:
        raise ValueError("El umbral debe ser mayor que cero")
    return float(max(0.0, min(1.0, 1.0 - dist / umbral)))


def identificar(
    codificacion: np.ndarray,
    catalogo: Iterable[Candidato],
    *,
    umbral_confianza: float = UMBRAL_CONFIANZA,
    umbral_distancia: float = UMBRAL_DISTANCIA,
) -> Identificacion:
    """Compara una codificacion contra el catalogo y devuelve el mejor match.

    Implementa el nucleo del CU-02. Recorre las codificaciones almacenadas,
    se queda con la de menor distancia y solo declara identificado al
    estudiante si la confianza alcanza el umbral. Por debajo de ese valor el
    evento se reporta como no identificado y queda para verificacion manual
    del guardia, que es justamente el rol de apoyo que el sistema persigue.
    """
    codificacion = np.asarray(codificacion, dtype=np.float64)
    if codificacion.shape != (DIMENSIONES,):
        raise ValueError(f"La codificacion debe tener {DIMENSIONES} dimensiones")

    mejor_id: Optional[int] = None
    mejor_distancia = float("inf")

    for candidato in catalogo:
        d = distancia(codificacion, candidato.vector)
        if d < mejor_distancia:
            mejor_distancia = d
            mejor_id = candidato.estudiante_id

    if mejor_id is None:
        log.warning("El catalogo de codificaciones esta vacio")
        return Identificacion(None, 0.0, float("inf"))

    conf = confianza_desde_distancia(mejor_distancia, umbral_distancia)
    if conf < umbral_confianza:
        log.info(
            "Rostro no identificado, mejor confianza %.4f por debajo del umbral %.2f",
            conf,
            umbral_confianza,
        )
        return Identificacion(None, conf, mejor_distancia)

    return Identificacion(mejor_id, conf, mejor_distancia)
