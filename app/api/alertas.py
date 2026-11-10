"""Endpoints de alertas de arma visible (CU-03, CU-04, CU-09)."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from .. import repositorio
from ..seguridad import requiere_rol
from ..servicios import alertas as servicio

bp = Blueprint("alertas", __name__, url_prefix="/api/alertas")


@bp.post("")
def crear():
    """La estacion de captura reporta una deteccion de arma visible.

    Recibe tambien el registro de acceso y la persona identificada en ese
    momento, que es lo que permite saber despues quien llevaba el arma.
    """
    cuerpo = request.get_json(silent=True) or {}
    faltan = [c for c in ("camara_id", "punto_acceso_id", "tipo_arma", "confianza")
              if cuerpo.get(c) is None]
    if faltan:
        return jsonify({"error": f"faltan campos: {', '.join(faltan)}"}), 400

    try:
        alerta_id = repositorio.crear_alerta(
            camara_id=int(cuerpo["camara_id"]),
            punto_acceso_id=int(cuerpo["punto_acceso_id"]),
            tipo_arma=cuerpo["tipo_arma"],
            confianza=float(cuerpo["confianza"]),
            registro_acceso_id=cuerpo.get("registro_acceso_id"),
            persona_id=cuerpo.get("persona_id"),
            imagen_url=cuerpo.get("imagen_url"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    servicio.notificar(alerta_id)
    return jsonify({"id": alerta_id, "estado": servicio.NOTIFICADA}), 201


@bp.get("")
@requiere_rol("administrador", "guardia", "consulta")
def listar():
    return jsonify({
        "alertas": repositorio.listar_alertas(
            estado=request.args.get("estado"),
            limite=min(int(request.args.get("limite", 100)), 500),
        )
    })


@bp.post("/<int:alerta_id>/atender")
@requiere_rol("administrador", "guardia")
def atender(alerta_id: int):
    try:
        resultado = servicio.atender(alerta_id, g.usuario["id"])
    except servicio.TransicionInvalida as exc:
        return jsonify({"error": str(exc)}), 409

    repositorio.registrar_auditoria(
        g.usuario["id"], "atender_alerta", "alerta_arma", alerta_id
    )
    return jsonify(resultado)


@bp.post("/<int:alerta_id>/resolver")
@requiere_rol("administrador", "guardia")
def resolver(alerta_id: int):
    cuerpo = request.get_json(silent=True) or {}
    if "confirmada" not in cuerpo:
        return jsonify({"error": "falta el campo confirmada"}), 400

    try:
        resultado = servicio.resolver(
            alerta_id, g.usuario["id"], bool(cuerpo["confirmada"])
        )
    except servicio.TransicionInvalida as exc:
        return jsonify({"error": str(exc)}), 409

    repositorio.registrar_auditoria(
        g.usuario["id"], "resolver_alerta", "alerta_arma", alerta_id,
        "confirmada" if cuerpo["confirmada"] else "falso_positivo",
    )
    return jsonify(resultado)


@bp.post("/escalar")
@requiere_rol("administrador")
def escalar():
    """Sube al administrador las alertas que nadie atendio (RF-14)."""
    escaladas = servicio.escalar_pendientes()
    return jsonify({"escaladas": escaladas, "total": len(escaladas)})
