"""Caja blanca de la maquina de estados de las alertas.

Cubre las pruebas de la asesoria sobre las alertas: que no se salten estados,
que suban al administrador cuando nadie las atiende (sin que haga falta
invocar nada a mano), que una misma deteccion no genere alertas repetidas y
que la persona que aparece en el fotograma quede como contexto y no como
portadora del arma.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.servicios import alertas as servicio
from app.servicios.alertas import TransicionInvalida, transicion_valida


@pytest.fixture
def alerta(repo):
    """Alerta recien creada, unida a una persona y a su evento de acceso."""
    pid = repo.crear_persona(nombres="Ana", apellidos="Ruiz", estado="activo")
    rid = repo.registrar_acceso(punto_acceso_id=1, persona_id=pid,
                                tipo_evento="ingreso", resultado="identificado")
    aid = repo.crear_alerta(camara_id=1, punto_acceso_id=1, tipo_arma="arma_blanca",
                            confianza=0.82, registro_acceso_id=rid,
                            persona_contexto_id=pid)
    return aid


CAMARA = {"id": 1, "punto_acceso_id": 1}


class TestAporteDelTrabajo:
    """La alerta queda unida al evento de acceso y a su contexto."""

    def test_la_alerta_conserva_evento_y_contexto(self, repo, alerta):
        guardada = repo.obtener_alerta(alerta)
        assert guardada["persona_contexto_id"] is not None
        assert guardada["registro_acceso_id"] is not None

    def test_la_persona_del_fotograma_no_queda_como_portadora(self, repo, alerta):
        """Aparecer junto a un arma no prueba que se la porte."""
        assert repo.obtener_alerta(alerta)["portador_id"] is None

    def test_tipo_de_arma_invalido_se_rechaza(self, repo):
        with pytest.raises(ValueError):
            repo.crear_alerta(camara_id=1, punto_acceso_id=1,
                              tipo_arma="paraguas", confianza=0.9)


class TestTransiciones:
    """Una alerta no puede saltarse pasos de su ciclo de vida."""

    def test_el_camino_feliz_recorre_todos_los_estados(self, repo, alerta):
        servicio.notificar(alerta, repositorio=repo)
        assert repo.obtener_alerta(alerta)["estado"] == servicio.NOTIFICADA

        servicio.atender(alerta, usuario_id=5, repositorio=repo)
        assert repo.obtener_alerta(alerta)["estado"] == servicio.EN_ATENCION

        servicio.resolver(alerta, usuario_id=5, confirmada=True, repositorio=repo)
        assert repo.obtener_alerta(alerta)["estado"] == servicio.CERRADA

    def test_no_se_puede_cerrar_lo_que_nadie_atendio(self, repo, alerta):
        with pytest.raises(TransicionInvalida):
            servicio.cambiar_estado(alerta, servicio.CERRADA, repositorio=repo)

    def test_no_se_puede_atender_una_alerta_recien_generada(self, repo, alerta):
        """Primero hay que notificarla; atender salta un paso."""
        with pytest.raises(TransicionInvalida):
            servicio.atender(alerta, usuario_id=5, repositorio=repo)

    def test_no_se_puede_reabrir_una_alerta_cerrada(self, repo, alerta):
        servicio.notificar(alerta, repositorio=repo)
        servicio.atender(alerta, 5, repositorio=repo)
        servicio.resolver(alerta, 5, confirmada=False, repositorio=repo)
        with pytest.raises(TransicionInvalida):
            servicio.atender(alerta, 5, repositorio=repo)

    def test_atender_exige_saber_quien_atiende(self, repo, alerta):
        servicio.notificar(alerta, repositorio=repo)
        with pytest.raises(TransicionInvalida):
            servicio.cambiar_estado(alerta, servicio.EN_ATENCION, repositorio=repo)

    def test_estado_inexistente_se_rechaza(self, repo, alerta):
        with pytest.raises(TransicionInvalida):
            servicio.cambiar_estado(alerta, "inventado", repositorio=repo)

    def test_alerta_inexistente_se_rechaza(self, repo):
        with pytest.raises(TransicionInvalida):
            servicio.notificar(999, repositorio=repo)

    @pytest.mark.parametrize("origen,destino,esperado", [
        (servicio.GENERADA, servicio.NOTIFICADA, True),
        (servicio.GENERADA, servicio.CERRADA, False),
        (servicio.NOTIFICADA, servicio.ESCALADA, True),
        (servicio.ESCALADA, servicio.EN_ATENCION, True),
        (servicio.EN_ATENCION, servicio.CONFIRMADA, True),
        (servicio.EN_ATENCION, servicio.NOTIFICADA, False),
        (servicio.CERRADA, servicio.EN_ATENCION, False),
    ])
    def test_mapa_de_transiciones(self, origen, destino, esperado):
        assert transicion_valida(origen, destino) is esperado


class TestEscalamiento:
    """Si nadie atiende la alerta, sube al administrador."""

    def _alerta_vieja(self, repo, minutos):
        return repo.crear_alerta(
            camara_id=1, punto_acceso_id=1, tipo_arma="arma_fuego", confianza=0.9,
            fecha_hora=datetime.now() - timedelta(minutes=minutos),
        )

    def test_escala_la_alerta_que_nadie_tomo(self, repo):
        aid = self._alerta_vieja(repo, minutos=30)
        escaladas = servicio.escalar_pendientes(repositorio=repo, minutos=5)
        assert aid in escaladas
        assert repo.obtener_alerta(aid)["estado"] == servicio.ESCALADA
        assert repo.obtener_alerta(aid)["fecha_escalamiento"] is not None

    def test_no_escala_una_alerta_reciente(self, repo):
        aid = self._alerta_vieja(repo, minutos=1)
        assert servicio.escalar_pendientes(repositorio=repo, minutos=5) == []
        assert repo.obtener_alerta(aid)["estado"] == servicio.GENERADA

    def test_no_escala_una_alerta_ya_atendida(self, repo):
        aid = self._alerta_vieja(repo, minutos=30)
        servicio.notificar(aid, repositorio=repo)
        servicio.atender(aid, usuario_id=5, repositorio=repo)
        assert servicio.escalar_pendientes(repositorio=repo, minutos=5) == []

    def test_el_administrador_puede_tomar_la_escalada(self, repo):
        aid = self._alerta_vieja(repo, minutos=30)
        servicio.escalar_pendientes(repositorio=repo, minutos=5)
        servicio.atender(aid, usuario_id=1, repositorio=repo)
        assert repo.obtener_alerta(aid)["estado"] == servicio.EN_ATENCION
        assert repo.obtener_alerta(aid)["atendida_por"] == 1


class TestPortador:
    """Solo el guardia, al confirmar con la evidencia, atribuye el arma."""

    def _en_atencion(self, repo, alerta):
        servicio.notificar(alerta, repositorio=repo)
        servicio.atender(alerta, usuario_id=5, repositorio=repo)

    def test_al_confirmar_el_guardia_indica_el_portador(self, repo, alerta):
        self._en_atencion(repo, alerta)
        pid = repo.obtener_alerta(alerta)["persona_contexto_id"]
        resultado = servicio.resolver(alerta, 5, confirmada=True,
                                      repositorio=repo, portador_id=pid)
        assert resultado["desenlace"] == servicio.CONFIRMADA
        assert repo.obtener_alerta(alerta)["portador_id"] == pid

    def test_confirmar_sin_portador_es_valido(self, repo, alerta):
        """El arma puede ser real sin que se sepa todavia quien la lleva."""
        self._en_atencion(repo, alerta)
        servicio.resolver(alerta, 5, confirmada=True, repositorio=repo)
        assert repo.obtener_alerta(alerta)["portador_id"] is None

    def test_un_falso_positivo_no_admite_portador(self, repo, alerta):
        self._en_atencion(repo, alerta)
        pid = repo.obtener_alerta(alerta)["persona_contexto_id"]
        with pytest.raises(TransicionInvalida):
            servicio.resolver(alerta, 5, confirmada=False, repositorio=repo,
                              portador_id=pid)
        assert repo.obtener_alerta(alerta)["estado"] == servicio.EN_ATENCION

    def test_portador_inexistente_se_rechaza(self, repo, alerta):
        self._en_atencion(repo, alerta)
        with pytest.raises(TransicionInvalida):
            servicio.resolver(alerta, 5, confirmada=True, repositorio=repo,
                              portador_id=999)


class TestDeteccionesRepetidas:
    """Una misma arma frente a la camara no abre una alerta por fotograma."""

    def test_la_segunda_deteccion_se_suma_a_la_primera(self, repo):
        primera = servicio.registrar_deteccion(CAMARA, "arma_fuego", 0.81, repositorio=repo)
        segunda = servicio.registrar_deteccion(CAMARA, "arma_fuego", 0.90, repositorio=repo)
        assert primera["duplicada"] is False
        assert segunda["duplicada"] is True
        assert segunda["id"] == primera["id"]
        assert len(repo.alertas) == 1
        guardada = repo.obtener_alerta(primera["id"])
        assert guardada["detecciones"] == 2
        assert guardada["confianza"] == 0.90

    def test_otro_tipo_de_arma_si_abre_otra_alerta(self, repo):
        servicio.registrar_deteccion(CAMARA, "arma_fuego", 0.8, repositorio=repo)
        servicio.registrar_deteccion(CAMARA, "arma_blanca", 0.8, repositorio=repo)
        assert len(repo.alertas) == 2

    def test_una_alerta_cerrada_no_absorbe_detecciones_nuevas(self, repo):
        primera = servicio.registrar_deteccion(CAMARA, "arma_fuego", 0.8, repositorio=repo)
        servicio.atender(primera["id"], 5, repositorio=repo)
        servicio.resolver(primera["id"], 5, confirmada=False, repositorio=repo)
        nueva = servicio.registrar_deteccion(CAMARA, "arma_fuego", 0.8, repositorio=repo)
        assert nueva["duplicada"] is False
        assert nueva["id"] != primera["id"]

    def test_pasada_la_ventana_se_abre_otra(self, repo, monkeypatch):
        from app.config import Config

        primera = servicio.registrar_deteccion(CAMARA, "arma_fuego", 0.8, repositorio=repo)
        repo.alertas[primera["id"]]["ultima_deteccion"] -= timedelta(
            seconds=Config.VENTANA_ALERTA + 5)
        nueva = servicio.registrar_deteccion(CAMARA, "arma_fuego", 0.8, repositorio=repo)
        assert nueva["duplicada"] is False


class TestContexto:
    """La persona del evento se toma como contexto solo si es inequivoca."""

    def _evento(self, repo, punto=1, hace_segundos=0):
        pid = repo.crear_persona(nombres="Ana", apellidos="Ruiz", estado="activo")
        rid = repo.registrar_acceso(
            punto_acceso_id=punto, persona_id=pid, tipo_evento="ingreso",
            resultado="identificado",
            fecha_hora=datetime.now() - timedelta(seconds=hace_segundos),
        )
        return pid, rid

    def test_un_solo_rostro_queda_como_contexto(self, repo):
        pid, rid = self._evento(repo)
        r = servicio.registrar_deteccion(CAMARA, "arma_blanca", 0.8, registro_acceso_id=rid,
                                         rostros_en_escena=1, repositorio=repo)
        assert r["persona_contexto_id"] == pid
        assert repo.obtener_alerta(r["id"])["portador_id"] is None

    def test_con_varios_rostros_no_se_atribuye_contexto(self, repo):
        _, rid = self._evento(repo)
        r = servicio.registrar_deteccion(CAMARA, "arma_blanca", 0.8, registro_acceso_id=rid,
                                         rostros_en_escena=3, repositorio=repo)
        assert r["persona_contexto_id"] is None
        assert repo.obtener_alerta(r["id"])["registro_acceso_id"] == rid

    def test_un_evento_de_otro_punto_se_ignora(self, repo):
        _, rid = self._evento(repo, punto=2)
        r = servicio.registrar_deteccion(CAMARA, "arma_blanca", 0.8, registro_acceso_id=rid,
                                         repositorio=repo)
        assert r["persona_contexto_id"] is None
        assert repo.obtener_alerta(r["id"])["registro_acceso_id"] is None

    def test_un_evento_viejo_se_ignora(self, repo):
        _, rid = self._evento(repo, hace_segundos=servicio.SEGUNDOS_CONTEXTO + 30)
        r = servicio.registrar_deteccion(CAMARA, "arma_blanca", 0.8, registro_acceso_id=rid,
                                         repositorio=repo)
        assert r["persona_contexto_id"] is None


class TestEvidencia:
    def test_la_imagen_queda_guardada_con_la_alerta(self, repo):
        guardadas = {}

        class Almacen:
            @staticmethod
            def guardar(alerta_id, datos):
                guardadas[alerta_id] = datos
                return f"local:alertas/{alerta_id}.jpg"

        r = servicio.registrar_deteccion(CAMARA, "arma_fuego", 0.9, imagen=b"jpeg",
                                         repositorio=repo, evidencias=Almacen)
        assert guardadas[r["id"]] == b"jpeg"
        assert repo.obtener_alerta(r["id"])["imagen_url"] == f"local:alertas/{r['id']}.jpg"

    def test_si_la_imagen_falla_la_alerta_se_crea_igual(self, repo):
        class AlmacenRoto:
            @staticmethod
            def guardar(alerta_id, datos):
                raise OSError("disco lleno")

        r = servicio.registrar_deteccion(CAMARA, "arma_fuego", 0.9, imagen=b"x",
                                         repositorio=repo, evidencias=AlmacenRoto)
        assert repo.obtener_alerta(r["id"])["estado"] == servicio.NOTIFICADA


class TestEscalamientoAutomatico:
    """El escalamiento corre solo, sin que alguien invoque un endpoint."""

    def test_la_revision_de_fondo_escala_lo_pendiente(self, repo, monkeypatch):
        from flask import Flask

        from app import repositorio as repo_real
        from app.servicios import tareas

        for nombre in ("alertas_sin_atender", "obtener_alerta", "actualizar_estado_alerta"):
            monkeypatch.setattr(repo_real, nombre, getattr(repo, nombre))
        aid = repo.crear_alerta(camara_id=1, punto_acceso_id=1, tipo_arma="arma_fuego",
                                confianza=0.9, fecha_hora=datetime.now() - timedelta(hours=1))
        assert tareas.revisar_escalamiento(Flask("prueba")) == [aid]
        assert repo.obtener_alerta(aid)["estado"] == servicio.ESCALADA

    def test_el_hilo_arranca_y_escala_sin_intervencion(self, repo, monkeypatch):
        import time

        from flask import Flask

        from app import repositorio as repo_real
        from app.servicios import tareas

        for nombre in ("alertas_sin_atender", "obtener_alerta", "actualizar_estado_alerta"):
            monkeypatch.setattr(repo_real, nombre, getattr(repo, nombre))
        aid = repo.crear_alerta(camara_id=1, punto_acceso_id=1, tipo_arma="arma_fuego",
                                confianza=0.9, fecha_hora=datetime.now() - timedelta(hours=1))
        tareas.iniciar_escalamiento_automatico(Flask("prueba"), segundos=0.05)
        try:
            for _ in range(60):
                if repo.alertas[aid]["estado"] == servicio.ESCALADA:
                    break
                time.sleep(0.05)
        finally:
            tareas.detener_escalamiento_automatico()
        assert repo.alertas[aid]["estado"] == servicio.ESCALADA

    def test_una_falla_no_detiene_la_tarea(self, monkeypatch):
        from flask import Flask

        from app.servicios import tareas

        def falla(*a, **k):
            raise RuntimeError("base caida")

        monkeypatch.setattr(servicio, "escalar_pendientes", falla)
        assert tareas.revisar_escalamiento(Flask("prueba")) == []
