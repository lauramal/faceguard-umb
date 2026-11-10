"""Inicio y cierre de sesion (RF-08, CU-05)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from .. import seguridad

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/login")
def login():
    cuerpo = request.get_json(silent=True) or {}
    correo = (cuerpo.get("correo") or "").strip()
    contrasena = cuerpo.get("contrasena") or ""

    if not correo or not contrasena:
        return jsonify({"error": "correo y contrasena son obligatorios"}), 400

    usuario = seguridad.autenticar(correo, contrasena)
    if usuario is None:
        # Mismo mensaje para credenciales malas y cuenta bloqueada, para no
        # revelar cuales correos existen.
        return jsonify({"error": "credenciales invalidas"}), 401

    seguridad.iniciar_sesion(usuario)
    return jsonify({
        "id": usuario["id"],
        "nombre": usuario["nombre"],
        "rol": usuario["rol"],
    })


@bp.post("/logout")
def logout():
    seguridad.cerrar_sesion()
    return jsonify({"estado": "sesion cerrada"})


@bp.get("/yo")
def yo():
    usuario = seguridad.usuario_actual()
    if usuario is None:
        return jsonify({"error": "no autenticado"}), 401
    return jsonify(usuario)
