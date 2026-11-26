"""Caja blanca de las mejoras pedidas por la asesoria (revision del 21 nov).

Cada clase corresponde a uno de los puntos de la revision:

1. Panel de seguridad: atender, confirmar o descartar alertas desde la
   interfaz, ver las escaladas y refrescarse solo.
2. Deteccion de armas: no atribuir el arma por estar en el mismo fotograma y
   no repetir alertas. (Logica en tests/test_alertas.py; aqui, la API.)
3. Seguridad: estaciones autenticadas, permisos verificados en cada peticion,
   sesiones y operaciones protegidas.
4. Escalamiento automatico. (tests/test_alertas.py::TestEscalamientoAutomatico)
5. Evidencia de incidentes: el guardia ve la imagen de cada alerta.
6. Control de acceso: ingreso y salida bien decididos, sin duplicados.
7. Validacion: el script de metricas del reconocimiento facial.
8. Base de datos de pruebas aislada de la de produccion.
"""

from __future__ import annotations

import base64
import csv
import io
from datetime import datetime, timedelta

import pytest
from PIL import Image

from app import crear_app, seguridad
from app.config import Config
from app.servicios import control_acceso, evidencias
from tests.ayudas import ESTACION, vector, vector_a_distancia
from tests.test_api import ConfigPrueba, app, client, entrar_como  # noqa: F401


def jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), (90, 90, 90)).save(buffer, format="JPEG")
    return buffer.getvalue()


def alerta_abierta(repo, estado="notificada", contexto=None, **extra):
    aid = repo.crear_alerta(camara_id=1, punto_acceso_id=1, tipo_arma="arma_fuego",
                            confianza=0.9, persona_contexto_id=contexto, **extra)
    repo.alertas[aid]["estado"] = estado
    return aid


# ===========================================================================
# 1. Panel de seguridad
# ===========================================================================

