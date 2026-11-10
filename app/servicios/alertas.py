"""Ciclo de vida de las alertas de arma visible (procesos P3 y P4).

Concentra la maquina de estados de la clase AlertaArma. Mantenerla aqui, y no
repartida por los endpoints, es lo que permite garantizar que una alerta no se
salte pasos: no se puede cerrar algo que nadie atendio, ni atender algo que ya
se cerro.

Los estados y las transiciones son los mismos del diagrama de estados y los
mismos que admite la restriccion CHECK de la tabla.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..config import Config

log = logging.getLogger(__name__)

GENERADA = "generada"
NOTIFICADA = "notificada"
EN_ATENCION = "en_atencion"
ESCALADA = "escalada"
CONFIRMADA = "confirmada"
FALSO_POSITIVO = "falso_positivo"
CERRADA = "cerrada"

ESTADOS = (GENERADA, NOTIFICADA, EN_ATENCION, ESCALADA,
           CONFIRMADA, FALSO_POSITIVO, CERRADA)

# Que puede seguir a que. Cualquier salto fuera de este mapa es un error.
TRANSICIONES: dict[str, tuple[str, ...]] = {
    GENERADA: (NOTIFICADA, ESCALADA),
    NOTIFICADA: (EN_ATENCION, ESCALADA),
    ESCALADA: (EN_ATENCION,),
    EN_ATENCION: (CONFIRMADA, FALSO_POSITIVO),
    CONFIRMADA: (CERRADA,),
    FALSO_POSITIVO: (CERRADA,),
    CERRADA: (),
}

# Estados cuya transicion exige saber que usuario la ejecuta.
EXIGEN_USUARIO = (EN_ATENCION, CONFIRMADA, FALSO_POSITIVO)


class TransicionInvalida(Exception):
    """La alerta no puede pasar del estado actual al solicitado."""


def transicion_valida(actual: str, siguiente: str) -> bool:
    return siguiente in TRANSICIONES.get(actual, ())


def _repo(repositorio):
    if repositorio is not None:
        return repositorio
    from .. import repositorio as repositorio_real

    return repositorio_real


def cambiar_estado(
    alerta_id: int,
    nuevo_estado: str,
    usuario_id: Optional[int] = None,
    repositorio=None,
) -> dict:
    """Mueve la alerta a otro estado validando la transicion.

    Raises:
        TransicionInvalida: el salto no esta permitido o falta el responsable.
    """
    repo = _repo(repositorio)

    if nuevo_estado not in ESTADOS:
        raise TransicionInvalida(f"estado desconocido: {nuevo_estado}")

    alerta = repo.obtener_alerta(alerta_id)
    if alerta is None:
        raise TransicionInvalida(f"la alerta {alerta_id} no existe")

    actual = alerta["estado"]
    if not transicion_valida(actual, nuevo_estado):
        raise TransicionInvalida(
            f"no se puede pasar de '{actual}' a '{nuevo_estado}'"
        )
    if nuevo_estado in EXIGEN_USUARIO and usuario_id is None:
        raise TransicionInvalida(
            f"el estado '{nuevo_estado}' exige registrar al usuario responsable"
        )

    repo.actualizar_estado_alerta(
        alerta_id,
        nuevo_estado,
        usuario_id=usuario_id,
        escalada=(nuevo_estado == ESCALADA),
    )
    log.info("Alerta %s: %s -> %s", alerta_id, actual, nuevo_estado)
    return {"alerta_id": alerta_id, "anterior": actual, "estado": nuevo_estado}


def notificar(alerta_id: int, repositorio=None) -> dict:
    return cambiar_estado(alerta_id, NOTIFICADA, repositorio=repositorio)


def atender(alerta_id: int, usuario_id: int, repositorio=None) -> dict:
    return cambiar_estado(alerta_id, EN_ATENCION, usuario_id, repositorio)


def resolver(alerta_id: int, usuario_id: int, confirmada: bool, repositorio=None) -> dict:
    """Cierra la alerta como amenaza confirmada o como falso positivo."""
    estado = CONFIRMADA if confirmada else FALSO_POSITIVO
    cambiar_estado(alerta_id, estado, usuario_id, repositorio)
    return cambiar_estado(alerta_id, CERRADA, repositorio=repositorio)


def escalar_pendientes(repositorio=None, minutos: Optional[int] = None) -> list[int]:
    """Sube al administrador las alertas que nadie atendio (RF-14).

    Se invoca desde el endpoint de escalamiento, que a su vez puede llamarse
    desde una tarea programada. Devuelve los identificadores escalados.
    """
    repo = _repo(repositorio)
    minutos = Config.MINUTOS_ESCALAMIENTO if minutos is None else minutos

    escaladas: list[int] = []
    for alerta in repo.alertas_sin_atender(minutos):
        try:
            cambiar_estado(alerta["id"], ESCALADA, repositorio=repo)
            escaladas.append(alerta["id"])
        except TransicionInvalida as exc:
            log.warning("No se pudo escalar la alerta %s: %s", alerta["id"], exc)
    if escaladas:
        log.info("Alertas escaladas al administrador: %s", escaladas)
    return escaladas
