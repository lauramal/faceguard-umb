"""Orquestacion del proceso P2, registro de ingreso y salida.

Este servicio une el modulo de reconocimiento facial con la base de datos.
Recibe un fotograma, obtiene la codificacion, la compara contra el catalogo y
decide si el evento es un ingreso o una salida.

Tres reglas gobiernan el proceso:

1. La identidad se decide sobre la distancia, no sobre la confianza.
2. Los eventos no identificados TAMBIEN se registran, con su evidencia, para
   que el guardia los verifique (RF-11). El sistema no adivina, pero tampoco
   olvida.
3. Una misma persona no genera un registro por fotograma. La ventana
   antirrebote evita que quien se queda frente a la camara produzca una
   secuencia absurda de ingresos y salidas alternados.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
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
    persona_id: Optional[int] = None
    nombre: Optional[str] = None
    tipo_evento: Optional[str] = None
    metodo: str = "facial"
    resultado: Optional[str] = None
    distancia: Optional[float] = None
    confianza: float = 0.0
    registro_id: Optional[int] = None
    motivo: Optional[str] = None
    milisegundos: float = 0.0

    def a_dict(self) -> dict:
        return {
            "identificado": self.identificado,
            "persona_id": self.persona_id,
            "nombre": self.nombre,
            "tipo_evento": self.tipo_evento,
            "metodo": self.metodo,
            "resultado": self.resultado,
            "distancia": None if self.distancia is None else round(self.distancia, 4),
            "confianza": round(self.confianza, 4),
            "registro_id": self.registro_id,
            "motivo": self.motivo,
            "milisegundos": round(self.milisegundos, 1),
        }


def siguiente_evento(ultimo_tipo: Optional[str]) -> str:
    """Alterna entre ingreso y salida.

    Si no hay registro previo el evento es un ingreso. Si el ultimo fue un
    ingreso, el siguiente es una salida, y viceversa. Es la regla que describe
    el diagrama de estados de la clase RegistroAcceso.
    """
    return "salida" if ultimo_tipo == "ingreso" else "ingreso"


def es_rebote(ultimo: Optional[dict], ahora: Optional[datetime] = None) -> bool:
    """Decide si el evento repite uno reciente de la misma persona.

    La estacion analiza un fotograma por segundo. Sin esta comprobacion, una
    persona parada cinco segundos frente a la camara dejaria cinco registros
    alternando ingreso y salida, y el historial quedaria inservible.
    """
    if not ultimo or not ultimo.get("fecha_hora"):
        return False
    ahora = ahora or datetime.now()
    ventana = timedelta(seconds=Config.VENTANA_ANTIREBOTE)
    return (ahora - ultimo["fecha_hora"]) < ventana


def _repo(repositorio):
    if repositorio is not None:
        return repositorio
    from .. import repositorio as repositorio_real

    return repositorio_real


def procesar_codificacion(
    codificacion: np.ndarray,
    punto_acceso_id: int,
    camara_id: Optional[int] = None,
    imagen_url: Optional[str] = None,
    repositorio=None,
) -> ResultadoAcceso:
    """Resuelve un evento a partir de una codificacion ya calculada (CU-02).

    Esta es la via principal del sistema. La estacion de captura calcula el
    embedding en el punto de acceso, donde si viven dlib y YOLOv8, y envia al
    servidor un vector de 128 numeros. El servidor solo necesita numpy para
    comparar, que es lo que permite desplegarlo en un plan gratuito (RNF-11).

    Como efecto secundario, las imagenes de los rostros nunca salen del equipo
    local, lo que refuerza la minimizacion de datos frente a la Ley 1581.

    El parametro repositorio se inyecta para poder sustituirlo en las pruebas.
    """
    repo = _repo(repositorio)
    inicio = time.perf_counter()

    def transcurrido() -> float:
        return (time.perf_counter() - inicio) * 1000

    catalogo = repo.cargar_catalogo()
    resultado: Identificacion = identificar(
        codificacion, catalogo, umbral_distancia=Config.UMBRAL_DISTANCIA
    )

    # ---- No identificado: se registra igual, con evidencia ----------------
    if not resultado.identificado:
        log.info("Rostro no identificado en el punto %s", punto_acceso_id)
        registro_id = repo.registrar_acceso(
            punto_acceso_id=punto_acceso_id,
            camara_id=camara_id,
            persona_id=None,
            tipo_evento="ingreso",
            metodo="facial",
            resultado="no_identificado",
            distancia=None if resultado.distancia == float("inf") else resultado.distancia,
            confianza=resultado.confianza,
            imagen_url=imagen_url,
        )
        return ResultadoAcceso(
            identificado=False,
            resultado="no_identificado",
            distancia=None if resultado.distancia == float("inf") else resultado.distancia,
            confianza=resultado.confianza,
            registro_id=registro_id,
            motivo="requiere_verificacion_manual",
            milisegundos=transcurrido(),
        )

    persona = repo.obtener_persona(resultado.persona_id)
    if persona is None:
        return ResultadoAcceso(
            identificado=False, motivo="persona_inexistente", milisegundos=transcurrido()
        )

    ultimo = repo.ultimo_registro(resultado.persona_id)

    # ---- Rebote: se reconoce pero no se vuelve a registrar ----------------
    if es_rebote(ultimo):
        return ResultadoAcceso(
            identificado=True,
            persona_id=resultado.persona_id,
            nombre=f"{persona['nombres']} {persona['apellidos']}",
            tipo_evento=ultimo["tipo_evento"],
            distancia=resultado.distancia,
            confianza=resultado.confianza,
            registro_id=ultimo["id"],
            motivo="evento_reciente_omitido",
            milisegundos=transcurrido(),
        )

    tipo_evento = siguiente_evento(ultimo["tipo_evento"] if ultimo else None)
    registro_id = repo.registrar_acceso(
        punto_acceso_id=punto_acceso_id,
        camara_id=camara_id,
        persona_id=resultado.persona_id,
        tipo_evento=tipo_evento,
        metodo="facial",
        resultado="identificado",
        distancia=resultado.distancia,
        confianza=resultado.confianza,
    )

    return ResultadoAcceso(
        identificado=True,
        persona_id=resultado.persona_id,
        nombre=f"{persona['nombres']} {persona['apellidos']}",
        tipo_evento=tipo_evento,
        resultado="identificado",
        distancia=resultado.distancia,
        confianza=resultado.confianza,
        registro_id=registro_id,
        milisegundos=transcurrido(),
    )


def procesar_fotograma(
    imagen_rgb: np.ndarray,
    punto_acceso_id: int,
    camara_id: Optional[int] = None,
    imagen_url: Optional[str] = None,
    repositorio=None,
) -> ResultadoAcceso:
    """Codifica el fotograma y resuelve el evento, todo en el mismo proceso.

    Via auxiliar, pensada para el montaje de demostracion en el que la
    estacion y el backend corren en el mismo equipo. Requiere dlib, de modo
    que NO debe invocarse en el servidor desplegado: alli se usa
    procesar_codificacion.
    """
    inicio = time.perf_counter()
    try:
        codificacion = codificar_rostro(imagen_rgb, estricto=False)
    except RostroNoDetectado:
        return ResultadoAcceso(
            identificado=False, motivo="sin_rostro",
            milisegundos=(time.perf_counter() - inicio) * 1000,
        )
    return procesar_codificacion(
        codificacion, punto_acceso_id, camara_id, imagen_url, repositorio
    )


def registrar_con_credencial(
    persona_id: int,
    punto_acceso_id: int,
    repositorio=None,
) -> ResultadoAcceso:
    """Ingreso de quien no autorizo el tratamiento biometrico (RF-13, CU-11).

    Produce exactamente el mismo registro de acceso que la via facial, solo
    que con metodo 'credencial' y sin distancia ni confianza. Que una persona
    ejerza su derecho a no entregar su rostro no puede dejarla fuera del
    historial institucional.
    """
    repo = _repo(repositorio)
    inicio = time.perf_counter()

    persona = repo.obtener_persona(persona_id)
    if persona is None:
        return ResultadoAcceso(
            identificado=False,
            metodo="credencial",
            motivo="persona_inexistente",
            milisegundos=(time.perf_counter() - inicio) * 1000,
        )

    ultimo = repo.ultimo_registro(persona_id)
    if es_rebote(ultimo):
        return ResultadoAcceso(
            identificado=True,
            persona_id=persona_id,
            nombre=f"{persona['nombres']} {persona['apellidos']}",
            tipo_evento=ultimo["tipo_evento"],
            metodo="credencial",
            registro_id=ultimo["id"],
            motivo="evento_reciente_omitido",
            milisegundos=(time.perf_counter() - inicio) * 1000,
        )

    tipo_evento = siguiente_evento(ultimo["tipo_evento"] if ultimo else None)
    registro_id = repo.registrar_acceso(
        punto_acceso_id=punto_acceso_id,
        persona_id=persona_id,
        tipo_evento=tipo_evento,
        metodo="credencial",
        resultado="identificado",
    )
    return ResultadoAcceso(
        identificado=True,
        persona_id=persona_id,
        nombre=f"{persona['nombres']} {persona['apellidos']}",
        tipo_evento=tipo_evento,
        metodo="credencial",
        resultado="identificado",
        registro_id=registro_id,
        milisegundos=(time.perf_counter() - inicio) * 1000,
    )
