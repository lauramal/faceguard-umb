"""Pruebas del modulo de reconocimiento facial.

Verifican la logica de comparacion sin depender de dlib ni de la camara, que
es lo que permite ejecutarlas en cualquier equipo y en integracion continua.
"""

import numpy as np
import pytest

from app.servicios.reconocimiento_facial import (
    DIMENSIONES,
    Candidato,
    confianza_desde_distancia,
    distancia,
    identificar,
    promediar_codificaciones,
)


def vector(semilla: int) -> np.ndarray:
    generador = np.random.default_rng(semilla)
    return generador.normal(0, 0.1, DIMENSIONES)


def test_distancia_de_un_vector_consigo_mismo_es_cero():
    v = vector(1)
    assert distancia(v, v) == pytest.approx(0.0)


def test_confianza_maxima_cuando_la_distancia_es_cero():
    assert confianza_desde_distancia(0.0) == pytest.approx(1.0)


def test_confianza_nula_cuando_se_alcanza_el_umbral():
    assert confianza_desde_distancia(0.6, umbral=0.6) == pytest.approx(0.0)


def test_confianza_nunca_es_negativa():
    assert confianza_desde_distancia(5.0, umbral=0.6) == 0.0


def test_identifica_al_estudiante_correcto():
    v = vector(7)
    catalogo = [
        Candidato(1, vector(3)),
        Candidato(2, v),
        Candidato(3, vector(5)),
    ]
    resultado = identificar(v, catalogo)

    assert resultado.identificado
    assert resultado.estudiante_id == 2
    assert resultado.confianza == pytest.approx(1.0)


def test_rechaza_un_rostro_desconocido():
    """Un rostro que no esta en el catalogo no debe identificarse.

    Es la prueba que sostiene el argumento del trabajo. El sistema prefiere
    devolver 'no identificado' y dejar la verificacion al guardia antes que
    asignar una identidad equivocada.
    """
    desconocido = np.ones(DIMENSIONES) * 0.9
    catalogo = [Candidato(1, vector(3)), Candidato(2, vector(4))]

    resultado = identificar(desconocido, catalogo)

    assert not resultado.identificado
    assert resultado.estudiante_id is None
    assert resultado.confianza < 0.85


def test_catalogo_vacio_no_identifica():
    resultado = identificar(vector(2), [])
    assert not resultado.identificado
    assert resultado.confianza == 0.0


def test_promedio_de_codificaciones():
    a = np.zeros(DIMENSIONES)
    b = np.ones(DIMENSIONES)
    promedio = promediar_codificaciones([a, b])

    assert promedio.shape == (DIMENSIONES,)
    assert np.allclose(promedio, 0.5)


def test_promedio_rechaza_lista_vacia():
    with pytest.raises(ValueError):
        promediar_codificaciones([])


def test_identificar_valida_la_dimension():
    with pytest.raises(ValueError):
        identificar(np.zeros(64), [Candidato(1, vector(1))])
