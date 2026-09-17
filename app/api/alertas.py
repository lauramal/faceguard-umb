"""Endpoints de alertas de armas (CU-04, CU-09). Se completa en el sprint 3."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from .. import repositorio
from ..seguridad import requiere_rol

bp = Blueprint("alertas", __name__, url_prefix="/api/alertas")


@bp.get("")
@requiere_rol("administrador", "guardia", "consulta")
def listar():
    return jsonify(repositorio.listar_alertas(request.args.get("estado")))


@bp.post("/<int:alerta_id>/cerrar")
@requiere_rol("administrador", "guardia")
def cerrar(alerta_id: int):
    """Cierra una alerta dejando trazabilidad de quien la atendio (RF-07)."""
    estado = (request.get_json(silent=True) or {}).get("estado")
    if estado not in ("confirmada", "falso_positivo"):
        return jsonify({"error": "estado debe ser confirmada o falso_positivo"}), 400

    repositorio.cerrar_alerta(alerta_id, g.usuario["id"], estado)
    return jsonify({"alerta_id": alerta_id, "estado": estado})
