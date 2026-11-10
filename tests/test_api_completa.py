"""Caja blanca de los endpoints que faltaban y del panel web.

Completa la cobertura de la API: enrolamiento, identificacion desde la
estacion de captura, verificacion manual, gestion de usuarios y camaras, y
las vistas del panel.
"""

from __future__ import annotations

import base64
import io

import numpy as np
import pytest
from PIL import Image

from app import seguridad
from app.servicios import control_acceso
from tests.ayudas import vector, vector_a_distancia
from tests.test_api import app, client, entrar_como  # noqa: F401  (fixtures)


def imagen_base64() -> str:
    """Una imagen real y diminuta, suficiente para que Pillow la abra."""
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (120, 120, 120)).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode()


@pytest.fixture
def sin_dlib(monkeypatch):
    """Sustituye la codificacion facial para no depender de dlib."""
    def codificar(imagen_rgb, estricto=True):
        return vector(0.0)

    monkeypatch.setattr(control_acceso, "codificar_rostro", codificar)
    monkeypatch.setattr(
        "app.servicios.reconocimiento_facial.codificar_rostro", codificar
    )
    return codificar


class TestEnrolamiento:
    def test_enrola_a_quien_autorizo(self, client, repo, monkeypatch):
        monkeypatch.setattr(
            "app.servicios.reconocimiento_facial.codificar_rostro",
            lambda img, estricto=True: vector(0.1),
        )
        pid = repo.crear_persona(autoriza_biometria=True)
        entrar_como(client, "administrador")
        respuesta = client.post(f"/api/personas/{pid}/enrolar",
                                json={"imagen": imagen_base64()})
        assert respuesta.status_code == 201
        assert len(repo.codificaciones) == 1

    def test_rechaza_enrolar_a_quien_no_autorizo(self, client, repo, monkeypatch):
        monkeypatch.setattr(
            "app.servicios.reconocimiento_facial.codificar_rostro",
            lambda img, estricto=True: vector(0.1),
        )
        pid = repo.crear_persona(autoriza_biometria=False)
        entrar_como(client, "administrador")
        respuesta = client.post(f"/api/personas/{pid}/enrolar",
                                json={"imagen": imagen_base64()})
        assert respuesta.status_code == 409
        assert repo.codificaciones == []

    def test_sin_imagen_da_400(self, client, repo):
        pid = repo.crear_persona(autoriza_biometria=True)
        entrar_como(client, "administrador")
        assert client.post(f"/api/personas/{pid}/enrolar", json={}).status_code == 400

    def test_imagen_sin_rostro_da_400(self, client, repo, monkeypatch):
        from app.servicios.reconocimiento_facial import RostroNoDetectado

        def fallar(img, estricto=True):
            raise RostroNoDetectado("sin rostro")

        monkeypatch.setattr(
            "app.servicios.reconocimiento_facial.codificar_rostro", fallar
        )
        pid = repo.crear_persona(autoriza_biometria=True)
        entrar_como(client, "administrador")
        assert client.post(f"/api/personas/{pid}/enrolar",
                           json={"imagen": imagen_base64()}).status_code == 400

    def test_imagen_con_varios_rostros_da_400(self, client, repo, monkeypatch):
        from app.servicios.reconocimiento_facial import VariosRostros

        def fallar(img, estricto=True):
            raise VariosRostros("dos rostros")

        monkeypatch.setattr(
            "app.servicios.reconocimiento_facial.codificar_rostro", fallar
        )
        pid = repo.crear_persona(autoriza_biometria=True)
        entrar_como(client, "administrador")
        assert client.post(f"/api/personas/{pid}/enrolar",
                           json={"imagen": imagen_base64()}).status_code == 400


