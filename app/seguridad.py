"""Autenticacion y control de acceso por roles (RF-08, RNF-03, RNF-04).

Las contrasenas nunca se guardan en claro. Se almacena el hash que produce
werkzeug, que aplica PBKDF2 con sal aleatoria.
"""

from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import g, jsonify, redirect, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import repositorio


def hashear(contrasena: str) -> str:
    return generate_password_hash(contrasena)


def verificar(contrasena: str, hash_guardado: str) -> bool:
    return check_password_hash(hash_guardado, contrasena)


def autenticar(correo: str, contrasena: str) -> dict | None:
    """Valida las credenciales y devuelve el usuario si son correctas."""
    usuario = repositorio.obtener_usuario_por_correo(correo)
    if usuario is None:
        return None
    if not verificar(contrasena, usuario["contrasena_hash"]):
        return None
    return usuario


def usuario_actual() -> dict | None:
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
    define el script de la base de datos.
    """

    def decorador(vista: Callable) -> Callable:
        @wraps(vista)
        def envoltura(*args, **kwargs):
            usuario = usuario_actual()
            if usuario is None:
                return jsonify({"error": "no autenticado"}), 401
            if usuario["rol"] not in roles:
                return jsonify({"error": "permisos insuficientes"}), 403
            g.usuario = usuario
            return vista(*args, **kwargs)

        return envoltura

    return decorador
