"""Pruebas de los endpoints del backend."""

import pytest

from app import crear_app
from app.config import Config


class ConfigPrueba(Config):
    SECRET_KEY = "clave-de-prueba"
    DEBUG = True


@pytest.fixture
def cliente():
    app = crear_app(ConfigPrueba)
    app.config["TESTING"] = True
    return app.test_client()


def test_endpoint_de_salud(cliente):
    respuesta = cliente.get("/salud")
    assert respuesta.status_code == 200
    assert respuesta.get_json()["estado"] == "ok"


def test_ruta_inexistente_devuelve_json(cliente):
    respuesta = cliente.get("/no-existe")
    assert respuesta.status_code == 404
    assert "error" in respuesta.get_json()


def test_identificar_exige_la_imagen(cliente):
    respuesta = cliente.post("/api/accesos/identificar", json={"punto_acceso_id": 1})
    assert respuesta.status_code == 400
    assert "imagen" in respuesta.get_json()["error"]


def test_identificar_exige_el_punto_de_acceso(cliente):
    respuesta = cliente.post("/api/accesos/identificar", json={"imagen": "abc"})
    assert respuesta.status_code == 400
    assert "punto_acceso_id" in respuesta.get_json()["error"]


def test_identificar_rechaza_una_imagen_corrupta(cliente):
    respuesta = cliente.post(
        "/api/accesos/identificar",
        json={"imagen": "no-es-base64-valido", "punto_acceso_id": 1},
    )
    assert respuesta.status_code == 400


def test_el_historial_exige_sesion(cliente):
    """Sin sesion iniciada no se puede consultar el historial (RF-08)."""
    respuesta = cliente.get("/api/accesos")
    assert respuesta.status_code == 401


def test_crear_estudiante_exige_sesion(cliente):
    respuesta = cliente.post("/api/estudiantes", json={"codigo": "1"})
    assert respuesta.status_code == 401


def test_login_muestra_el_formulario(cliente):
    respuesta = cliente.get("/login")
    assert respuesta.status_code == 200
    assert b"FaceGuard" in respuesta.data


def test_el_panel_redirige_al_login(cliente):
    respuesta = cliente.get("/panel")
    assert respuesta.status_code == 302
    assert "/login" in respuesta.headers["Location"]