class TestPersonasApi:
    def test_lista_personas(self, client, repo):
        repo.crear_persona(nombres="Ana", apellidos="Ruiz")
        entrar_como(client, "consulta")
        datos = client.get("/api/personas").get_json()
        assert len(datos["personas"]) == 1

    def test_detalle_de_persona(self, client, repo):
        pid = repo.crear_persona(nombres="Ana", apellidos="Ruiz")
        entrar_como(client, "guardia")
        assert client.get(f"/api/personas/{pid}").get_json()["nombres"] == "Ana"

    def test_detalle_inexistente_da_404(self, client):
        entrar_como(client, "guardia")
        assert client.get("/api/personas/999").status_code == 404

    def test_tipo_de_persona_invalido_da_400(self, client):
        entrar_como(client, "administrador")
        respuesta = client.post("/api/personas", json={
            "institucion_id": 1, "documento": "1", "tipo_persona": "alien",
            "nombres": "A", "apellidos": "B",
        })
        assert respuesta.status_code == 400

    def test_faltan_campos_da_400(self, client):
        entrar_como(client, "administrador")
        assert client.post("/api/personas", json={"nombres": "A"}).status_code == 400

    def test_estado_invalido_da_400(self, client, repo):
        pid = repo.crear_persona()
        entrar_como(client, "administrador")
        assert client.patch(f"/api/personas/{pid}/estado",
                            json={"estado": "zombi"}).status_code == 400

    def test_estado_de_persona_inexistente_da_404(self, client):
        entrar_como(client, "administrador")
        assert client.patch("/api/personas/999/estado",
                            json={"estado": "activo"}).status_code == 404


class TestIdentificacionDesdeLaEstacion:
    def test_identifica_y_registra(self, client, repo, sin_dlib):
        pid = repo.crear_persona(autoriza_biometria=True, estado="activo")
        repo.guardar_codificacion(pid, vector(0.0))
        respuesta = client.post("/api/accesos/identificar", json={
            "imagen": imagen_base64(), "punto_acceso_id": 1, "camara_id": 1,
        })
        datos = respuesta.get_json()
        assert respuesta.status_code == 200
        assert datos["identificado"] is True
        assert datos["tipo_evento"] == "ingreso"

    def test_el_desconocido_queda_registrado_para_verificacion(self, client, repo, sin_dlib):
        otro = repo.crear_persona(autoriza_biometria=True, estado="activo")
        repo.guardar_codificacion(otro, vector_a_distancia(0.0, 0.95))
        respuesta = client.post("/api/accesos/identificar", json={
            "imagen": imagen_base64(), "punto_acceso_id": 1,
            "imagen_url": "s3://ev/9.jpg",
        })
        datos = respuesta.get_json()
        assert datos["identificado"] is False
        assert datos["resultado"] == "no_identificado"
        assert datos["registro_id"] is not None
        assert repo.listar_accesos()[0]["imagen_url"] == "s3://ev/9.jpg"

    def test_falta_la_imagen(self, client):
        assert client.post("/api/accesos/identificar",
                           json={"punto_acceso_id": 1}).status_code == 400

    def test_falta_el_punto_de_acceso(self, client):
        assert client.post("/api/accesos/identificar",
                           json={"imagen": imagen_base64()}).status_code == 400

    def test_imagen_corrupta(self, client):
        assert client.post("/api/accesos/identificar", json={
            "imagen": "esto-no-es-una-imagen", "punto_acceso_id": 1,
        }).status_code == 400


class TestVerificacionYCredencial:
    def test_el_guardia_verifica_un_evento(self, client, repo):
        pid = repo.crear_persona(estado="activo")
        rid = repo.registrar_acceso(punto_acceso_id=1, tipo_evento="ingreso",
                                    resultado="no_identificado")
        entrar_como(client, "guardia")
        respuesta = client.post(f"/api/accesos/{rid}/verificar",
                                json={"aprobado": True, "persona_id": pid})
        assert respuesta.status_code == 200
        assert respuesta.get_json()["resultado"] == "verificado_manual"

    def test_verificar_un_registro_inexistente_da_404(self, client):
        entrar_como(client, "guardia")
        assert client.post("/api/accesos/999/verificar",
                           json={"aprobado": True}).status_code == 404

    def test_ingreso_con_credencial(self, client, repo):
        pid = repo.crear_persona(estado="activo", autoriza_biometria=False)
        entrar_como(client, "guardia")
        respuesta = client.post("/api/accesos/credencial",
                                json={"persona_id": pid, "punto_acceso_id": 1})
        assert respuesta.status_code == 201
        assert respuesta.get_json()["metodo"] == "credencial"

    def test_credencial_sin_persona_da_400(self, client):
        entrar_como(client, "guardia")
        assert client.post("/api/accesos/credencial",
                           json={"punto_acceso_id": 1}).status_code == 400

    def test_credencial_de_persona_inexistente_da_404(self, client):
        entrar_como(client, "guardia")
        assert client.post("/api/accesos/credencial", json={
            "persona_id": 999, "punto_acceso_id": 1,
        }).status_code == 404


