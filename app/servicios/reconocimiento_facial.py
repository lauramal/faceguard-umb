"""Modulo de reconocimiento facial de FaceGuard.

Cubre el objetivo especifico 3 del trabajo de grado. Se apoya en la libreria
face_recognition (construida sobre dlib) para obtener la codificacion de 128
dimensiones de un rostro, y resuelve la identificacion comparando esa
codificacion contra el catalogo almacenado en la base de datos.

La comparacion se implementa con numpy y no depende de dlib, de manera que
puede probarse de forma aislada. Esa separacion responde al RNF-08, que exige
una arquitectura modular.

Sobre el criterio de decision
-----------------------------
La identidad se decide sobre la DISTANCIA euclidiana entre codificaciones.
Dos fotografias de la misma persona suelen quedar entre 0.30 y 0.55; dos
personas distintas, por encima de 0.60. Ese 0.60 es el umbral de referencia
que recomiendan los autores de dlib.

La confianza es una lectura normalizada de la distancia, pensada para el
reporte y para el panel del guardia. No es el criterio de corte. El 85 % que
aparece en la hipotesis se refiere a la precision global del sistema medida
sobre el conjunto de pruebas, no a la confianza exigida en cada comparacion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

import numpy as np

log = logging.getLogger(__name__)

# Distancia euclidiana maxima admitida entre dos codificaciones para
# considerarlas de la misma persona.
UMBRAL_DISTANCIA = 0.6

DIMENSIONES = 128


@dataclass(frozen=True)
class Candidato:
    """Codificacion facial de una persona ya enrolada."""

    persona_id: int
    vector: np.ndarray


@dataclass(frozen=True)
class Identificacion:
    """Resultado de comparar un rostro contra el catalogo."""

    persona_id: Optional[int]
    distancia: float
    confianza: float

    @property
    def identificado(self) -> bool:
        return self.persona_id is not None


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
            "pip install -r requirements-estacion.txt"
        ) from exc
    return face_recognition


def _area(ubicacion) -> int:
    """Area del recuadro (top, right, bottom, left) que devuelve dlib."""
    arriba, derecha, abajo, izquierda = ubicacion
    return max(0, abajo - arriba) * max(0, derecha - izquierda)


def codificar_rostro(imagen_rgb: np.ndarray, *, estricto: bool = True) -> np.ndarray:
    """Devuelve la codificacion de 128 dimensiones del rostro de la imagen.

    Cuando la imagen contiene varias caras y no se exige exclusividad, se
    elige la de mayor area, que corresponde a la persona mas cercana a la
    camara. Quedarse con la primera que devuelve dlib era un error, porque
    ese orden es arbitrario y podia codificar a alguien del fondo.

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

    principal = max(ubicaciones, key=_area)
    codificaciones = fr.face_encodings(imagen_rgb, [principal])
    return np.asarray(codificaciones[0], dtype=np.float64)


def promediar_codificaciones(codificaciones: Sequence[np.ndarray]) -> np.ndarray:
    """Combina varias capturas de la misma persona en una sola codificacion.

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
    return float(
        np.linalg.norm(
            np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)
        )
    )


def confianza_desde_distancia(dist: float, umbral: float = UMBRAL_DISTANCIA) -> float:
    """Convierte una distancia en un valor informativo entre 0 y 1.

    Una distancia de cero equivale a confianza 1 y una distancia igual al
    umbral equivale a confianza 0. El valor se guarda en
    registro_acceso.confianza y se muestra en el panel, pero la decision de
    identidad se toma sobre la distancia, no sobre este numero.
    """
    if umbral <= 0:
        raise ValueError("El umbral debe ser mayor que cero")
    return float(max(0.0, min(1.0, 1.0 - dist / umbral)))


def identificar(
    codificacion: np.ndarray,
    catalogo: Iterable[Candidato],
    *,
    umbral_distancia: float = UMBRAL_DISTANCIA,
) -> Identificacion:
    """Compara una codificacion contra el catalogo y devuelve el mejor match.

    Implementa el nucleo del CU-02. Recorre las codificaciones almacenadas, se
    queda con la de menor distancia y declara identificada a la persona solo
    si esa distancia queda por debajo del umbral. Por encima, el evento se
    reporta como no identificado y pasa a verificacion manual del guardia, que
    es el rol de apoyo humano que sostiene el proyecto.
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
            mejor_id = candidato.persona_id

    if mejor_id is None:
        log.warning("El catalogo de codificaciones esta vacio")
        return Identificacion(None, float("inf"), 0.0)

    conf = confianza_desde_distancia(mejor_distancia, umbral_distancia)

    if mejor_distancia > umbral_distancia:
        log.info(
            "Rostro no identificado, mejor distancia %.4f por encima del umbral %.2f",
            mejor_distancia,
            umbral_distancia,
        )
        return Identificacion(None, mejor_distancia, conf)

    return Identificacion(mejor_id, mejor_distancia, conf)
