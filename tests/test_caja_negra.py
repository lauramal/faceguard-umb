"""Pruebas de caja negra: el sistema visto desde afuera.

A diferencia de la caja blanca, estas pruebas no conocen el codigo por dentro.
Hablan con la aplicacion por HTTP, como lo haria la estacion de captura o una
persona desde el navegador, y solo miran lo que el sistema responde.

Cubren las nueve pruebas que pide la asesoria, salvo las tres que exigen
presencia fisica (arma de juguete frente a la camara, objetos cotidianos y el
cuestionario SUS). Esas quedan documentadas en docs/pruebas_caja_negra.md
como protocolo manual.

Como ejecutarlas
----------------
Contra un servidor que ya este corriendo:

    export FACEGUARD_URL=https://su-servidor.onrender.com
    export TEST_DATABASE_URL=postgresql://...     # para sembrar los datos
    pytest tests/test_caja_negra.py --no-cov

Si no se define FACEGUARD_URL, la suite levanta la aplicacion en un hilo y la
prueba en local, de modo que tambien corre sin despliegue.
"""

from __future__ import annotations

import os
import pathlib
import threading
import time
from datetime import datetime, timedelta
from wsgiref.simple_server import WSGIRequestHandler, make_server

import numpy as np
import pytest

URL_EXTERNA = os.getenv("FACEGUARD_URL", "").rstrip("/")
URL_BD = os.getenv("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not URL_BD,
    reason="TEST_DATABASE_URL no esta definida; se omite la caja negra",
)

ESQUEMA = pathlib.Path(__file__).resolve().parents[1] / "db" / "schema.sql"

CLAVE_ADMIN = "Clave-Admin-2026"
CLAVE_GUARDIA = "Clave-Guardia-2026"


def codificacion(valor: float = 0.0) -> list[float]:
    """Vector de 128 dimensiones, como el que envia la estacion de captura."""
    return np.full(128, valor, dtype=np.float64).tolist()


def codificacion_lejana(distancia_objetivo: float) -> list[float]:
    delta = distancia_objetivo / np.sqrt(128)
    return np.full(128, delta, dtype=np.float64).tolist()


