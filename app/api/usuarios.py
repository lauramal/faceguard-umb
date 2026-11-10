"""Gestion de usuarios del sistema y bitacora (CU-07, RNF-04)."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from .. import repositorio, seguridad
from ..seguridad import requiere_rol

bp = Blueprint("usuarios", __name__, url_prefix="/api/usuarios")


@bp.get("")
@requiere_rol("administrador")
def listar():
    return jsonify({"usuarios": repositorio.listar_usuarios()})


@bp.post("")
@requiere_rol("administrador")
def crear():
    cuerpo = request.get_json(silent=True) or {}
    faltan = [c for c in ("nombre", "correo", "contrasena", "rol_id")
              if not cuerpo.get(c)]
    if faltan:
        return jsonify({"error": f"faltan campos: {', '.join(faltan)}"}), 400

    usuario_id = repositorio.crear_usuario(
        nombre=cuerpo["nombre"],
        correo=cuerpo["correo"].strip(),
        contrasena_hash=seguridad.hashear(cuerpo["contrasena"]),
        rol_id=int(cuerpo["rol_id"]),
    )
    repositorio.registrar_auditoria(
        g.usuario["id"], "crear_usuario", "usuario", usuario_id
    )
    return jsonify({"id": usuario_id}), 201


@bp.patch("/<int:usuario_id>/estado")
@requiere_rol("administrador")
def cambiar_estado(usuario_id: int):
    """Desbloquea o desactiva una cuenta."""
    cuerpo = request.get_json(silent=True) or {}
    try:
        filas = repositorio.cambiar_estado_usuario(usuario_id, cuerpo.get("estado"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not filas:
        return jsonify({"error": "usuario no encontrado"}), 404

    repositorio.registrar_auditoria(
        g.usuario["id"], "cambiar_estado_usuario", "usuario", usuario_id,
        cuerpo.get("estado"),
    )
    return jsonify({"usuario_id": usuario_id, "estado": cuerpo.get("estado")})


@bp.get("/auditoria")
@requiere_rol("administrador")
def auditoria():
    limite = min(int(request.args.get("limite", 200)), 1000)
    return jsonify({"registros": repositorio.listar_auditoria(limite)})
