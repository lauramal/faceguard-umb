"""Ciclo de vida de las alertas de arma visible (procesos P3 y P4).

Concentra la maquina de estados de la clase AlertaArma. Mantenerla aqui, y no
repartida por los endpoints, es lo que permite garantizar que una alerta no se
salte pasos: no se puede cerrar algo que nadie atendio, ni atender algo que ya
se cerro.

Los estados y las transiciones son los mismos del diagrama de estados y los
mismos que admite la restriccion CHECK de la tabla.

Tambien decide como entra una deteccion al sistema:

* Una misma arma vista en fotogramas seguidos no abre una alerta por
  fotograma. Si ya hay una alerta abierta del mismo tipo en la misma camara,
  la deteccion se suma a ella.
* La persona identificada en el mismo momento queda como CONTEXTO de la
  alerta, no como portadora. Que alguien aparezca en el mismo fotograma que
  un arma no prueba que la lleve: puede estar al lado de quien la porta. El
  portador solo se registra cuando el guardia, viendo la evidencia, confirma
  la alerta e indica a quien corresponde.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
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


def resolver(
    alerta_id: int,
    usuario_id: int,
    confirmada: bool,
    repositorio=None,
    portador_id: Optional[int] = None,
) -> dict:
    """Cierra la alerta como amenaza confirmada o como falso positivo.

    Al confirmar, el guardia puede indicar quien porta el arma. Es la unica
    via por la que una alerta queda atribuida a una persona. Un falso
    positivo no admite portador.
    """
    repo = _repo(repositorio)
    if portador_id is not None and not confirmada:
        raise TransicionInvalida("un falso positivo no puede tener portador")
    if portador_id is not None and repo.obtener_persona(portador_id) is None:
        raise TransicionInvalida(f"la persona {portador_id} no existe")

    estado = CONFIRMADA if confirmada else FALSO_POSITIVO
    cambiar_estado(alerta_id, estado, usuario_id, repo)
    if portador_id is not None:
        repo.asignar_portador(alerta_id, portador_id)
    repo.registrar_desenlace(alerta_id, estado)
    resultado = cambiar_estado(alerta_id, CERRADA, repositorio=repo)
    resultado["desenlace"] = estado
    resultado["portador_id"] = portador_id
    return resultado


# Segundos maximos entre el evento de acceso y la deteccion para tomar ese
# evento como contexto de la alerta.
SEGUNDOS_CONTEXTO = 120


def contexto_de(repo, registro_acceso_id: Optional[int], camara: dict,
                rostros_en_escena: Optional[int] = None) -> tuple[Optional[int], Optional[int]]:
    """Valida el evento de acceso que la estacion asocia a la deteccion.

    Returns:
        (registro_acceso_id aceptado, persona_contexto_id).

    El evento solo se acepta si ocurrio en el mismo punto de acceso de la
    camara y hace poco. La persona de ese evento solo se toma como contexto
    si el fotograma tenia un unico rostro; con varios, no hay forma de saber
    a quien se refiere la deteccion y se deja en blanco.
    """
    if not registro_acceso_id:
        return None, None
    registro = repo.obtener_registro(int(registro_acceso_id))
    if registro is None or registro["punto_acceso_id"] != camara["punto_acceso_id"]:
        return None, None
    fecha = registro.get("fecha_hora")
    if fecha and datetime.now() - fecha > timedelta(seconds=SEGUNDOS_CONTEXTO):
        return None, None
    persona = registro.get("persona_id")
    if rostros_en_escena is not None and int(rostros_en_escena) != 1:
        persona = None
    return registro["id"], persona


def registrar_deteccion(
    camara: dict,
    tipo_arma: str,
    confianza: float,
    registro_acceso_id: Optional[int] = None,
    rostros_en_escena: Optional[int] = None,
    imagen: Optional[bytes] = None,
    repositorio=None,
    evidencias=None,
) -> dict:
    """Convierte una deteccion de la estacion en una alerta, sin duplicarla."""
    repo = _repo(repositorio)

    existente = repo.alerta_abierta_reciente(camara["id"], tipo_arma, Config.VENTANA_ALERTA)
    if existente is not None:
        repo.sumar_deteccion(existente["id"], confianza)
        return {"id": existente["id"], "estado": existente["estado"], "duplicada": True}

    registro_id, persona_contexto = contexto_de(
        repo, registro_acceso_id, camara, rostros_en_escena
    )
    alerta_id = repo.crear_alerta(
        camara_id=camara["id"],
        punto_acceso_id=camara["punto_acceso_id"],
        tipo_arma=tipo_arma,
        confianza=confianza,
        registro_acceso_id=registro_id,
        persona_contexto_id=persona_contexto,
    )

    if imagen:
        if evidencias is None:
            from . import evidencias
        try:
            repo.asignar_evidencia(alerta_id, evidencias.guardar(alerta_id, imagen))
        except Exception as exc:        # la alerta vale mas que su foto
            log.error("No se pudo guardar la evidencia de la alerta %s: %s", alerta_id, exc)

    notificar(alerta_id, repo)
    return {
        "id": alerta_id,
        "estado": NOTIFICADA,
        "duplicada": False,
        "persona_contexto_id": persona_contexto,
    }


def escalar_pendientes(repositorio=None, minutos: Optional[int] = None) -> list[int]:
    """Sube al administrador las alertas que nadie atendio (RF-14).

    La invoca sola la tarea de fondo del servidor (servicios/tareas.py) cada
    cierto tiempo, y tambien cada vez que alguien abre el panel o consulta
    las alertas. Devuelve los identificadores escalados.
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
