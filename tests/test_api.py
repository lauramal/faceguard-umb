"""Caja blanca de la API: control de acceso por roles.

Cubre la prueba de la asesoria sobre que cada rol haga solo lo que le toca.
Se monta la aplicacion real y se sustituye el repositorio por el doble en
memoria, de modo que las pruebas corren sin base de datos.
"""

from __future__ import annotations

import pytest

from app import crear_app, repositorio as repo_real, seguridad
from app.config import Config

# Funciones del repositorio que la API invoca y que hay que sustituir.
FUNCIONES = [
    "crear_persona", "obtener_persona", "listar_personas",
    "actualizar_estado_persona", "guardar_codificacion",
    "eliminar_codificaciones", "cargar_catalogo", "ultimo_registro",
    "registrar_acceso", "verificar_acceso_manual", "listar_accesos",
    "crear_alerta", "obtener_alerta", "actualizar_estado_alerta",
    "listar_alertas", "alertas_sin_atender", "obtener_usuario_por_correo",
    "obtener_usuario", "crear_usuario", "listar_usuarios",
    "registrar_intento_fallido", "reiniciar_intentos",
    "cambiar_estado_usuario", "listar_puntos_acceso", "crear_punto_acceso",
    "listar_camaras", "crear_camara", "registrar_auditoria",
    "listar_auditoria", "resumen_accesos",
]


class ConfigPrueba(Config):
    SECRET_KEY = "clave-de-prueba"
    TESTING = True


@pytest.fixture
def app(repo, monkeypatch):
    for nombre in FUNCIONES:
        monkeypatch.setattr(repo_real, nombre, getattr(repo, nombre))
    aplicacion = crear_app(ConfigPrueba)
    aplicacion.config["TESTING"] = True
    return aplicacion


@pytest.fixture
def client(app):
    return app.test_client()


def entrar_como(client, rol: str, usuario_id: int = 1):
    """Simula una sesion abierta con el rol indicado."""
    with client.session_transaction() as sesion:
        sesion["usuario_id"] = usuario_id
        sesion["usuario_nombre"] = f"Usuario {rol}"
        sesion["usuario_rol"] = rol


class TestSalud:
    def test_el_servicio_responde(self, client):
        respuesta = client.get("/salud")
        assert respuesta.status_code == 200
        assert respuesta.get_json()["estado"] == "ok"

    def test_ruta_inexistente_da_404_en_json(self, client):
        respuesta = client.get("/api/no-existe")
        assert respuesta.status_code == 404
        assert "error" in respuesta.get_json()


class TestSinSesion:
    """Sin autenticar no se accede a nada protegido."""

    @pytest.mark.parametrize("metodo,ruta", [
        ("get", "/api/personas"),
        ("post", "/api/personas"),
        ("get", "/api/accesos"),
        ("get", "/api/alertas"),
        ("get", "/api/usuarios"),
        ("get", "/api/reportes/resumen"),
        ("get", "/api/camaras"),
    ])
    def test_responde_401(self, client, metodo, ruta):
        assert getattr(client, metodo)(ruta).status_code == 401


