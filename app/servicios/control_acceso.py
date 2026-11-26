"""Orquestacion del proceso P2, registro de ingreso y salida.

Este servicio une el modulo de reconocimiento facial con la base de datos.
Recibe un fotograma, obtiene la codificacion, la compara contra el catalogo y
decide si el evento es un ingreso o una salida.

Cuatro reglas gobiernan el proceso:

1. La identidad se decide sobre la distancia, no sobre la confianza.
2. Los eventos no identificados TAMBIEN se registran, con su evidencia, para
   que el guardia los verifique (RF-11). El sistema no adivina, pero tampoco
   olvida.
3. Una misma persona no genera un registro por fotograma. La ventana
   antirrebote evita que quien se queda frente a la camara produzca una
   secuencia absurda de ingresos y salidas alternados. La comprobacion y la
   insercion ocurren en una sola transaccion, de modo que dos fotogramas
   simultaneos tampoco duplican el evento. Lo mismo vale para un rostro
   desconocido: se registra una vez, no una por segundo.
4. Ingreso o salida lo decide primero el sentido del punto de acceso. En un
   punto mixto se alterna con el ultimo evento, salvo que ese ultimo ingreso
   sea tan viejo que la salida se perdio: entonces el evento nuevo es otro
   ingreso.
"""

from __future__ import annotations

import logging
import threading
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
    distancia as distancia_entre,
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


def decidir_evento(
    ultimo: Optional[dict],
    sentido: str = "mixto",
    ahora: Optional[datetime] = None,
) -> str:
    """Decide si el evento es ingreso o salida.

    1. Un punto de solo entrada registra ingresos y uno de solo salida,
       salidas, sin importar el historial.
    2. En un punto mixto se alterna con el ultimo evento de la persona.
    3. Excepcion: si el ultimo evento fue un ingreso de hace mas de
       HORAS_JORNADA_MAXIMA, la salida se perdio (la persona salio por otro
       lado o la camara no la vio). El evento nuevo es un ingreso; tratarlo
       como salida invertiria todo el historial a partir de ahi.
    """
    if sentido == "entrada":
        return "ingreso"
    if sentido == "salida":
        return "salida"
    if not ultimo:
        return "ingreso"
    ahora = ahora or datetime.now()
    jornada = timedelta(hours=Config.HORAS_JORNADA_MAXIMA)
    if (ultimo.get("tipo_evento") == "ingreso" and ultimo.get("fecha_hora")
            and ahora - ultimo["fecha_hora"] > jornada):
        return "ingreso"
    return siguiente_evento(ultimo.get("tipo_evento"))


# --------------------------------------------------------------------------
# Rostros desconocidos recientes
#
# El servidor no guarda la codificacion de quien no esta enrolado (seria
# tratar un dato biometrico sin consentimiento). Para no registrar al mismo
# desconocido una vez por segundo, se recuerda su vector en memoria solo
# durante la ventana antirrebote y luego se descarta.
# --------------------------------------------------------------------------

_desconocidos: dict[int, list[tuple[np.ndarray, float, int]]] = {}
_candado_desconocidos = threading.Lock()


def _desconocido_reciente(punto_acceso_id: int, vector: np.ndarray) -> Optional[int]:
    limite = time.monotonic() - Config.VENTANA_ANTIREBOTE
    with _candado_desconocidos:
        vigentes = [(v, t, r) for v, t, r in _desconocidos.get(punto_acceso_id, [])
                    if t >= limite]
        _desconocidos[punto_acceso_id] = vigentes
        for v, _, registro_id in vigentes:
            if distancia_entre(v, vector) <= Config.UMBRAL_DISTANCIA:
                return registro_id
    return None


def _recordar_desconocido(punto_acceso_id: int, vector: np.ndarray, registro_id: int) -> None:
    with _candado_desconocidos:
        _desconocidos.setdefault(punto_acceso_id, []).append(
            (np.asarray(vector, dtype=np.float64), time.monotonic(), registro_id)
        )


def olvidar_desconocidos() -> None:
    """Vacia la memoria de desconocidos. Lo usan las pruebas."""
    with _candado_desconocidos:
        _desconocidos.clear()


def _sentido(repo, punto_acceso_id: int) -> str:
    obtener = getattr(repo, "obtener_punto_acceso", None)
    punto = obtener(punto_acceso_id) if obtener else None
    return (punto or {}).get("sentido") or "mixto"


def _registrar_identificado(repo, *, punto_acceso_id, tipo_evento, persona_id,
                            camara_id, metodo, distancia=None, confianza=None):
    """Inserta sin duplicar. Devuelve (registro_id, creado)."""
    return repo.registrar_acceso_unico(
        punto_acceso_id=punto_acceso_id,
        tipo_evento=tipo_evento,
        persona_id=persona_id,
        ventana_segundos=Config.VENTANA_ANTIREBOTE,
        camara_id=camara_id,
        metodo=metodo,
        distancia=distancia,
        confianza=confianza,
    )


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
        dist = None if resultado.distancia == float("inf") else resultado.distancia
        repetido = _desconocido_reciente(punto_acceso_id, codificacion)
        if repetido is not None:
            return ResultadoAcceso(
                identificado=False,
                resultado="no_identificado",
                distancia=dist,
                confianza=resultado.confianza,
                registro_id=repetido,
                motivo="evento_reciente_omitido",
                milisegundos=transcurrido(),
            )
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
        _recordar_desconocido(punto_acceso_id, codificacion, registro_id)
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

    tipo_evento = decidir_evento(ultimo, _sentido(repo, punto_acceso_id))
    registro_id, creado = _registrar_identificado(
        repo,
        punto_acceso_id=punto_acceso_id,
        tipo_evento=tipo_evento,
        persona_id=resultado.persona_id,
        camara_id=camara_id,
        metodo="facial",
        distancia=resultado.distancia,
        confianza=resultado.confianza,
    )
    if not creado:
        # Otro fotograma de la misma persona gano la carrera.
        return ResultadoAcceso(
            identificado=True,
            persona_id=resultado.persona_id,
            nombre=f"{persona['nombres']} {persona['apellidos']}",
            tipo_evento=tipo_evento,
            distancia=resultado.distancia,
            confianza=resultado.confianza,
            registro_id=registro_id,
            motivo="evento_reciente_omitido",
            milisegundos=transcurrido(),
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

    tipo_evento = decidir_evento(ultimo, _sentido(repo, punto_acceso_id))
    registro_id, creado = _registrar_identificado(
        repo,
        punto_acceso_id=punto_acceso_id,
        tipo_evento=tipo_evento,
        persona_id=persona_id,
        camara_id=None,
        metodo="credencial",
    )
    if not creado:
        return ResultadoAcceso(
            identificado=True,
            persona_id=persona_id,
            nombre=f"{persona['nombres']} {persona['apellidos']}",
            tipo_evento=tipo_evento,
            metodo="credencial",
            registro_id=registro_id,
            motivo="evento_reciente_omitido",
            milisegundos=(time.perf_counter() - inicio) * 1000,
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