class TestPanelDelGuardia:
    def test_muestra_las_alertas_abiertas_con_sus_acciones(self, client, repo):
        alerta_abierta(repo)
        entrar_como(client, "guardia")
        html = client.get("/panel").get_data(as_text=True)
        assert "Alertas abiertas (1)" in html
        assert "Atender" in html

    def test_las_escaladas_aparecen_primero_y_marcadas(self, client, repo):
        alerta_abierta(repo, "notificada")
        alerta_abierta(repo, "escalada")
        entrar_como(client, "guardia")
        html = client.get("/panel/alertas").get_data(as_text=True)
        assert "escalada al administrador" in html
        assert html.index("estado-escalada") < html.index("estado-notificada")

    def test_el_panel_se_refresca_solo(self, client, repo):
        entrar_como(client, "guardia")
        html = client.get("/panel").get_data(as_text=True)
        assert 'data-url="/panel/alertas"' in html
        assert "setInterval" in html

    def test_el_guardia_atiende_desde_la_interfaz(self, client, repo):
        aid = alerta_abierta(repo)
        entrar_como(client, "guardia", usuario_id=7)
        respuesta = client.post(f"/panel/alertas/{aid}/atender",
                                data={"csrf": "token-csrf-de-prueba"})
        assert respuesta.status_code == 302
        assert repo.alertas[aid]["estado"] == "en_atencion"
        assert repo.alertas[aid]["atendida_por"] == 7

    def test_el_guardia_confirma_e_indica_el_portador(self, client, repo):
        pid = repo.crear_persona(nombres="Ana", apellidos="Ruiz")
        aid = alerta_abierta(repo, "en_atencion", contexto=pid)
        repo.alertas[aid]["atendida_por"] = 7
        entrar_como(client, "guardia", usuario_id=7)
        client.post(f"/panel/alertas/{aid}/resolver", data={
            "csrf": "token-csrf-de-prueba", "desenlace": "confirmada",
            "portador_id": str(pid),
        })
        assert repo.alertas[aid]["estado"] == "cerrada"
        assert repo.alertas[aid]["portador_id"] == pid

    def test_el_guardia_descarta_un_falso_positivo(self, client, repo):
        pid = repo.crear_persona()
        aid = alerta_abierta(repo, "en_atencion", contexto=pid)
        repo.alertas[aid]["atendida_por"] = 7
        entrar_como(client, "guardia", usuario_id=7)
        client.post(f"/panel/alertas/{aid}/resolver", data={
            "csrf": "token-csrf-de-prueba", "desenlace": "falso_positivo",
            "portador_id": str(pid),          # se ignora en un falso positivo
        })
        assert repo.alertas[aid]["estado"] == "cerrada"
        assert repo.alertas[aid]["portador_id"] is None
        acciones = [a for a in repo.auditoria if a["accion"] == "resolver_alerta"]
        assert acciones[-1]["detalle"] == "falso_positivo"

    def test_sin_token_del_formulario_no_se_atiende(self, client, repo):
        aid = alerta_abierta(repo)
        entrar_como(client, "guardia")
        assert client.post(f"/panel/alertas/{aid}/atender",
                           data={"csrf": "otro"}).status_code == 400
        assert repo.alertas[aid]["estado"] == "notificada"

    def test_el_rol_consulta_ve_pero_no_actua(self, client, repo):
        aid = alerta_abierta(repo)
        entrar_como(client, "consulta")
        html = client.get("/panel/alertas").get_data(as_text=True)
        assert "Atender" not in html
        assert client.post(f"/panel/alertas/{aid}/atender",
                           data={"csrf": "token-csrf-de-prueba"}).status_code == 403

    def test_el_contexto_se_presenta_como_contexto(self, client, repo):
        pid = repo.crear_persona(nombres="Ana", apellidos="Ruiz")
        alerta_abierta(repo, contexto=pid)
        entrar_como(client, "guardia")
        html = client.get("/panel/alertas").get_data(as_text=True)
        assert "Ana Ruiz" in html
        assert "no prueba de que porte el arma" in html

    def test_abrir_el_panel_escala_lo_pendiente(self, client, repo):
        aid = repo.crear_alerta(camara_id=1, punto_acceso_id=1, tipo_arma="arma_fuego",
                                confianza=0.9, fecha_hora=datetime.now() - timedelta(hours=1))
        entrar_como(client, "guardia")
        client.get("/panel")
        assert repo.alertas[aid]["estado"] == "escalada"

    def test_el_historial_no_falla_con_ingresos_por_credencial(self, client, repo):
        """Antes la plantilla formateaba una confianza nula y se caia."""
        pid = repo.crear_persona(nombres="Lu", apellidos="Pa")
        repo.registrar_acceso(punto_acceso_id=1, tipo_evento="ingreso",
                              resultado="identificado", persona_id=pid, metodo="credencial")
        entrar_como(client, "guardia")
        assert client.get("/registros").status_code == 200
        assert client.get("/panel").status_code == 200


# ===========================================================================
# 2. Deteccion de armas a traves de la API
# ===========================================================================

class TestAlertasDesdeLaEstacion:
    def test_la_deteccion_repetida_responde_200_y_no_crea_otra(self, client, repo):
        cuerpo = {"tipo_arma": "arma_blanca", "confianza": 0.8}
        primera = client.post("/api/alertas", headers=ESTACION, json=cuerpo)
        segunda = client.post("/api/alertas", headers=ESTACION, json=cuerpo)
        assert primera.status_code == 201
        assert segunda.status_code == 200
        assert segunda.get_json()["duplicada"] is True
        assert len(repo.alertas) == 1

    def test_la_confianza_fuera_de_rango_da_400(self, client):
        assert client.post("/api/alertas", headers=ESTACION, json={
            "tipo_arma": "arma_fuego", "confianza": 7,
        }).status_code == 400

    def test_el_guardia_indica_el_portador_por_api(self, client, repo):
        pid = repo.crear_persona()
        aid = alerta_abierta(repo, "en_atencion", contexto=pid)
        repo.alertas[aid]["atendida_por"] = 1
        entrar_como(client, "guardia")
        respuesta = client.post(f"/api/alertas/{aid}/resolver",
                                json={"confirmada": True, "portador_id": pid})
        assert respuesta.status_code == 200
        assert respuesta.get_json()["portador_id"] == pid

    def test_falso_positivo_con_portador_da_409(self, client, repo):
        pid = repo.crear_persona()
        aid = alerta_abierta(repo, "en_atencion", contexto=pid)
        repo.alertas[aid]["atendida_por"] = 1
        entrar_como(client, "guardia")
        assert client.post(f"/api/alertas/{aid}/resolver",
                           json={"confirmada": False, "portador_id": pid}).status_code == 409

    def test_lista_solo_las_abiertas(self, client, repo):
        alerta_abierta(repo, "notificada")
        alerta_abierta(repo, "cerrada")
        entrar_como(client, "guardia")
        alertas = client.get("/api/alertas?abiertas=1").get_json()["alertas"]
        assert [a["estado"] for a in alertas] == ["notificada"]


