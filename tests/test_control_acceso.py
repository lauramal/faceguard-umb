"""Caja blanca del control de acceso.

Cubre tres pruebas de la asesoria: distinguir ingreso de salida, registrar a
las personas no identificadas y el ingreso con credencial de quien no
autoriza su rostro.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.config import Config
from app.servicios.control_acceso import (
    es_rebote, registrar_con_credencial, siguiente_evento,
)


class TestIngresoOSalida:
    """El sistema alterna el tipo de evento segun el ultimo registro."""

    def test_sin_registro_previo_es_ingreso(self):
        assert siguiente_evento(None) == "ingreso"

    def test_despues_de_un_ingreso_viene_una_salida(self):
        assert siguiente_evento("ingreso") == "salida"

    def test_despues_de_una_salida_viene_un_ingreso(self):
        assert siguiente_evento("salida") == "ingreso"

    def test_la_alternancia_se_sostiene_en_el_tiempo(self):
        tipo, secuencia = None, []
        for _ in range(4):
            tipo = siguiente_evento(tipo)
            secuencia.append(tipo)
        assert secuencia == ["ingreso", "salida", "ingreso", "salida"]


class TestAntirrebote:
    """Una persona parada frente a la camara no genera un registro por frame."""

    def test_evento_reciente_es_rebote(self):
        ultimo = {"fecha_hora": datetime.now() - timedelta(seconds=2),
                  "tipo_evento": "ingreso", "id": 1}
        assert es_rebote(ultimo)

    def test_evento_antiguo_no_es_rebote(self):
        ultimo = {"fecha_hora": datetime.now()
                  - timedelta(seconds=Config.VENTANA_ANTIREBOTE + 5),
                  "tipo_evento": "ingreso", "id": 1}
        assert not es_rebote(ultimo)

    def test_sin_registro_previo_no_es_rebote(self):
        assert not es_rebote(None)

    def test_el_limite_de_la_ventana_no_es_rebote(self):
        ultimo = {"fecha_hora": datetime.now()
                  - timedelta(seconds=Config.VENTANA_ANTIREBOTE),
                  "tipo_evento": "ingreso", "id": 1}
        assert not es_rebote(ultimo)


class TestEventosNoIdentificados:
    """El sistema no adivina, pero tampoco olvida."""

    def test_el_repositorio_guarda_el_evento_sin_persona(self, repo):
        rid = repo.registrar_acceso(
            punto_acceso_id=1, tipo_evento="ingreso",
            resultado="no_identificado", imagen_url="s3://ev/1.jpg",
        )
        assert rid is not None
        guardado = repo.listar_accesos(resultado="no_identificado")[0]
        assert guardado["persona_id"] is None
        assert guardado["imagen_url"] == "s3://ev/1.jpg"

    def test_no_se_puede_declarar_identificado_sin_persona(self, repo):
        with pytest.raises(ValueError):
            repo.registrar_acceso(
                punto_acceso_id=1, tipo_evento="ingreso", resultado="identificado"
            )

    def test_el_guardia_verifica_y_asocia_a_la_persona(self, repo):
        pid = repo.crear_persona(nombres="Ana", apellidos="Ruiz", estado="activo")
        rid = repo.registrar_acceso(
            punto_acceso_id=1, tipo_evento="ingreso", resultado="no_identificado"
        )
        assert repo.verificar_acceso_manual(rid, usuario_id=9,
                                            persona_id=pid, aprobado=True) == 1
        registro = repo.listar_accesos()[0]
        assert registro["resultado"] == "verificado_manual"
        assert registro["persona_id"] == pid
        assert registro["verificado_por"] == 9

    def test_no_se_verifica_dos_veces(self, repo):
        rid = repo.registrar_acceso(
            punto_acceso_id=1, tipo_evento="ingreso", resultado="no_identificado"
        )
        repo.verificar_acceso_manual(rid, 9, None, True)
        assert repo.verificar_acceso_manual(rid, 9, None, True) == 0


class TestIngresoConCredencial:
    """Quien no autoriza su rostro conserva el derecho a entrar."""

    def test_genera_el_mismo_registro_sin_biometria(self, repo):
        pid = repo.crear_persona(nombres="Luis", apellidos="Gomez",
                                 estado="activo", autoriza_biometria=False)
        resultado = registrar_con_credencial(pid, 1, repositorio=repo)

        assert resultado.identificado
        assert resultado.metodo == "credencial"
        assert resultado.tipo_evento == "ingreso"
        assert resultado.distancia is None

    def test_tambien_alterna_ingreso_y_salida(self, repo):
        pid = repo.crear_persona(estado="activo")
        repo.registrar_acceso(
            punto_acceso_id=1, persona_id=pid, tipo_evento="ingreso",
            resultado="identificado", metodo="credencial",
            fecha_hora=datetime.now() - timedelta(minutes=10),
        )
        resultado = registrar_con_credencial(pid, 1, repositorio=repo)
        assert resultado.tipo_evento == "salida"

    def test_persona_inexistente_no_registra(self, repo):
        resultado = registrar_con_credencial(999, 1, repositorio=repo)
        assert not resultado.identificado
        assert resultado.motivo == "persona_inexistente"
