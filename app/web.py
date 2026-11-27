"""Plataforma web: panel del guardia y consulta de registros (CU-05, CU-09).

El panel es donde el guardia trabaja. Muestra las alertas abiertas, con las
escaladas arriba, y le permite atenderlas, ver el fotograma de la deteccion y
confirmar el arma o descartarla como falso positivo. La lista se actualiza
sola cada pocos segundos, sin recargar la pagina.

Los formularios llevan un token ligado a la sesion, de modo que una pagina de
otro sitio no puede atender o cerrar alertas en nombre del guardia.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from . import repositorio
from .seguridad import (
    autenticar,
    cerrar_sesion,
    csrf_valido,
    iniciar_sesion,
    requiere_sesion,
)
from .servicios import alertas as servicio_alertas
from .servicios import evidencias

bp = Blueprint("web", __name__)

ROLES_QUE_ATIENDEN = ("administrador", "guardia")
SEGUNDOS_REFRESCO = 10

_MESES = ("ene", "feb", "mar", "abr", "may", "jun",
          "jul", "ago", "sep", "oct", "nov", "dic")


@bp.app_template_filter("hora")
def filtro_hora(valor):
    """Hora legible para el panel: '23:39:49'."""
    if isinstance(valor, datetime):
        return valor.strftime("%H:%M:%S")
    return valor or ""


@bp.app_template_filter("fecha_corta")
def filtro_fecha_corta(valor):
    """Fecha legible: 'hoy, 23:39' o '26 nov, 23:39'."""
    if not isinstance(valor, datetime):
        return valor or ""
    hoy = datetime.now().date()
    if valor.date() == hoy:
        dia = "hoy"
    elif valor.date() == hoy - timedelta(days=1):
        dia = "ayer"
    else:
        dia = f"{valor.day} {_MESES[valor.month - 1]}"
    return f"{dia}, {valor.strftime('%H:%M')}"


@bp.app_template_filter("iniciales")
def filtro_iniciales(nombres, apellidos=None):
    if apellidos is None:
        partes = (nombres or "?").split()
        return "".join(p[:1] for p in partes[:2]).upper()
    return f"{(nombres or '?')[:1]}{apellidos[:1]}".upper()


@bp.get("/")
def inicio():
    return redirect(url_for("web.panel"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = autenticar(
            request.form.get("correo", ""),
            request.form.get("contrasena", ""),
        )
        if usuario is None:
            flash("Correo o contrasena incorrectos", "error")
            return render_template("login.html"), 401

        iniciar_sesion(usuario)
        return redirect(url_for("web.panel"))

    return render_template("login.html")


@bp.get("/logout")
def logout():
    cerrar_sesion()
    return redirect(url_for("web.login"))


def _contexto_alertas():
    # Se escala lo pendiente antes de mostrar, por si el servidor estuvo
    # suspendido y la tarea de fondo no corrio.
    servicio_alertas.escalar_pendientes()
    return {
        "alertas": repositorio.listar_alertas(abiertas=True),
        "puede_atender": g.usuario["rol"] in ROLES_QUE_ATIENDEN,
    }


def _indicadores(alertas):
    """Cifras del dia para las tarjetas superiores del panel."""
    inicio_dia = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    hoy = repositorio.listar_accesos(desde=inicio_dia, limite=5000)
    return {
        "accesos_hoy": sum(1 for r in hoy if r.get("resultado") == "identificado"),
        "no_identificados": sum(1 for r in hoy if r.get("resultado") != "identificado"),
        "alertas_abiertas": len(alertas),
        "escaladas": sum(1 for a in alertas if a.get("estado") == "escalada"),
    }


@bp.get("/panel")
@requiere_sesion
def panel():
    """Panel de monitoreo: alertas abiertas y ultimos accesos."""
    contexto = _contexto_alertas()
    return render_template(
        "panel.html",
        usuario=g.usuario,
        accesos=repositorio.listar_accesos(limite=12),
        segundos_refresco=SEGUNDOS_REFRESCO,
        indicadores=_indicadores(contexto["alertas"]),
        **contexto,
    )


@bp.get("/panel/accesos")
@requiere_sesion
def panel_accesos():
    """Fragmento con los ultimos accesos y las cifras del dia."""
    contexto = _contexto_alertas()
    return render_template(
        "_accesos.html",
        usuario=g.usuario,
        accesos=repositorio.listar_accesos(limite=12),
        indicadores=_indicadores(contexto["alertas"]),
    )


@bp.get("/panel/alertas")
@requiere_sesion
def panel_alertas():
    """Fragmento con las alertas abiertas. El panel lo pide periodicamente."""
    return render_template("_alertas.html", usuario=g.usuario, **_contexto_alertas())


def _exigir_guardia_y_token():
    if g.usuario["rol"] not in ROLES_QUE_ATIENDEN:
        repositorio.registrar_auditoria(
            g.usuario["id"], "acceso_denegado", "endpoint", None,
            f"{request.method} {request.path}",
        )
        abort(403)
    if not csrf_valido(request.form.get("csrf")):
        abort(400, "formulario vencido o invalido")


@bp.post("/panel/alertas/<int:alerta_id>/atender")
@requiere_sesion
def atender_alerta(alerta_id: int):
    _exigir_guardia_y_token()
    try:
        servicio_alertas.atender(alerta_id, g.usuario["id"])
    except servicio_alertas.TransicionInvalida as exc:
        flash(str(exc), "error")
    else:
        repositorio.registrar_auditoria(
            g.usuario["id"], "atender_alerta", "alerta_arma", alerta_id
        )
        flash(f"Alerta {alerta_id} en atencion", "ok")
    return redirect(url_for("web.panel"))


@bp.post("/panel/alertas/<int:alerta_id>/resolver")
@requiere_sesion
def resolver_alerta(alerta_id: int):
    _exigir_guardia_y_token()
    confirmada = request.form.get("desenlace") == "confirmada"
    portador = request.form.get("portador_id") or None
    try:
        servicio_alertas.resolver(
            alerta_id, g.usuario["id"], confirmada,
            portador_id=int(portador) if (portador and confirmada) else None,
        )
    except (servicio_alertas.TransicionInvalida, ValueError) as exc:
        flash(str(exc), "error")
    else:
        repositorio.registrar_auditoria(
            g.usuario["id"], "resolver_alerta", "alerta_arma", alerta_id,
            "confirmada" if confirmada else "falso_positivo",
        )
        flash(f"Alerta {alerta_id} cerrada como "
              f"{'arma confirmada' if confirmada else 'falso positivo'}", "ok")
    return redirect(url_for("web.panel"))


@bp.get("/panel/alertas/<int:alerta_id>/evidencia")
@requiere_sesion
def evidencia_alerta(alerta_id: int):
    """Fotograma de la deteccion, visible solo para guardia y administrador."""
    if g.usuario["rol"] not in ROLES_QUE_ATIENDEN:
        abort(403)
    alerta = repositorio.obtener_alerta(alerta_id)
    if alerta is None or not alerta.get("imagen_url"):
        abort(404)
    try:
        datos, tipo = evidencias.leer(alerta["imagen_url"])
    except (FileNotFoundError, OSError):
        abort(404)
    repositorio.registrar_auditoria(
        g.usuario["id"], "ver_evidencia", "alerta_arma", alerta_id
    )
    return Response(datos, mimetype=tipo, headers={"Cache-Control": "no-store"})


@bp.get("/registros")
@requiere_sesion
def registros():
    """Consulta del historial con los filtros del RF-09."""

    def fecha(nombre):
        valor = request.args.get(nombre)
        try:
            return datetime.fromisoformat(valor) if valor else None
        except ValueError:
            return None

    return render_template(
        "registros.html",
        usuario=g.usuario,
        seccion="registros",
        puntos=repositorio.listar_puntos_acceso(),
        filtros=request.args,
        accesos=repositorio.listar_accesos(
            desde=fecha("desde"),
            hasta=fecha("hasta"),
            punto_acceso_id=int(request.args["punto"]) if request.args.get("punto") else None,
        ),
    )
