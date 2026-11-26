"""Tareas de fondo del servidor de aplicacion.

Escalamiento automatico (RF-14). Un hilo revisa cada
SEGUNDOS_REVISION_ESCALAMIENTO si hay alertas que llevan mas de
MINUTOS_ESCALAMIENTO sin que un guardia las tome, y las sube al administrador.
Nadie tiene que invocar un endpoint para que ocurra.

Como el plan gratuito de despliegue suspende el servidor cuando no recibe
trafico, el hilo se complementa con una revision en cada consulta del panel y
de la lista de alertas: lo primero que hace el servidor al despertar es
escalar lo que haya quedado pendiente. La operacion es idempotente, porque una
alerta ya escalada no vuelve a escalar, de modo que varias revisiones a la vez
no producen efectos duplicados.
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)

_hilo: threading.Thread | None = None
_detener = threading.Event()


def revisar_escalamiento(app) -> list[int]:
    """Una pasada de revision. Devuelve las alertas escaladas."""
    from . import alertas

    with app.app_context():
        try:
            return alertas.escalar_pendientes()
        except Exception as exc:          # la tarea no debe morir por un fallo
            log.error("Fallo la revision de escalamiento: %s", exc)
            return []


def iniciar_escalamiento_automatico(app, segundos: int) -> threading.Thread:
    """Arranca el hilo de revision, una sola vez por proceso."""
    global _hilo
    if _hilo is not None and _hilo.is_alive():
        return _hilo

    _detener.clear()

    def ciclo():
        while not _detener.wait(segundos):
            revisar_escalamiento(app)

    _hilo = threading.Thread(target=ciclo, name="escalamiento", daemon=True)
    _hilo.start()
    log.info("Escalamiento automatico activo cada %s s", segundos)
    return _hilo


def detener_escalamiento_automatico() -> None:
    global _hilo
    _detener.set()
    if _hilo is not None:
        _hilo.join(timeout=5)
    _hilo = None
