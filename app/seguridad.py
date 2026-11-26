"""Autenticacion y control de acceso (RF-08, RNF-03, RNF-04).

Cubre tres frentes:

1. Usuarios del panel. Las contrasenas se guardan con PBKDF2 y sal aleatoria.
   La cuenta se bloquea tras varios intentos fallidos y todo inicio de sesion,
   exitoso o no, queda en la bitacora.

2. Permisos verificados en cada peticion. La sesion solo guarda el
   identificador del usuario: el rol y el estado se vuelven a leer de la base
   en cada solicitud. Asi, si el administrador bloquea una cuenta o le cambia
   el rol, el cambio rige de inmediato y no cuando la persona cierre sesion.

3. Estaciones de captura. Cada camara tiene una credencial propia. Sin ella el
   servidor no acepta eventos de acceso ni alertas, de modo que nadie puede
   fabricar un ingreso o una alerta enviando peticiones a mano.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from functools import wraps
from typing import Callable, Optional

from flask import g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import repositorio
from .config import Config

ESTADOS_QUE_ENTRAN = ("registrado", "activo")


def hashear(contrasena: str) -> str:
    return generate_password_hash(contrasena)


def verificar(contrasena: str, hash_guardado: str) -> bool:
    return check_password_hash(hash_guardado, contrasena)


def _ip() -> Optional[str]:
    try:
        return request.remote_addr
    except RuntimeError:          # fuera de un contexto de peticion
        return None


# ===========================================================================
# Usuarios del panel
# ===========================================================================

def autenticar(correo: str, contrasena: str, repo=repositorio) -> Optional[dict]:
    """Valida las credenciales y devuelve el usuario si son correctas.

    Una cuenta bloqueada o inactiva no autentica aunque la contrasena sea
    correcta. Cada intento fallido se contabiliza y, al llegar al maximo, la
    cuenta pasa a 'bloqueado' y solo el administrador puede reactivarla.
    """
    usuario = repo.obtener_usuario_por_correo(correo)
    if usuario is None:
        repo.registrar_auditoria(
            None, "login_fallido", "usuario", None,
            f"correo inexistente: {correo}", _ip(),
        )
        return None

    if usuario["estado"] in ("bloqueado", "inactivo"):
        repo.registrar_auditoria(
            usuario["id"], "login_rechazado", "usuario", usuario["id"],
            f"cuenta en estado {usuario['estado']}", _ip(),
        )
        return None

    if not verificar(contrasena, usuario["contrasena_hash"]):
        repo.registrar_intento_fallido(usuario["id"], Config.MAX_INTENTOS_FALLIDOS)
        repo.registrar_auditoria(
            usuario["id"], "login_fallido", "usuario", usuario["id"],
            "contrasena incorrecta", _ip(),
        )
        return None

    repo.reiniciar_intentos(usuario["id"])
    repo.registrar_auditoria(
        usuario["id"], "login_exitoso", "usuario", usuario["id"], None, _ip()
    )
    return usuario


def iniciar_sesion(usuario: dict) -> None:
    # Se descarta cualquier sesion anterior para evitar la fijacion de sesion.
    session.clear()
    session.permanent = True
    session["usuario_id"] = usuario["id"]
    session["csrf"] = secrets.token_urlsafe(32)


def cerrar_sesion() -> None:
    session.clear()


def duracion_sesion() -> timedelta:
    return timedelta(hours=Config.HORAS_SESION)


def usuario_actual(repo=None) -> Optional[dict]:
    """Usuario de la sesion, con su rol y su estado leidos de la base.

    Si la cuenta ya no existe o fue bloqueada o desactivada, la sesion se
    invalida aunque la cookie siga vigente.
    """
    if "usuario_id" not in session:
        return None
    repo = repo or repositorio
    usuario = repo.obtener_usuario(session["usuario_id"])
    if usuario is None or usuario.get("estado") not in ESTADOS_QUE_ENTRAN:
        session.clear()
        return None
    return {
        "id": usuario["id"],
        "nombre": usuario.get("nombre"),
        "rol": usuario.get("rol"),
        "permisos": list(usuario.get("permisos") or []),
    }


def tiene_permiso(usuario: dict, permiso: str) -> bool:
    """El administrador tiene todos; los demas, los de su rol."""
    if usuario.get("rol") == "administrador":
        return True
    return permiso in (usuario.get("permisos") or [])


def token_csrf() -> str:
    """Token del formulario, ligado a la sesion. Lo usan las plantillas."""
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def csrf_valido(enviado: Optional[str]) -> bool:
    esperado = session.get("csrf")
    return bool(esperado and enviado and hmac.compare_digest(esperado, enviado))


def requiere_sesion(vista: Callable) -> Callable:
    @wraps(vista)
    def envoltura(*args, **kwargs):
        usuario = usuario_actual()
        if usuario is None:
            return redirect(url_for("web.login"))
        g.usuario = usuario
        return vista(*args, **kwargs)

    return envoltura


def requiere_rol(*roles: str) -> Callable:
    """Restringe una vista a los roles indicados.

    Los roles disponibles son administrador, guardia y consulta, tal como los
    define el script de la base de datos. El rol se lee de la base en cada
    peticion. Un usuario sin el rol adecuado recibe 403 y el intento queda en
    la bitacora.
    """

    def decorador(vista: Callable) -> Callable:
        @wraps(vista)
        def envoltura(*args, **kwargs):
            usuario = usuario_actual()
            if usuario is None:
                return jsonify({"error": "no autenticado"}), 401
            if usuario["rol"] not in roles:
                repositorio.registrar_auditoria(
                    usuario["id"], "acceso_denegado", "endpoint", None,
                    f"{request.method} {request.path} requiere {roles}", _ip(),
                )
                return jsonify({"error": "permisos insuficientes"}), 403
            g.usuario = usuario
            return vista(*args, **kwargs)

        return envoltura

    return decorador


# ===========================================================================
# Estaciones de captura
# ===========================================================================

def _resumen(secreto: str) -> str:
    return hashlib.sha256(secreto.encode("utf-8")).hexdigest()


def generar_credencial_estacion(camara_id: int) -> tuple[str, str]:
    """Crea la credencial de una camara.

    Returns:
        (token que se entrega una sola vez al administrador,
         resumen SHA-256 que se guarda en la base).

    El token tiene la forma "<camara_id>.<secreto>". El secreto es aleatorio
    y largo, de modo que basta un resumen rapido para guardarlo.
    """
    secreto = secrets.token_urlsafe(32)
    return f"{camara_id}.{secreto}", _resumen(secreto)


def autenticar_estacion(cabecera: Optional[str], repo=None) -> Optional[dict]:
    """Devuelve la camara si la cabecera Authorization trae una credencial valida."""
    if not cabecera or not cabecera.startswith("Bearer "):
        return None
    token = cabecera[len("Bearer "):].strip()
    camara_id, _, secreto = token.partition(".")
    if not camara_id.isdigit() or not secreto:
        return None

    repo = repo or repositorio
    camara = repo.obtener_camara(int(camara_id))
    if camara is None or not camara.get("token_hash"):
        return None
    if camara.get("estado", "activa") != "activa":
        return None
    if not hmac.compare_digest(camara["token_hash"].strip(), _resumen(secreto)):
        return None
    return camara


def requiere_estacion(vista: Callable) -> Callable:
    """Solo una estacion de captura con credencial valida entra aqui.

    La camara que queda en g.camara es la que firma la peticion, y de ella se
    toman la camara y el punto de acceso: el servidor no confia en los que
    vengan escritos en el cuerpo.
    """

    @wraps(vista)
    def envoltura(*args, **kwargs):
        camara = autenticar_estacion(request.headers.get("Authorization"))
        if camara is None:
            repositorio.registrar_auditoria(
                None, "estacion_rechazada", "endpoint", None,
                f"{request.method} {request.path}", _ip(),
            )
            return jsonify({"error": "estacion no autenticada"}), 401
        g.camara = camara
        return vista(*args, **kwargs)

    return envoltura