class _HandlerSilencioso(WSGIRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def servidor():
    """Devuelve la URL base. Externa si se indico, o una local efimera."""
    if URL_EXTERNA:
        yield URL_EXTERNA
        return

    os.environ["DATABASE_URL"] = URL_BD
    from app import crear_app, db
    from app.config import Config

    class ConfigLocal(Config):
        DATABASE_URL = URL_BD
        SECRET_KEY = "clave-de-caja-negra"

    # El pool lee Config del modulo db, no la configuracion de la app.
    db.Config.DATABASE_URL = URL_BD
    db.cerrar_pool()
    db.inicializar_pool(URL_BD)

    aplicacion = crear_app(ConfigLocal)
    httpd = make_server("127.0.0.1", 0, aplicacion, handler_class=_HandlerSilencioso)
    hilo = threading.Thread(target=httpd.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    db.cerrar_pool()


@pytest.fixture(scope="module")
def datos(servidor):
    """Siembra una institucion, un punto de acceso, usuarios y personas."""
    import psycopg2
    from werkzeug.security import generate_password_hash

    conn = psycopg2.connect(URL_BD)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        cur.execute(ESQUEMA.read_text(encoding="utf-8"))
        cur.execute("INSERT INTO institucion (nombre) VALUES ('Institucion de prueba')")
        cur.execute("INSERT INTO punto_acceso (institucion_id, nombre) VALUES (1,'Porteria')")
        cur.execute(
            "INSERT INTO camara (punto_acceso_id, identificador, resolucion_ancho,"
            " resolucion_alto) VALUES (1,'CAM-01',1280,720)"
        )
        for nombre, correo, clave, rol in (
            ("Admin", "admin@prueba.edu", CLAVE_ADMIN, "administrador"),
            ("Guardia", "guardia@prueba.edu", CLAVE_GUARDIA, "guardia"),
            ("Consulta", "consulta@prueba.edu", CLAVE_GUARDIA, "consulta"),
        ):
            cur.execute(
                "INSERT INTO usuario (nombre, correo, contrasena_hash, rol_id, estado)"
                " SELECT %s,%s,%s,id,'activo' FROM rol WHERE nombre=%s",
                (nombre, correo, generate_password_hash(clave), rol),
            )
        # Persona enrolada, con su codificacion en el origen del espacio
        cur.execute(
            "INSERT INTO persona (institucion_id, documento, tipo_persona, nombres,"
            " apellidos, estado, autoriza_biometria, fecha_consentimiento)"
            " VALUES (1,'1001','estudiante','Ana','Ruiz','activo',TRUE,NOW())"
            " RETURNING id"
        )
        persona_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO codificacion_facial (persona_id, vector)"
            " VALUES (%s, (SELECT array_agg(0.0::float8) FROM generate_series(1,128)))",
            (persona_id,),
        )
        # Persona que no autorizo biometria
        cur.execute(
            "INSERT INTO persona (institucion_id, documento, tipo_persona, nombres,"
            " apellidos, estado, autoriza_biometria)"
            " VALUES (1,'1002','docente','Luis','Gomez','activo',FALSE) RETURNING id"
        )
        sin_biometria = cur.fetchone()[0]
    yield {"persona_id": persona_id, "sin_biometria": sin_biometria, "conn": conn}
    conn.close()


@pytest.fixture
def sesion():
    import requests

    return requests.Session()


def entrar(sesion, base, correo, clave):
    respuesta = sesion.post(f"{base}/api/auth/login",
                            json={"correo": correo, "contrasena": clave}, timeout=15)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


# ===========================================================================
# 1. Una persona registrada pasa frente a la camara y queda registrada
# ===========================================================================

class TestPersonaRegistrada:
    def test_queda_registrada_como_ingreso(self, servidor, datos, sesion):
        respuesta = sesion.post(f"{servidor}/api/accesos/evento", json={
            "codificacion": codificacion(0.0),
            "punto_acceso_id": 1, "camara_id": 1,
        }, timeout=20)
        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["identificado"] is True
        assert cuerpo["persona_id"] == datos["persona_id"]
        assert cuerpo["tipo_evento"] == "ingreso"
        assert cuerpo["registro_id"] is not None

    def test_aparece_en_el_historial(self, servidor, datos, sesion):
        entrar(sesion, servidor, "guardia@prueba.edu", CLAVE_GUARDIA)
        registros = sesion.get(
            f"{servidor}/api/accesos", params={"persona_id": datos["persona_id"]},
            timeout=15,
        ).json()["registros"]
        assert registros
        assert registros[0]["nombres"] == "Ana"

    def test_la_segunda_pasada_es_salida(self, servidor, datos):
        """Tras agotar la ventana antirrebote el evento alterna."""
        import requests

        with datos["conn"].cursor() as cur:
            cur.execute(
                "UPDATE registro_acceso SET fecha_hora = NOW() - INTERVAL '1 hour'"
                " WHERE persona_id = %s", (datos["persona_id"],)
            )
        respuesta = requests.post(f"{servidor}/api/accesos/evento", json={
            "codificacion": codificacion(0.0), "punto_acceso_id": 1,
        }, timeout=20)
        assert respuesta.json()["tipo_evento"] == "salida"


# ===========================================================================
# 2. Pasa alguien que no esta registrado y le avisa al guardia
# ===========================================================================

class TestPersonaDesconocida:
    def test_no_la_identifica_pero_guarda_el_evento(self, servidor, datos):
        import requests

        respuesta = requests.post(f"{servidor}/api/accesos/evento", json={
            "codificacion": codificacion_lejana(0.95),
            "punto_acceso_id": 1, "camara_id": 1,
            "imagen_url": "s3://evidencias/desconocido.jpg",
        }, timeout=20)
        cuerpo = respuesta.json()
        assert cuerpo["identificado"] is False
        assert cuerpo["resultado"] == "no_identificado"
        assert cuerpo["registro_id"] is not None
        assert cuerpo["motivo"] == "requiere_verificacion_manual"

    def test_el_guardia_lo_ve_pendiente(self, servidor, sesion):
        entrar(sesion, servidor, "guardia@prueba.edu", CLAVE_GUARDIA)
        pendientes = sesion.get(f"{servidor}/api/accesos",
                                params={"resultado": "no_identificado"},
                                timeout=15).json()["registros"]
        assert pendientes, "el guardia deberia ver el evento sin identificar"

    def test_el_guardia_lo_verifica(self, servidor, datos, sesion):
        entrar(sesion, servidor, "guardia@prueba.edu", CLAVE_GUARDIA)
        pendientes = sesion.get(f"{servidor}/api/accesos",
                                params={"resultado": "no_identificado"},
                                timeout=15).json()["registros"]
        registro_id = pendientes[0]["id"]
        respuesta = sesion.post(f"{servidor}/api/accesos/{registro_id}/verificar",
                                json={"aprobado": True}, timeout=15)
        assert respuesta.status_code == 200
        assert respuesta.json()["resultado"] == "verificado_manual"


# ===========================================================================
# 3. Alerta de arma: el sistema la recibe, la notifica y la une a la persona
# ===========================================================================

class TestAlertaDeArma:
    def test_la_alerta_se_crea_y_se_notifica(self, servidor, datos):
        import requests

        registro = requests.post(f"{servidor}/api/accesos/evento", json={
            "codificacion": codificacion(0.0), "punto_acceso_id": 1, "camara_id": 1,
        }, timeout=20).json()

        respuesta = requests.post(f"{servidor}/api/alertas", json={
            "camara_id": 1, "punto_acceso_id": 1, "tipo_arma": "arma_blanca",
            "confianza": 0.84, "registro_acceso_id": registro["registro_id"],
            "persona_id": datos["persona_id"],
        }, timeout=15)
        assert respuesta.status_code == 201
        assert respuesta.json()["estado"] == "notificada"

    def test_la_alerta_dice_quien_llevaba_el_arma(self, servidor, datos, sesion):
        entrar(sesion, servidor, "guardia@prueba.edu", CLAVE_GUARDIA)
        alertas = sesion.get(f"{servidor}/api/alertas", timeout=15).json()["alertas"]
        assert alertas
        assert alertas[0]["nombres"] == "Ana", "la alerta debe identificar a la persona"

    def test_un_objeto_que_no_es_arma_no_se_acepta(self, servidor):
        """El sistema solo admite los tipos de arma de su vocabulario."""
        import requests

        respuesta = requests.post(f"{servidor}/api/alertas", json={
            "camara_id": 1, "punto_acceso_id": 1, "tipo_arma": "sombrilla",
            "confianza": 0.97,
        }, timeout=15)
        assert respuesta.status_code == 400


# ===========================================================================
# 5. Un usuario sin permiso intenta atender una alerta y no lo deja
# ===========================================================================

class TestPermisos:
    def test_el_rol_consulta_no_atiende_alertas(self, servidor, sesion):
        entrar(sesion, servidor, "consulta@prueba.edu", CLAVE_GUARDIA)
        alertas = sesion.get(f"{servidor}/api/alertas", timeout=15).json()["alertas"]
        respuesta = sesion.post(
            f"{servidor}/api/alertas/{alertas[0]['alerta_id']}/atender", timeout=15
        )
        assert respuesta.status_code == 403

    def test_sin_sesion_no_se_ve_el_historial(self, servidor):
        import requests

        assert requests.get(f"{servidor}/api/accesos", timeout=15).status_code == 401

    def test_el_guardia_no_gestiona_usuarios(self, servidor, sesion):
        entrar(sesion, servidor, "guardia@prueba.edu", CLAVE_GUARDIA)
        assert sesion.get(f"{servidor}/api/usuarios", timeout=15).status_code == 403

    def test_el_guardia_si_atiende_alertas(self, servidor, sesion):
        entrar(sesion, servidor, "guardia@prueba.edu", CLAVE_GUARDIA)
        alertas = sesion.get(f"{servidor}/api/alertas", timeout=15).json()["alertas"]
        respuesta = sesion.post(
            f"{servidor}/api/alertas/{alertas[0]['alerta_id']}/atender", timeout=15
        )
        assert respuesta.status_code == 200


# ===========================================================================
# 6. Te equivocas varias veces con la contrasena y bloquea la cuenta
# ===========================================================================

class TestBloqueoDeCuenta:
    def test_la_cuenta_se_bloquea_y_no_entra_ni_con_la_clave_buena(self, servidor, datos):
        import requests

        from app.config import Config

        with datos["conn"].cursor() as cur:
            cur.execute(
                "INSERT INTO usuario (nombre, correo, contrasena_hash, rol_id, estado)"
                " SELECT 'Victima','victima@prueba.edu',"
                " (SELECT contrasena_hash FROM usuario WHERE correo='guardia@prueba.edu'),"
                " id,'activo' FROM rol WHERE nombre='guardia'"
            )

        for _ in range(Config.MAX_INTENTOS_FALLIDOS):
            requests.post(f"{servidor}/api/auth/login", json={
                "correo": "victima@prueba.edu", "contrasena": "equivocada",
            }, timeout=15)

        respuesta = requests.post(f"{servidor}/api/auth/login", json={
            "correo": "victima@prueba.edu", "contrasena": CLAVE_GUARDIA,
        }, timeout=15)
        assert respuesta.status_code == 401, "la cuenta deberia estar bloqueada"

        with datos["conn"].cursor() as cur:
            cur.execute("SELECT estado FROM usuario WHERE correo='victima@prueba.edu'")
            assert cur.fetchone()[0] == "bloqueado"

    def test_el_administrador_la_desbloquea(self, servidor, datos, sesion):
        entrar(sesion, servidor, "admin@prueba.edu", CLAVE_ADMIN)
        with datos["conn"].cursor() as cur:
            cur.execute("SELECT id FROM usuario WHERE correo='victima@prueba.edu'")
            uid = cur.fetchone()[0]

        assert sesion.patch(f"{servidor}/api/usuarios/{uid}/estado",
                            json={"estado": "activo"}, timeout=15).status_code == 200

        import requests
        assert requests.post(f"{servidor}/api/auth/login", json={
            "correo": "victima@prueba.edu", "contrasena": CLAVE_GUARDIA,
        }, timeout=15).status_code == 200


# ===========================================================================
# 7. Exportas un reporte y sale bien
# ===========================================================================

class TestReportes:
    def test_el_resumen_responde(self, servidor, sesion):
        entrar(sesion, servidor, "admin@prueba.edu", CLAVE_ADMIN)
        respuesta = sesion.get(f"{servidor}/api/reportes/resumen", timeout=20)
        assert respuesta.status_code == 200
        assert "accesos" in respuesta.json()

    def test_el_csv_se_descarga_con_datos(self, servidor, sesion):
        entrar(sesion, servidor, "admin@prueba.edu", CLAVE_ADMIN)
        respuesta = sesion.get(f"{servidor}/api/reportes/accesos.csv", timeout=20)
        assert respuesta.status_code == 200
        assert "text/csv" in respuesta.headers["Content-Type"]

        lineas = respuesta.text.strip().splitlines()
        assert "tipo_evento" in lineas[0], "debe traer encabezados"
        assert len(lineas) > 1, "debe traer al menos una fila"

    def test_el_guardia_no_exporta_reportes(self, servidor, sesion):
        entrar(sesion, servidor, "guardia@prueba.edu", CLAVE_GUARDIA)
        assert sesion.get(f"{servidor}/api/reportes/accesos.csv",
                          timeout=15).status_code == 403


# ===========================================================================
# Escalamiento: la alerta sube al administrador si nadie la atiende
# ===========================================================================

class TestEscalamiento:
    def test_la_alerta_abandonada_sube_al_administrador(self, servidor, datos, sesion):
        import requests

        creada = requests.post(f"{servidor}/api/alertas", json={
            "camara_id": 1, "punto_acceso_id": 1, "tipo_arma": "arma_fuego",
            "confianza": 0.93,
        }, timeout=15).json()

        with datos["conn"].cursor() as cur:
            cur.execute(
                "UPDATE alerta_arma SET fecha_hora = NOW() - INTERVAL '45 minutes'"
                " WHERE id = %s", (creada["id"],)
            )

        entrar(sesion, servidor, "admin@prueba.edu", CLAVE_ADMIN)
        respuesta = sesion.post(f"{servidor}/api/alertas/escalar", timeout=20)
        assert respuesta.status_code == 200
        assert creada["id"] in respuesta.json()["escaladas"]

        with datos["conn"].cursor() as cur:
            cur.execute("SELECT estado FROM alerta_arma WHERE id=%s", (creada["id"],))
            assert cur.fetchone()[0] == "escalada"


# ===========================================================================
# 8. Tiempos de respuesta (RNF-01)
# ===========================================================================

class TestTiempos:
    def test_la_identificacion_responde_en_menos_de_tres_segundos(self, servidor):
        """RNF-01. Se mide la respuesta completa del servidor, no solo el calculo."""
        import requests

        medidas = []
        for _ in range(5):
            inicio = time.perf_counter()
            requests.post(f"{servidor}/api/accesos/evento", json={
                "codificacion": codificacion(0.0), "punto_acceso_id": 1,
            }, timeout=30)
            medidas.append(time.perf_counter() - inicio)

        mediana = sorted(medidas)[len(medidas) // 2]
        print(f"\n  mediana: {mediana * 1000:.0f} ms | "
              f"maximo: {max(medidas) * 1000:.0f} ms")
        assert mediana < 3.0, f"RNF-01 incumplido: {mediana:.2f} s"


# ===========================================================================
# Ingreso con credencial de quien no autoriza su rostro
# ===========================================================================

class TestIngresoConCredencial:
    def test_quien_no_autorizo_entra_con_credencial(self, servidor, datos, sesion):
        entrar(sesion, servidor, "guardia@prueba.edu", CLAVE_GUARDIA)
        respuesta = sesion.post(f"{servidor}/api/accesos/credencial", json={
            "persona_id": datos["sin_biometria"], "punto_acceso_id": 1,
        }, timeout=15)
        assert respuesta.status_code == 201
        cuerpo = respuesta.json()
        assert cuerpo["metodo"] == "credencial"
        assert cuerpo["identificado"] is True

    def test_su_ingreso_queda_en_el_mismo_historial(self, servidor, datos, sesion):
        entrar(sesion, servidor, "guardia@prueba.edu", CLAVE_GUARDIA)
        registros = sesion.get(f"{servidor}/api/accesos",
                               params={"persona_id": datos["sin_biometria"]},
                               timeout=15).json()["registros"]
        assert registros
        assert registros[0]["metodo"] == "credencial"


# ===========================================================================
# La bitacora registra lo que ocurre
# ===========================================================================

class TestAuditoria:
    def test_las_consultas_quedan_en_la_bitacora(self, servidor, sesion):
        entrar(sesion, servidor, "admin@prueba.edu", CLAVE_ADMIN)
        sesion.get(f"{servidor}/api/accesos", timeout=15)
        registros = sesion.get(f"{servidor}/api/usuarios/auditoria",
                               timeout=15).json()["registros"]
        acciones = {r["accion"] for r in registros}
        assert "consulta_historial" in acciones
        assert "login_exitoso" in acciones
