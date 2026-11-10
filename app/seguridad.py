"""Autenticacion y control de acceso por roles (RF-08, RNF-03, RNF-04).

Las contrasenas nunca se guardan en claro. Se almacena el hash que produce
werkzeug, que aplica PBKDF2 con sal aleatoria.

La cuenta se bloquea tras un numero configurable de intentos fallidos
consecutivos, y todo inicio de sesion, exitoso o no, queda en la bitacora de
auditoria.
"""

from __future__ import annotations

from functools import wraps
from typing import Callable, Optional

from flask import g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import repositorio
from .config import Config


def hashear(contrasena: str) -> str:
    return generate_password_hash(contrasena)


def verificar(contrasena: str, hash_guardado: str) -> bool:
    return check_password_hash(hash_guardado, contrasena)


def _ip() -> Optional[str]:
    try:
        return request.remote_addr
    except RuntimeError:          # fuera de un contexto de peticion
        return None


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
    session["usuario_id"] = usuario["id"]
    session["usuario_nombre"] = usuario["nombre"]
    session["usuario_rol"] = usuario["rol"]


def cerrar_sesion() -> None:
    session.clear()


def usuario_actual() -> Optional[dict]:
    if "usuario_id" not in session:
        return None
    return {
        "id": session["usuario_id"],
        "nombre": session.get("usuario_nombre"),
        "rol": session.get("usuario_rol"),
    }


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
    define el script de la base de datos. Un usuario sin el rol adecuado
    recibe 403 y el intento queda en la bitacora.
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
