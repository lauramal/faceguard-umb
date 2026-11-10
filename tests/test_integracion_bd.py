"""Pruebas de integracion de la capa de datos contra PostgreSQL real.

A diferencia del resto de la suite, estas pruebas no usan dobles: ejecutan el
script db/schema.sql sobre una base real y verifican que el repositorio y las
restricciones del esquema se comportan igual que lo que afirman los diagramas
y el documento.

Se omiten automaticamente si no hay una base disponible, de modo que la suite
sigue corriendo en cualquier equipo. Para ejecutarlas:

    export TEST_DATABASE_URL="postgresql://usuario:clave@host:5432/basedeprueba"
    pytest tests/test_integracion_bd.py
"""

from __future__ import annotations

import os
import pathlib

import numpy as np
import pytest

URL = os.getenv("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not URL, reason="TEST_DATABASE_URL no esta definida; se omite la integracion"
)

ESQUEMA = pathlib.Path(__file__).resolve().parents[1] / "db" / "schema.sql"


@pytest.fixture(scope="module")
def conexion():
    import psycopg2

    conn = psycopg2.connect(URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        cur.execute(ESQUEMA.read_text(encoding="utf-8"))
    yield conn
    conn.close()


@pytest.fixture
def repo(conexion, monkeypatch):
    """Apunta el repositorio real a la base de prueba."""
    from app import db, repositorio

    monkeypatch.setattr(db.Config, "DATABASE_URL", URL)
    db.cerrar_pool()
    db.inicializar_pool(URL)

    with conexion.cursor() as cur:
        cur.execute(
            "TRUNCATE auditoria, alerta_arma, registro_acceso, codificacion_facial,"
            " persona, camara, punto_acceso, usuario, institucion"
            " RESTART IDENTITY CASCADE"
        )
        cur.execute("INSERT INTO institucion (nombre) VALUES ('Institucion de prueba')")
        cur.execute("INSERT INTO punto_acceso (institucion_id, nombre) VALUES (1, 'Porteria')")
        cur.execute(
            "INSERT INTO camara (punto_acceso_id, identificador, resolucion_ancho,"
            " resolucion_alto) VALUES (1, 'CAM-01', 1280, 720)"
        )
    yield repositorio
    db.cerrar_pool()


def vector128(valor: float = 0.1) -> np.ndarray:
    return np.full(128, valor, dtype=np.float64)


class TestPersonasYBiometria:
    def test_crea_y_recupera_una_persona(self, repo):
        pid = repo.crear_persona(1, "1001", "docente", "Ana", "Ruiz",
                                 autoriza_biometria=True)
        persona = repo.obtener_persona(pid)
        assert persona["tipo_persona"] == "docente"
        assert persona["fecha_consentimiento"] is not None

    def test_sin_consentimiento_no_guarda_el_rostro(self, repo):
        pid = repo.crear_persona(1, "1002", "estudiante", "Luis", "Gomez",
                                 autoriza_biometria=False)
        with pytest.raises(PermissionError):
            repo.guardar_codificacion(pid, vector128())

    def test_el_enrolamiento_cambia_el_estado(self, repo):
        pid = repo.crear_persona(1, "1003", "estudiante", "Eva", "Paz",
                                 autoriza_biometria=True)
        repo.guardar_codificacion(pid, vector128())
        assert repo.obtener_persona(pid)["estado"] == "enrolado"

    def test_el_borrado_biometrico_conserva_el_historico(self, repo):
        pid = repo.crear_persona(1, "1004", "estudiante", "Iv", "Ortiz",
                                 autoriza_biometria=True)
        repo.guardar_codificacion(pid, vector128())
        repo.registrar_acceso(1, "ingreso", "identificado", persona_id=pid)
        assert repo.eliminar_codificaciones(pid) == 1
        assert len(repo.listar_accesos(persona_id=pid)) == 1

    def test_el_catalogo_solo_trae_a_quien_autorizo_y_esta_activo(self, repo):
        con = repo.crear_persona(1, "2001", "estudiante", "A", "A",
                                 autoriza_biometria=True)
        repo.guardar_codificacion(con, vector128(0.2))
        repo.actualizar_estado_persona(con, "activo")

        retirada = repo.crear_persona(1, "2002", "estudiante", "B", "B",
                                      autoriza_biometria=True)
        repo.guardar_codificacion(retirada, vector128(0.3))
        repo.actualizar_estado_persona(retirada, "retirado")

        ids = [c.persona_id for c in repo.cargar_catalogo()]
        assert con in ids and retirada not in ids


class TestRestriccionesDelEsquema:
    def test_el_evento_no_identificado_se_guarda(self, repo):
        rid = repo.registrar_acceso(1, "ingreso", "no_identificado",
                                    camara_id=1, imagen_url="s3://ev/1.jpg")
        assert rid is not None

    def test_identificado_sin_persona_es_rechazado_por_la_base(self, repo):
        """La restriccion vive en el esquema, no solo en Python."""
        import psycopg2

        from app.db import ejecutar

        with pytest.raises(psycopg2.errors.CheckViolation):
            ejecutar(
                "INSERT INTO registro_acceso (punto_acceso_id, tipo_evento, resultado)"
                " VALUES (1, 'ingreso', 'identificado')"
            )

    def test_el_vector_debe_medir_128(self, repo):
        import psycopg2

        from app.db import ejecutar

        pid = repo.crear_persona(1, "3001", "estudiante", "C", "C",
                                 autoriza_biometria=True)
        with pytest.raises(psycopg2.errors.CheckViolation):
            ejecutar(
                "INSERT INTO codificacion_facial (persona_id, vector)"
                " VALUES (%s, ARRAY[0.1,0.2]::float8[])",
                (pid,),
            )

    def test_el_documento_es_unico_por_institucion(self, repo):
        import psycopg2

        repo.crear_persona(1, "4001", "estudiante", "D", "D")
        with pytest.raises(psycopg2.errors.UniqueViolation):
            repo.crear_persona(1, "4001", "docente", "E", "E")


class TestAlertaUnidaALaPersona:
    """El aporte del trabajo: saber quien llevaba el arma."""

    def test_la_vista_responde_quien_portaba_el_arma(self, repo):
        pid = repo.crear_persona(1, "5001", "estudiante", "Sara", "Lopez",
                                 autoriza_biometria=True)
        repo.actualizar_estado_persona(pid, "activo")
        rid = repo.registrar_acceso(1, "ingreso", "identificado", persona_id=pid,
                                    camara_id=1, distancia=0.38, confianza=0.36)
        repo.crear_alerta(1, 1, "arma_blanca", 0.81,
                          registro_acceso_id=rid, persona_id=pid)

        alertas = repo.listar_alertas()
        assert alertas[0]["nombres"] == "Sara"
        assert alertas[0]["registro_acceso_id"] == rid

    def test_el_escalamiento_encuentra_las_pendientes(self, repo):
        from app.db import ejecutar

        aid = repo.crear_alerta(1, 1, "arma_fuego", 0.95)
        ejecutar(
            "UPDATE alerta_arma SET fecha_hora = NOW() - INTERVAL '30 minutes'"
            " WHERE id = %s",
            (aid,),
        )
        assert aid in [a["id"] for a in repo.alertas_sin_atender(5)]

    def test_tipo_de_arma_invalido_lo_rechaza_la_base(self, repo):
        import psycopg2

        from app.db import ejecutar

        with pytest.raises(psycopg2.errors.CheckViolation):
            ejecutar(
                "INSERT INTO alerta_arma (camara_id, punto_acceso_id, tipo_arma,"
                " confianza) VALUES (1, 1, 'sombrilla', 0.9)"
            )


class TestUsuariosYAuditoria:
    def test_bloquea_la_cuenta_al_llegar_al_maximo(self, repo):
        uid = repo.crear_usuario("G", "g@ejemplo.edu", "hash", 2)
        for _ in range(5):
            repo.registrar_intento_fallido(uid, 5)
        assert repo.obtener_usuario(uid)["estado"] == "bloqueado"

    def test_el_ingreso_exitoso_reinicia_el_contador(self, repo):
        uid = repo.crear_usuario("G2", "g2@ejemplo.edu", "hash", 2)
        repo.registrar_intento_fallido(uid, 5)
        repo.reiniciar_intentos(uid)
        assert repo.obtener_usuario(uid)["intentos_fallidos"] == 0

    def test_la_bitacora_guarda_y_recupera(self, repo):
        uid = repo.crear_usuario("A", "a@ejemplo.edu", "hash", 1)
        repo.registrar_auditoria(uid, "consulta_historial", "registro_acceso",
                                 None, "sin filtros", "127.0.0.1")
        assert repo.listar_auditoria()[0]["accion"] == "consulta_historial"

    def test_los_roles_iniciales_existen(self, repo):
        from app.db import consultar

        nombres = {r["nombre"] for r in consultar("SELECT nombre FROM rol")}
        assert {"administrador", "guardia", "consulta"} <= nombres


class TestReportes:
    def test_el_resumen_agrupa_por_resultado(self, repo):
        from datetime import datetime, timedelta

        pid = repo.crear_persona(1, "6001", "estudiante", "F", "F")
        repo.registrar_acceso(1, "ingreso", "identificado", persona_id=pid)
        repo.registrar_acceso(1, "ingreso", "no_identificado")

        resumen = repo.resumen_accesos(
            datetime.now() - timedelta(days=1), datetime.now() + timedelta(days=1)
        )
        totales = {f["resultado"]: f["total"] for f in resumen["accesos"]}
        assert totales["identificado"] == 1
        assert totales["no_identificado"] == 1