class TestRoles:
    """Cada rol hace lo suyo y nada mas."""

    def test_el_guardia_no_crea_personas(self, client):
        entrar_como(client, "guardia")
        respuesta = client.post("/api/personas", json={
            "institucion_id": 1, "documento": "1", "tipo_persona": "estudiante",
            "nombres": "A", "apellidos": "B",
        })
        assert respuesta.status_code == 403

    def test_el_administrador_si_crea_personas(self, client):
        entrar_como(client, "administrador")
        respuesta = client.post("/api/personas", json={
            "institucion_id": 1, "documento": "1", "tipo_persona": "estudiante",
            "nombres": "A", "apellidos": "B",
        })
        assert respuesta.status_code == 201

    def test_el_rol_consulta_no_atiende_alertas(self, client, repo):
        aid = repo.crear_alerta(camara_id=1, punto_acceso_id=1,
                                tipo_arma="arma_blanca", confianza=0.8)
        entrar_como(client, "consulta")
        assert client.post(f"/api/alertas/{aid}/atender").status_code == 403

    def test_el_guardia_si_atiende_alertas(self, client, repo):
        aid = repo.crear_alerta(camara_id=1, punto_acceso_id=1,
                                tipo_arma="arma_blanca", confianza=0.8)
        repo.actualizar_estado_alerta(aid, "notificada")
        entrar_como(client, "guardia")
        assert client.post(f"/api/alertas/{aid}/atender").status_code == 200

    def test_el_guardia_no_lista_usuarios(self, client):
        entrar_como(client, "guardia")
        assert client.get("/api/usuarios").status_code == 403

    def test_el_guardia_no_consulta_la_bitacora(self, client):
        entrar_como(client, "guardia")
        assert client.get("/api/usuarios/auditoria").status_code == 403

    def test_el_guardia_no_escala_alertas(self, client):
        entrar_como(client, "guardia")
        assert client.post("/api/alertas/escalar").status_code == 403

    def test_el_guardia_si_consulta_el_historial(self, client):
        entrar_como(client, "guardia")
        assert client.get("/api/accesos").status_code == 200

    def test_el_guardia_no_borra_datos_biometricos(self, client, repo):
        pid = repo.crear_persona(autoriza_biometria=True)
        entrar_como(client, "guardia")
        assert client.delete(f"/api/personas/{pid}/biometria").status_code == 403


class TestLogin:
    def test_credenciales_validas_abren_sesion(self, client, repo):
        repo.crear_usuario("Admin", "admin@ejemplo.edu",
                           seguridad.hashear("secreta"), 1, rol="administrador")
        respuesta = client.post("/api/auth/login", json={
            "correo": "admin@ejemplo.edu", "contrasena": "secreta",
        })
        assert respuesta.status_code == 200
        assert respuesta.get_json()["rol"] == "administrador"

    def test_credenciales_invalidas_dan_401(self, client, repo):
        repo.crear_usuario("Admin", "admin@ejemplo.edu",
                           seguridad.hashear("secreta"), 1, rol="administrador")
        respuesta = client.post("/api/auth/login", json={
            "correo": "admin@ejemplo.edu", "contrasena": "mala",
        })
        assert respuesta.status_code == 401

    def test_faltan_campos(self, client):
        assert client.post("/api/auth/login", json={}).status_code == 400

    def test_la_cuenta_se_bloquea_desde_la_api(self, client, repo):
        uid = repo.crear_usuario("G", "g@ejemplo.edu",
                                 seguridad.hashear("buena"), 2, rol="guardia")
        for _ in range(Config.MAX_INTENTOS_FALLIDOS):
            client.post("/api/auth/login",
                        json={"correo": "g@ejemplo.edu", "contrasena": "mala"})
        assert repo.obtener_usuario(uid)["estado"] == "bloqueado"
        assert client.post("/api/auth/login", json={
            "correo": "g@ejemplo.edu", "contrasena": "buena",
        }).status_code == 401


class TestBiometriaYSupresion:
    def test_el_administrador_borra_los_datos_biometricos(self, client, repo):
        pid = repo.crear_persona(autoriza_biometria=True, estado="activo")
        from tests.ayudas import vector
        repo.guardar_codificacion(pid, vector(0.2))
        entrar_como(client, "administrador")
        respuesta = client.delete(f"/api/personas/{pid}/biometria")
        assert respuesta.status_code == 200
        assert respuesta.get_json()["codificaciones_eliminadas"] == 1

    def test_retirar_a_la_persona_elimina_su_biometria(self, client, repo):
        pid = repo.crear_persona(autoriza_biometria=True, estado="activo")
        from tests.ayudas import vector
        repo.guardar_codificacion(pid, vector(0.2))
        entrar_como(client, "administrador")
        client.patch(f"/api/personas/{pid}/estado", json={"estado": "retirado"})
        assert repo.codificaciones == []

    def test_persona_inexistente_da_404(self, client):
        entrar_como(client, "administrador")
        assert client.delete("/api/personas/999/biometria").status_code == 404


