"""Caja blanca de la maquina de estados de las alertas.

Cubre dos pruebas de la asesoria: que la alerta no se salte estados y que
suba al administrador cuando nadie la atiende.
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
                            confianza=0.82, registro_acceso_id=rid, persona_id=pid)
    return aid


class TestAporteDelTrabajo:
    """La alerta debe responder quien llevaba el arma, no solo donde estaba."""

    def test_la_alerta_conserva_persona_y_evento(self, repo, alerta):
        guardada = repo.obtener_alerta(alerta)
        assert guardada["persona_id"] is not None
        assert guardada["registro_acceso_id"] is not None

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