# ===========================================================================
# 3. Seguridad
# ===========================================================================

class TestEstacionesAutenticadas:
    @pytest.mark.parametrize("cabecera", [
        None, "Bearer", "Bearer 1.equivocado", "Bearer 9.secreto-de-prueba",
        "Bearer x.y", "Basic abc",
    ])
    def test_sin_credencial_valida_no_se_registran_eventos(self, client, repo, cabecera):
        headers = {"Authorization": cabecera} if cabecera else {}
        respuesta = client.post("/api/accesos/evento", headers=headers,
                                json={"codificacion": vector(0.0).tolist()})
        assert respuesta.status_code == 401
        assert repo.registros == []

    def test_sin_credencial_no_se_crean_alertas(self, client, repo):
        assert client.post("/api/alertas", json={
            "tipo_arma": "arma_fuego", "confianza": 0.99,
        }).status_code == 401
        assert repo.alertas == {}
        assert repo.auditoria[-1]["accion"] == "estacion_rechazada"

    def test_una_camara_inactiva_no_entra(self, client, repo):
        repo.camaras[0]["estado"] = "inactiva"
        assert client.post("/api/alertas", headers=ESTACION, json={
            "tipo_arma": "arma_fuego", "confianza": 0.9,
        }).status_code == 401

    def test_el_administrador_emite_y_rota_la_credencial(self, client, repo):
        entrar_como(client, "administrador")
        respuesta = client.post("/api/camaras/1/credencial")
        assert respuesta.status_code == 201
        token = respuesta.get_json()["token"]
        # la anterior deja de servir; la nueva funciona
        assert client.post("/api/alertas", headers=ESTACION, json={
            "tipo_arma": "arma_fuego", "confianza": 0.9}).status_code == 401
        assert client.post("/api/alertas", headers={"Authorization": f"Bearer {token}"},
                           json={"tipo_arma": "arma_fuego", "confianza": 0.9}).status_code == 201

    def test_el_guardia_no_emite_credenciales(self, client):
        entrar_como(client, "guardia")
        assert client.post("/api/camaras/1/credencial").status_code == 403

    def test_la_lista_de_camaras_no_expone_el_resumen(self, client):
        entrar_como(client, "administrador")
        camara = client.get("/api/camaras").get_json()["camaras"][0]
        assert "token_hash" not in camara
        assert camara["tiene_credencial"] is True

    def test_credencial_de_camara_inexistente_da_404(self, client):
        entrar_como(client, "administrador")
        assert client.post("/api/camaras/99/credencial").status_code == 404


class TestPermisosVerificadosEnCadaPeticion:
    def test_una_cuenta_bloqueada_pierde_la_sesion_abierta(self, client, repo):
        entrar_como(client, "guardia", usuario_id=3)
        assert client.get("/api/accesos").status_code == 200
        repo.usuarios[3]["estado"] = "bloqueado"
        assert client.get("/api/accesos").status_code == 401

    def test_un_cambio_de_rol_rige_de_inmediato(self, client, repo):
        entrar_como(client, "administrador", usuario_id=3)
        assert client.get("/api/usuarios").status_code == 200
        repo.usuarios[3]["rol"] = "guardia"
        assert client.get("/api/usuarios").status_code == 403

    def test_una_cuenta_borrada_no_conserva_acceso(self, client, repo):
        entrar_como(client, "guardia", usuario_id=3)
        del repo.usuarios[3]
        assert client.get("/api/accesos").status_code == 401

    def test_permiso_del_rol(self):
        assert seguridad.tiene_permiso({"rol": "guardia", "permisos": ["alerta:atender"]},
                                       "alerta:atender")
        assert not seguridad.tiene_permiso({"rol": "consulta", "permisos": []},
                                           "alerta:atender")
        assert seguridad.tiene_permiso({"rol": "administrador"}, "cualquier:cosa")