class TestUsuariosApi:
    def test_el_administrador_crea_usuarios(self, client, repo):
        entrar_como(client, "administrador")
        respuesta = client.post("/api/usuarios", json={
            "nombre": "Nuevo", "correo": "n@ejemplo.edu",
            "contrasena": "clave", "rol_id": 2,
        })
        assert respuesta.status_code == 201
        guardado = repo.obtener_usuario(respuesta.get_json()["id"])
        assert "clave" not in guardado["contrasena_hash"]

    def test_faltan_campos_da_400(self, client):
        entrar_como(client, "administrador")
        assert client.post("/api/usuarios", json={"nombre": "x"}).status_code == 400

    def test_lista_usuarios(self, client, repo):
        repo.crear_usuario("A", "a@e.edu", seguridad.hashear("x"), 1)
        entrar_como(client, "administrador")
        assert len(client.get("/api/usuarios").get_json()["usuarios"]) == 1

    def test_desbloquea_una_cuenta(self, client, repo):
        uid = repo.crear_usuario("A", "a@e.edu", seguridad.hashear("x"), 2,
                                 estado="bloqueado")
        entrar_como(client, "administrador")
        respuesta = client.patch(f"/api/usuarios/{uid}/estado",
                                 json={"estado": "activo"})
        assert respuesta.status_code == 200
        assert repo.obtener_usuario(uid)["estado"] == "activo"

    def test_estado_invalido_da_400(self, client, repo):
        uid = repo.crear_usuario("A", "a@e.edu", seguridad.hashear("x"), 2)
        entrar_como(client, "administrador")
        assert client.patch(f"/api/usuarios/{uid}/estado",
                            json={"estado": "zombi"}).status_code == 400

    def test_usuario_inexistente_da_404(self, client):
        entrar_como(client, "administrador")
        assert client.patch("/api/usuarios/999/estado",
                            json={"estado": "activo"}).status_code == 404

    def test_el_administrador_consulta_la_bitacora(self, client, repo):
        repo.registrar_auditoria(1, "prueba")
        entrar_como(client, "administrador")
        assert len(client.get("/api/usuarios/auditoria").get_json()["registros"]) >= 1


class TestCamarasApi:
    def test_lista_puntos_de_acceso(self, client):
        entrar_como(client, "consulta")
        assert client.get("/api/puntos-acceso").status_code == 200

    def test_crea_un_punto_de_acceso(self, client):
        entrar_como(client, "administrador")
        respuesta = client.post("/api/puntos-acceso", json={
            "institucion_id": 1, "nombre": "Porteria norte",
        })
        assert respuesta.status_code == 201

    def test_punto_sin_nombre_da_400(self, client):
        entrar_como(client, "administrador")
        assert client.post("/api/puntos-acceso",
                           json={"institucion_id": 1}).status_code == 400

    def test_crea_una_camara(self, client):
        entrar_como(client, "administrador")
        respuesta = client.post("/api/camaras", json={
            "punto_acceso_id": 1, "identificador": "CAM-02",
            "resolucion_ancho": 1920, "resolucion_alto": 1080,
        })
        assert respuesta.status_code == 201

    def test_camara_sin_identificador_da_400(self, client):
        entrar_como(client, "administrador")
        assert client.post("/api/camaras",
                           json={"punto_acceso_id": 1}).status_code == 400

    def test_la_camara_que_cumple_queda_marcada(self, client):
        entrar_como(client, "administrador")
        camaras = client.get("/api/camaras").get_json()["camaras"]
        assert camaras[0]["cumple_rnf14"] is True


