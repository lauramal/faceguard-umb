"""Generacion de reportes (RF-10, CU-06).

El reporte se construye en el momento de la consulta y no se persiste, que es
la razon por la cual la clase Reporte no tiene tabla en el modelo relacional.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta

from flask import Blueprint, Response, g, jsonify, request

from .. import repositorio
from ..seguridad import requiere_rol

bp = Blueprint("reportes", __name__, url_prefix="/api/reportes")


def _rango():
    hasta = request.args.get("hasta")
    desde = request.args.get("desde")
    hasta = datetime.fromisoformat(hasta) if hasta else datetime.now()
    desde = datetime.fromisoformat(desde) if desde else hasta - timedelta(days=30)
    return desde, hasta


@bp.get("/resumen")
@requiere_rol("administrador", "consulta")
def resumen():
    desde, hasta = _rango()
    datos = repositorio.resumen_accesos(desde, hasta)
    repositorio.registrar_auditoria(
        g.usuario["id"], "generar_reporte", "reporte", None,
        f"resumen {desde.isoformat()} a {hasta.isoformat()}",
    )
    return jsonify({"desde": desde.isoformat(), "hasta": hasta.isoformat(), **datos})


@bp.get("/accesos.csv")
@requiere_rol("administrador", "consulta")
def accesos_csv():
    desde, hasta = _rango()
    registros = repositorio.listar_accesos(desde=desde, hasta=hasta, limite=1000)

    salida = io.StringIO()
    columnas = ["id", "fecha_hora", "tipo_evento", "metodo", "resultado",
                "documento", "nombres", "apellidos", "tipo_persona",
                "punto_acceso", "distancia", "confianza"]
    escritor = csv.DictWriter(salida, fieldnames=columnas, extrasaction="ignore")
    escritor.writeheader()
    for fila in registros:
        escritor.writerow(fila)

    repositorio.registrar_auditoria(
        g.usuario["id"], "exportar_reporte", "reporte", None,
        f"csv {len(registros)} filas",
    )
    return Response(
        salida.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=accesos.csv"},
    )