class TestSesionesYOperaciones:
    def test_la_cookie_de_sesion_esta_protegida(self, app):
        assert app.config["SESSION_COOKIE_HTTPONLY"] is True
        assert app.config["SESSION_COOKIE_SAMESITE"] == "Strict"
        assert app.permanent_session_lifetime == timedelta(hours=Config.HORAS_SESION)

    def test_el_login_renueva_la_sesion(self, client, repo):
        repo.crear_usuario("G", "g@x.edu", seguridad.hashear("clave"), 2, rol="guardia")
        with client.session_transaction() as s:
            s["dato_previo"] = "de otra persona"
        client.post("/api/auth/login", json={"correo": "g@x.edu", "contrasena": "clave"})
        with client.session_transaction() as s:
            assert "dato_previo" not in s
            assert "csrf" in s

    def test_una_escritura_desde_otro_sitio_se_rechaza(self, client, repo):
        entrar_como(client, "administrador")
        respuesta = client.post("/api/alertas/escalar",
                                headers={"Origin": "https://sitio-malicioso.com"})
        assert respuesta.status_code == 403

    def test_una_escritura_del_mismo_sitio_pasa(self, client):
        entrar_como(client, "administrador")
        respuesta = client.post("/api/alertas/escalar", headers={"Origin": "http://localhost"})
        assert respuesta.status_code == 200

    def test_cabeceras_de_seguridad(self, client):
        respuesta = client.get("/salud")
        assert respuesta.headers["X-Frame-Options"] == "DENY"
        assert respuesta.headers["X-Content-Type-Options"] == "nosniff"

    def test_en_produccion_no_arranca_con_la_clave_por_defecto(self):
        class Produccion(Config):
            APP_ENV = "produccion"
            SECRET_KEY = "cambiar-en-produccion"
            ESCALAMIENTO_AUTOMATICO = False

        with pytest.raises(RuntimeError):
            crear_app(Produccion)

    def test_la_peticion_demasiado_grande_se_rechaza(self, client):
        enorme = "A" * (Config.MAX_CONTENT_LENGTH + 10)
        respuesta = client.post("/api/alertas", headers=ESTACION, data=enorme,
                                content_type="application/json")
        assert respuesta.status_code == 413


# ===========================================================================
# 5. Evidencia de incidentes
# ===========================================================================

class TestEvidencia:
    @pytest.fixture(autouse=True)
    def carpeta(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Config, "EVIDENCIAS_DIR", str(tmp_path))
        monkeypatch.setattr(Config, "SUPABASE_URL", "")
        return tmp_path

    def test_la_estacion_envia_la_imagen_y_queda_guardada(self, client, repo):
        respuesta = client.post("/api/alertas", headers=ESTACION, json={
            "tipo_arma": "arma_fuego", "confianza": 0.9,
            "imagen": base64.b64encode(jpeg()).decode(),
        })
        alerta = repo.obtener_alerta(respuesta.get_json()["id"])
        assert alerta["imagen_url"].startswith("local:alertas/")

    def test_el_guardia_ve_la_imagen_y_queda_en_la_bitacora(self, client, repo):
        aid = alerta_abierta(repo)
        repo.alertas[aid]["imagen_url"] = evidencias.guardar(aid, jpeg())
        entrar_como(client, "guardia")
        for ruta in (f"/api/alertas/{aid}/evidencia", f"/panel/alertas/{aid}/evidencia"):
            respuesta = client.get(ruta)
            assert respuesta.status_code == 200
            assert respuesta.mimetype == "image/jpeg"
            assert respuesta.headers["Cache-Control"] == "no-store"
        assert [a["accion"] for a in repo.auditoria].count("ver_evidencia") == 2

    def test_el_rol_consulta_no_ve_la_imagen(self, client, repo):
        aid = alerta_abierta(repo)
        repo.alertas[aid]["imagen_url"] = evidencias.guardar(aid, jpeg())
        entrar_como(client, "consulta")
        assert client.get(f"/api/alertas/{aid}/evidencia").status_code == 403
        assert client.get(f"/panel/alertas/{aid}/evidencia").status_code == 403

    def test_alerta_sin_imagen_da_404(self, client, repo):
        aid = alerta_abierta(repo)
        entrar_como(client, "guardia")
        assert client.get(f"/api/alertas/{aid}/evidencia").status_code == 404
        assert client.get(f"/panel/alertas/{aid}/evidencia").status_code == 404

    def test_el_panel_ofrece_ver_la_evidencia(self, client, repo):
        aid = alerta_abierta(repo)
        repo.alertas[aid]["imagen_url"] = "local:alertas/1.jpg"
        entrar_como(client, "guardia")
        assert "Ver evidencia" in client.get("/panel/alertas").get_data(as_text=True)

    def test_lo_que_no_es_imagen_se_rechaza(self):
        with pytest.raises(evidencias.EvidenciaInvalida):
            evidencias.guardar(1, b"no soy una imagen")

    def test_una_ruta_maliciosa_no_sale_de_la_carpeta(self):
        with pytest.raises(FileNotFoundError):
            evidencias.leer("local:../../etc/passwd")
        with pytest.raises(FileNotFoundError):
            evidencias.leer("ftp:algo.jpg")


