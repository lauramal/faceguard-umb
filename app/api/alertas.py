"""Endpoints de alertas de arma visible (CU-03, CU-04, CU-09)."""

from __future__ import annotations

import base64
import binascii

from flask import Blueprint, Response, g, jsonify, request

from .. import repositorio
from ..seguridad import requiere_estacion, requiere_rol
from ..servicios import alertas as servicio
from ..servicios import evidencias

bp = Blueprint("alertas", __name__, url_prefix="/api/alertas")


def _imagen(cuerpo: dict):
    datos = cuerpo.get("imagen")
    if not datos:
        return None
    if "," in datos:                     # data:image/jpeg;base64,....
        datos = datos.split(",", 1)[1]
    return base64.b64decode(datos, validate=True)


@bp.post("")
@requiere_estacion
def crear():
    """La estacion de captura reporta una deteccion de arma visible.

    La camara y el punto de acceso se toman de la credencial de la estacion.
    La estacion puede indicar el evento de acceso del mismo momento: la
    persona de ese evento queda como contexto, no como portadora. Si ya hay
    una alerta abierta del mismo tipo en esa camara, la deteccion se suma a
    ella y no se crea otra.
    """
    cuerpo = request.get_json(silent=True) or {}
    faltan = [c for c in ("tipo_arma", "confianza") if cuerpo.get(c) is None]
    if faltan:
        return jsonify({"error": f"faltan campos: {', '.join(faltan)}"}), 400

    try:
        confianza = float(cuerpo["confianza"])
        if not 0 <= confianza <= 1:
            raise ValueError("la confianza debe estar entre 0 y 1")
        imagen = _imagen(cuerpo)
        resultado = servicio.registrar_deteccion(
            camara=g.camara,
            tipo_arma=cuerpo["tipo_arma"],
            confianza=confianza,
            registro_acceso_id=cuerpo.get("registro_acceso_id"),
            rostros_en_escena=cuerpo.get("rostros_en_escena"),
            imagen=imagen,
        )
    except (ValueError, binascii.Error) as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(resultado), (200 if resultado["duplicada"] else 201)


@bp.get("")
@requiere_rol("administrador", "guardia", "consulta")
def listar():
    # Antes de responder se escala lo pendiente: si el servidor estuvo
    # suspendido, la primera consulta pone al dia el escalamiento.
    servicio.escalar_pendientes()
    return jsonify({
        "alertas": repositorio.listar_alertas(
            estado=request.args.get("estado"),
            limite=min(int(request.args.get("limite", 100)), 500),
            abiertas=request.args.get("abiertas") in ("1", "true", "si"),
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
    """Confirma el arma o la descarta como falso positivo.

    Al confirmar, el guardia puede indicar en portador_id a quien corresponde
    el arma, una vez verificada la evidencia.
    """
    cuerpo = request.get_json(silent=True) or {}
    if "confirmada" not in cuerpo:
        return jsonify({"error": "falta el campo confirmada"}), 400
    portador = cuerpo.get("portador_id")

    try:
        resultado = servicio.resolver(
            alerta_id, g.usuario["id"], bool(cuerpo["confirmada"]),
            portador_id=int(portador) if portador else None,
        )
    except servicio.TransicionInvalida as exc:
        return jsonify({"error": str(exc)}), 409

    detalle = "confirmada" if cuerpo["confirmada"] else "falso_positivo"
    if portador:
        detalle += f", portador verificado {portador}"
    repositorio.registrar_auditoria(
        g.usuario["id"], "resolver_alerta", "alerta_arma", alerta_id, detalle,
    )
    return jsonify(resultado)


@bp.get("/<int:alerta_id>/evidencia")
@requiere_rol("administrador", "guardia")
def evidencia(alerta_id: int):
    """Fotograma de la deteccion, para verificar si es un arma visible."""
    alerta = repositorio.obtener_alerta(alerta_id)
    if alerta is None or not alerta.get("imagen_url"):
        return jsonify({"error": "la alerta no tiene evidencia"}), 404
    try:
        datos, tipo = evidencias.leer(alerta["imagen_url"])
    except (FileNotFoundError, OSError):
        return jsonify({"error": "la evidencia ya no esta disponible"}), 404

    repositorio.registrar_auditoria(
        g.usuario["id"], "ver_evidencia", "alerta_arma", alerta_id
    )
    return Response(datos, mimetype=tipo, headers={"Cache-Control": "no-store"})


@bp.post("/escalar")
@requiere_rol("administrador")
def escalar():
    """Revision manual del escalamiento.

    El servidor ya escala solo (servicios/tareas.py). Este endpoint queda
    para forzar una revision inmediata.
    """
    escaladas = servicio.escalar_pendientes()
    return jsonify({"escaladas": escaladas, "total": len(escaladas)})
