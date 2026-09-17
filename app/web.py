"""Plataforma web de consulta (CU-05, RNF-05, RNF-09)."""

from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from . import repositorio
from .seguridad import autenticar, requiere_sesion

bp = Blueprint("web", __name__)


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

        session["usuario_id"] = usuario["id"]
        session["usuario_nombre"] = usuario["nombre"]
        session["usuario_rol"] = usuario["rol"]
        return redirect(url_for("web.panel"))

    return render_template("login.html")


@bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("web.login"))


@bp.get("/panel")
@requiere_sesion
def panel():
    """Panel de monitoreo con los ultimos eventos y las alertas abiertas."""
    return render_template(
        "panel.html",
        usuario=g.usuario,
        accesos=repositorio.listar_accesos(limite=20),
        alertas=repositorio.listar_alertas(estado="generada"),
    )


@bp.get("/registros")
@requiere_sesion
def registros():
    """Consulta del historial con los filtros del RF-09."""
    from datetime import datetime

    def fecha(nombre):
        valor = request.args.get(nombre)
        try:
            return datetime.fromisoformat(valor) if valor else None
        except ValueError:
            return None

    return render_template(
        "registros.html",
        usuario=g.usuario,
        puntos=repositorio.listar_puntos_acceso(),
        filtros=request.args,
        accesos=repositorio.listar_accesos(
            desde=fecha("desde"),
            hasta=fecha("hasta"),
            punto_acceso_id=int(request.args["punto"]) if request.args.get("punto") else None,
        ),
    )