# ===========================================================================
# 6. Control de acceso: ingreso, salida y duplicados
# ===========================================================================

class TestIngresoYSalida:
    def test_punto_de_solo_entrada_siempre_registra_ingreso(self):
        ultimo = {"tipo_evento": "ingreso", "fecha_hora": datetime.now()}
        assert control_acceso.decidir_evento(ultimo, "entrada") == "ingreso"

    def test_punto_de_solo_salida_siempre_registra_salida(self):
        assert control_acceso.decidir_evento(None, "salida") == "salida"

    def test_punto_mixto_alterna(self):
        ultimo = {"tipo_evento": "ingreso",
                  "fecha_hora": datetime.now() - timedelta(hours=2)}
        assert control_acceso.decidir_evento(ultimo, "mixto") == "salida"

    def test_un_ingreso_de_ayer_sin_salida_no_convierte_hoy_en_salida(self):
        ultimo = {"tipo_evento": "ingreso",
                  "fecha_hora": datetime.now() - timedelta(
                      hours=Config.HORAS_JORNADA_MAXIMA + 1)}
        assert control_acceso.decidir_evento(ultimo, "mixto") == "ingreso"

    def test_el_sentido_del_punto_se_aplica_en_el_flujo(self, client, repo):
        repo.puntos[1]["sentido"] = "entrada"
        pid = repo.crear_persona(autoriza_biometria=True, estado="activo")
        repo.guardar_codificacion(pid, vector(0.0))
        repo.registrar_acceso(punto_acceso_id=1, tipo_evento="ingreso",
                              resultado="identificado", persona_id=pid,
                              fecha_hora=datetime.now() - timedelta(hours=1))
        datos = client.post("/api/accesos/evento", headers=ESTACION,
                            json={"codificacion": vector(0.0).tolist()}).get_json()
        assert datos["tipo_evento"] == "ingreso"