class TestPanelWeb:
    def test_el_login_se_muestra(self, client):
        assert client.get("/login").status_code == 200

    def test_la_raiz_redirige(self, client):
        assert client.get("/").status_code in (301, 302)

    def test_el_panel_exige_sesion(self, client):
        assert client.get("/panel").status_code in (301, 302)

    def test_el_panel_responde_con_sesion(self, client):
        entrar_como(client, "guardia")
        assert client.get("/panel").status_code == 200

    def test_los_registros_responden_con_sesion(self, client):
        entrar_como(client, "guardia")
        assert client.get("/registros?punto=1").status_code == 200

    def test_login_correcto_redirige_al_panel(self, client, repo):
        repo.crear_usuario("G", "g@e.edu", seguridad.hashear("clave"), 2,
                           rol="guardia")
        respuesta = client.post("/login", data={
            "correo": "g@e.edu", "contrasena": "clave",
        })
        assert respuesta.status_code in (301, 302)

    def test_login_incorrecto_responde_401(self, client, repo):
        repo.crear_usuario("G", "g@e.edu", seguridad.hashear("clave"), 2,
                           rol="guardia")
        respuesta = client.post("/login", data={
            "correo": "g@e.edu", "contrasena": "mala",
        })
        assert respuesta.status_code == 401

    def test_logout_cierra_la_sesion(self, client):
        entrar_como(client, "guardia")
        assert client.get("/logout").status_code in (301, 302)
        assert client.get("/panel").status_code in (301, 302)


class TestSesionApi:
    def test_yo_sin_sesion_da_401(self, client):
        assert client.get("/api/auth/yo").status_code == 401

    def test_yo_con_sesion_devuelve_el_rol(self, client):
        entrar_como(client, "guardia")
        assert client.get("/api/auth/yo").get_json()["rol"] == "guardia"

    def test_logout_por_api(self, client):
        entrar_como(client, "guardia")
        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/auth/yo").status_code == 401


class TestEndpointEvento:
    """Via principal: el servidor recibe la codificacion, no la imagen."""

    def test_identifica_a_partir_de_la_codificacion(self, client, repo):
        pid = repo.crear_persona(autoriza_biometria=True, estado="activo")
        repo.guardar_codificacion(pid, vector(0.0))
        respuesta = client.post("/api/accesos/evento", json={
            "codificacion": vector(0.0).tolist(),
            "punto_acceso_id": 1, "camara_id": 1,
        })
        datos = respuesta.get_json()
        assert respuesta.status_code == 200
        assert datos["identificado"] is True
        assert datos["persona_id"] == pid

    def test_el_desconocido_queda_registrado(self, client, repo):
        otro = repo.crear_persona(autoriza_biometria=True, estado="activo")
        repo.guardar_codificacion(otro, vector_a_distancia(0.0, 0.95))
        respuesta = client.post("/api/accesos/evento", json={
            "codificacion": vector(0.0).tolist(), "punto_acceso_id": 1,
        })
        assert respuesta.get_json()["resultado"] == "no_identificado"

    def test_codificacion_de_tamano_incorrecto_da_400(self, client):
        respuesta = client.post("/api/accesos/evento", json={
            "codificacion": [0.1, 0.2], "punto_acceso_id": 1,
        })
        assert respuesta.status_code == 400

    def test_codificacion_ausente_da_400(self, client):
        assert client.post("/api/accesos/evento",
                           json={"punto_acceso_id": 1}).status_code == 400

    def test_sin_punto_de_acceso_da_400(self, client):
        assert client.post("/api/accesos/evento", json={
            "codificacion": vector(0.0).tolist(),
        }).status_code == 400

    def test_codificacion_con_texto_da_400(self, client):
        respuesta = client.post("/api/accesos/evento", json={
            "codificacion": ["a"] * 128, "punto_acceso_id": 1,
        })
        assert respuesta.status_code == 400

    def test_no_repite_el_evento_dentro_de_la_ventana(self, client, repo):
        pid = repo.crear_persona(autoriza_biometria=True, estado="activo")
        repo.guardar_codificacion(pid, vector(0.0))
        cuerpo = {"codificacion": vector(0.0).tolist(), "punto_acceso_id": 1}
        primero = client.post("/api/accesos/evento", json=cuerpo).get_json()
        segundo = client.post("/api/accesos/evento", json=cuerpo).get_json()
        assert segundo["registro_id"] == primero["registro_id"]
        assert segundo["motivo"] == "evento_reciente_omitido"
        assert len(repo.registros) == 1
