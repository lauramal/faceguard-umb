"""Caja blanca del modulo de reconocimiento facial.

Cubre el criterio de aceptacion y rechazo segun el umbral, que es la primera
prueba que pide la asesoria.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.servicios.reconocimiento_facial import (
    UMBRAL_DISTANCIA, Candidato, confianza_desde_distancia, distancia,
    identificar, promediar_codificaciones,
)
from tests.ayudas import vector, vector_a_distancia


class TestDistancia:
    def test_vectores_identicos_distan_cero(self):
        assert distancia(vector(0.1), vector(0.1)) == pytest.approx(0.0)

    def test_distancia_construida_es_exacta(self):
        """El helper de pruebas produce la distancia que promete."""
        a, b = vector(0.0), vector_a_distancia(0.0, 0.45)
        assert distancia(a, b) == pytest.approx(0.45, abs=1e-9)


class TestUmbral:
    """La identidad se decide sobre la distancia, no sobre la confianza."""

    def _catalogo(self):
        return [Candidato(persona_id=7, vector=vector(0.0))]

    def test_acepta_rostro_tipico_de_la_misma_persona(self):
        """0.45 es una distancia normal entre dos fotos de alguien.

        Con el criterio anterior, que exigia confianza 0.85, este caso se
        rechazaba y el sistema no reconocia a nadie.
        """
        resultado = identificar(vector_a_distancia(0.0, 0.45), self._catalogo())
        assert resultado.identificado
        assert resultado.persona_id == 7

    def test_rechaza_rostro_de_otra_persona(self):
        resultado = identificar(vector_a_distancia(0.0, 0.85), self._catalogo())
        assert not resultado.identificado
        assert resultado.persona_id is None

    def test_justo_en_el_umbral_se_acepta(self):
        resultado = identificar(
            vector_a_distancia(0.0, UMBRAL_DISTANCIA - 1e-9), self._catalogo()
        )
        assert resultado.identificado

    def test_apenas_por_encima_del_umbral_se_rechaza(self):
        resultado = identificar(
            vector_a_distancia(0.0, UMBRAL_DISTANCIA + 1e-6), self._catalogo()
        )
        assert not resultado.identificado

    def test_umbral_mas_estricto_rechaza_lo_que_el_normal_acepta(self):
        candidato = vector_a_distancia(0.0, 0.45)
        assert identificar(candidato, self._catalogo()).identificado
        assert not identificar(
            candidato, self._catalogo(), umbral_distancia=0.30
        ).identificado

    def test_elige_el_candidato_mas_cercano(self):
        catalogo = [
            Candidato(persona_id=1, vector=vector_a_distancia(0.0, 0.50)),
            Candidato(persona_id=2, vector=vector_a_distancia(0.0, 0.20)),
        ]
        assert identificar(vector(0.0), catalogo).persona_id == 2

    def test_catalogo_vacio_no_identifica(self):
        resultado = identificar(vector(0.0), [])
        assert not resultado.identificado
        assert resultado.confianza == 0.0


class TestConfianza:
    """La confianza es informativa y deriva de la distancia."""

    def test_distancia_cero_da_confianza_uno(self):
        assert confianza_desde_distancia(0.0) == pytest.approx(1.0)

    def test_distancia_en_el_umbral_da_confianza_cero(self):
        assert confianza_desde_distancia(UMBRAL_DISTANCIA) == pytest.approx(0.0)

    def test_nunca_sale_del_rango_cero_uno(self):
        assert confianza_desde_distancia(5.0) == 0.0
        assert 0.0 <= confianza_desde_distancia(0.3) <= 1.0

    def test_umbral_invalido_falla(self):
        with pytest.raises(ValueError):
            confianza_desde_distancia(0.3, umbral=0)


class TestPromedio:
    def test_promedia_varias_capturas(self):
        promedio = promediar_codificaciones([vector(0.0), vector(1.0)])
        assert promedio == pytest.approx(np.full(128, 0.5))

    def test_lista_vacia_falla(self):
        with pytest.raises(ValueError):
            promediar_codificaciones([])

    def test_dimension_incorrecta_falla(self):
        with pytest.raises(ValueError):
            promediar_codificaciones([np.zeros(64)])


def test_codificacion_de_dimension_incorrecta_falla():
    with pytest.raises(ValueError):
        identificar(np.zeros(64), [Candidato(1, vector(0.0))])