class TestSinDuplicados:
    def test_el_mismo_desconocido_se_registra_una_sola_vez(self, client, repo):
        otro = repo.crear_persona(autoriza_biometria=True, estado="activo")
        repo.guardar_codificacion(otro, vector_a_distancia(0.0, 0.95))
        cuerpo = {"codificacion": vector(0.0).tolist()}
        primero = client.post("/api/accesos/evento", headers=ESTACION, json=cuerpo).get_json()
        segundo = client.post("/api/accesos/evento", headers=ESTACION, json=cuerpo).get_json()
        assert len(repo.registros) == 1
        assert segundo["registro_id"] == primero["registro_id"]
        assert segundo["motivo"] == "evento_reciente_omitido"

    def test_dos_desconocidos_distintos_si_se_registran(self, client, repo):
        otro = repo.crear_persona(autoriza_biometria=True, estado="activo")
        repo.guardar_codificacion(otro, vector(5.0))
        client.post("/api/accesos/evento", headers=ESTACION,
                    json={"codificacion": vector(0.0).tolist()})
        client.post("/api/accesos/evento", headers=ESTACION,
                    json={"codificacion": vector(1.0).tolist()})
        assert len(repo.registros) == 2

    def test_si_otro_fotograma_gano_la_carrera_no_se_duplica(self, repo, monkeypatch):
        """La comprobacion previa no basta: decide la transaccion."""
        pid = repo.crear_persona(nombres="A", apellidos="B",
                                 autoriza_biometria=True, estado="activo")
        repo.guardar_codificacion(pid, vector(0.0))
        monkeypatch.setattr(repo, "ultimo_registro", lambda _pid: None)
        primero = control_acceso.procesar_codificacion(vector(0.0), 1, repositorio=repo)
        segundo = control_acceso.procesar_codificacion(vector(0.0), 1, repositorio=repo)
        assert len(repo.registros) == 1
        assert segundo.motivo == "evento_reciente_omitido"
        assert segundo.registro_id == primero.registro_id

    def test_la_credencial_tampoco_duplica(self, repo, monkeypatch):
        pid = repo.crear_persona(nombres="A", apellidos="B")
        monkeypatch.setattr(repo, "ultimo_registro", lambda _pid: None)
        control_acceso.registrar_con_credencial(pid, 1, repositorio=repo)
        segundo = control_acceso.registrar_con_credencial(pid, 1, repositorio=repo)
        assert len(repo.registros) == 1
        assert segundo.motivo == "evento_reciente_omitido"


# ===========================================================================
# 7. Validacion del reconocimiento facial
# ===========================================================================

class TestMetricasDelReconocimiento:
    def _filas(self):
        texto = (
            "documento_real,condicion,resultado,documento,distancia\n"
            "1001,luz,identificado,1001,0.40\n"
            "1001,luz,identificado,1001,0.42\n"
            "1001,gorra,no_identificado,,\n"
            "1002,luz,identificado,1001,0.58\n"
            "desconocido,luz,no_identificado,,\n"
            "desconocido,luz,identificado,1002,0.59\n"
        )
        return list(csv.DictReader(io.StringIO(texto)))

    def test_cuenta_cada_tipo_de_resultado(self):
        from scripts.evaluar_reconocimiento import evaluar

        g = evaluar(self._filas())["global"]
        assert g["aciertos"] == 2
        assert g["falsos_rechazos"] == 1
        assert g["falsas_aceptaciones"] == 2
        assert g["rechazos_correctos"] == 1
        assert g["precision"] == 0.5
        assert g["exhaustividad"] == round(2 / 3, 4)
        assert g["exactitud"] == 0.5

    def test_desglosa_por_condicion_y_compara_con_la_hipotesis(self):
        from scripts.evaluar_reconocimiento import evaluar

        informe = evaluar(self._filas())
        assert informe["por_condicion"]["gorra"]["falsos_rechazos"] == 1
        assert informe["cumple_hipotesis"] is False


# ===========================================================================
# 8. Base de datos de pruebas aislada
# ===========================================================================

class TestBaseDePruebasAislada:
    def test_rechaza_la_misma_base_de_la_aplicacion(self):
        from tests.bd_de_pruebas import motivo_de_rechazo

        url = "postgresql://u:c@db.supabase.co:5432/faceguard_test"
        assert "misma base" in motivo_de_rechazo(url, url)

    def test_rechaza_una_base_que_no_parece_desechable(self):
        from tests.bd_de_pruebas import motivo_de_rechazo

        assert motivo_de_rechazo("postgresql://u:c@db.supabase.co:5432/postgres")

    def test_acepta_una_base_de_pruebas(self):
        from tests.bd_de_pruebas import motivo_de_rechazo

        assert motivo_de_rechazo("postgresql://u:c@localhost/faceguard_test",
                                 "postgresql://u:c@db.supabase.co/postgres") is None
        assert motivo_de_rechazo("postgresql://u:c@localhost/base_de_pruebas") is None

    def test_salud_declara_el_entorno(self, client):
        assert client.get("/salud").get_json()["entorno"] == ConfigPrueba.APP_ENV