class TestAlertasApi:
    def test_la_alerta_se_crea_unida_a_la_persona(self, client, repo):
        pid = repo.crear_persona(estado="activo")
        rid = repo.registrar_acceso(punto_acceso_id=1, persona_id=pid,
                                    tipo_evento="ingreso", resultado="identificado")
        respuesta = client.post("/api/alertas", json={
            "camara_id": 1, "punto_acceso_id": 1, "tipo_arma": "arma_fuego",
            "confianza": 0.91, "registro_acceso_id": rid, "persona_id": pid,
        })
        assert respuesta.status_code == 201
        guardada = repo.obtener_alerta(respuesta.get_json()["id"])
        assert guardada["persona_id"] == pid
        assert guardada["estado"] == "notificada"

    def test_tipo_de_arma_invalido_da_400(self, client):
        respuesta = client.post("/api/alertas", json={
            "camara_id": 1, "punto_acceso_id": 1,
            "tipo_arma": "sombrilla", "confianza": 0.9,
        })
        assert respuesta.status_code == 400

    def test_faltan_campos_da_400(self, client):
        assert client.post("/api/alertas", json={"camara_id": 1}).status_code == 400

    def test_no_se_puede_atender_saltando_estados(self, client, repo):
        aid = repo.crear_alerta(camara_id=1, punto_acceso_id=1,
                                tipo_arma="arma_blanca", confianza=0.8)
        entrar_como(client, "guardia")
        # sigue en 'generada': atender salta un paso
        assert client.post(f"/api/alertas/{aid}/atender").status_code == 409

    def test_el_administrador_escala_las_pendientes(self, client, repo):
        from datetime import datetime, timedelta
        repo.crear_alerta(camara_id=1, punto_acceso_id=1, tipo_arma="arma_fuego",
                          confianza=0.9,
                          fecha_hora=datetime.now() - timedelta(minutes=60))
        entrar_como(client, "administrador")
        respuesta = client.post("/api/alertas/escalar")
        assert respuesta.status_code == 200
        assert respuesta.get_json()["total"] == 1


class TestCamaras:
    def test_marca_la_camara_que_no_cumple_el_rnf14(self, client, repo):
        repo.camaras = [{"id": 1, "punto_acceso_id": 1,
                         "identificador": "CAM-01",
                         "resolucion_ancho": 640, "resolucion_alto": 480}]
        entrar_como(client, "administrador")
        camaras = client.get("/api/camaras").get_json()["camaras"]
        assert camaras[0]["cumple_rnf14"] is False


class TestReportes:
    def test_el_resumen_responde(self, client):
        entrar_como(client, "administrador")
        assert client.get("/api/reportes/resumen").status_code == 200

    def test_la_exportacion_devuelve_csv(self, client, repo):
        pid = repo.crear_persona(estado="activo")
        repo.registrar_acceso(punto_acceso_id=1, persona_id=pid,
                              tipo_evento="ingreso", resultado="identificado")
        entrar_como(client, "administrador")
        respuesta = client.get("/api/reportes/accesos.csv")
        assert respuesta.status_code == 200
        assert respuesta.mimetype == "text/csv"
        assert "tipo_evento" in respuesta.get_data(as_text=True)


class TestAuditoria:
    def test_la_consulta_del_historial_queda_registrada(self, client, repo):
        entrar_como(client, "administrador")
        client.get("/api/accesos?limite=5")
        assert any(a["accion"] == "consulta_historial" for a in repo.auditoria)

    def test_el_acceso_denegado_queda_registrado(self, client, repo):
        entrar_como(client, "guardia")
        client.get("/api/usuarios")
        assert any(a["accion"] == "acceso_denegado" for a in repo.auditoria)
