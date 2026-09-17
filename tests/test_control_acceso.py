"""Pruebas del proceso P2, registro de ingreso y salida.

Se usa un repositorio falso en memoria y se sustituye la codificacion del
rostro, de modo que la prueba ejercita la logica de decision del servicio sin
camara ni base de datos.
"""

import numpy as np
import pytest

from app.servicios import control_acceso
from app.servicios.control_acceso import _siguiente_evento, procesar_fotograma
from app.servicios.reconocimiento_facial import DIMENSIONES, Candidato, RostroNoDetectado


class RepositorioFalso:
    def __init__(self, catalogo, estudiantes, ultimo=None):
        self._catalogo = catalogo
        self._estudiantes = estudiantes
        self._ultimo = ultimo
        self.registros = []

    def cargar_catalogo(self):
        return self._catalogo

    def obtener_estudiante(self, estudiante_id):
        return self._estudiantes.get(estudiante_id)

    def ultimo_evento(self, estudiante_id):
        return self._ultimo

    def registrar_acceso(self, estudiante_id, punto_acceso_id, tipo_evento, confianza):
        self.registros.append(
            {
                "estudiante_id": estudiante_id,
                "punto_acceso_id": punto_acceso_id,
                "tipo_evento": tipo_evento,
                "confianza": confianza,
            }
        )
        return len(self.registros)


ROSTRO = np.linspace(0, 1, DIMENSIONES)

ESTUDIANTES = {
    1: {"id": 1, "nombres": "Laura Valentina", "apellidos": "Maldonado Perez"},
}


@pytest.fixture
def rostro_conocido(monkeypatch):
    monkeypatch.setattr(control_acceso, "codificar_rostro", lambda img, estricto=True: ROSTRO)


def test_primer_evento_es_ingreso():
    assert _siguiente_evento(None) == "ingreso"


def test_despues_de_un_ingreso_viene_una_salida():
    assert _siguiente_evento("ingreso") == "salida"


def test_despues_de_una_salida_viene_un_ingreso():
    assert _siguiente_evento("salida") == "ingreso"


def test_registra_el_ingreso_de_un_estudiante_conocido(rostro_conocido):
    repo = RepositorioFalso([Candidato(1, ROSTRO)], ESTUDIANTES)

    resultado = procesar_fotograma(np.zeros((10, 10, 3)), punto_acceso_id=1, repositorio=repo)

    assert resultado.identificado
    assert resultado.estudiante_id == 1
    assert resultado.tipo_evento == "ingreso"
    assert resultado.confianza == pytest.approx(1.0)
    assert len(repo.registros) == 1


def test_alterna_a_salida_cuando_ya_habia_un_ingreso(rostro_conocido):
    repo = RepositorioFalso([Candidato(1, ROSTRO)], ESTUDIANTES, ultimo="ingreso")

    resultado = procesar_fotograma(np.zeros((10, 10, 3)), punto_acceso_id=1, repositorio=repo)

    assert resultado.tipo_evento == "salida"


def test_no_registra_nada_cuando_no_identifica(rostro_conocido):
    """Un rostro desconocido no debe generar registro de acceso."""
    repo = RepositorioFalso([Candidato(9, np.ones(DIMENSIONES) * 5)], ESTUDIANTES)

    resultado = procesar_fotograma(np.zeros((10, 10, 3)), punto_acceso_id=1, repositorio=repo)

    assert not resultado.identificado
    assert resultado.motivo == "confianza_insuficiente"
    assert repo.registros == []


def test_fotograma_sin_rostro(monkeypatch):
    def sin_rostro(img, estricto=True):
        raise RostroNoDetectado()

    monkeypatch.setattr(control_acceso, "codificar_rostro", sin_rostro)
    repo = RepositorioFalso([], ESTUDIANTES)

    resultado = procesar_fotograma(np.zeros((10, 10, 3)), punto_acceso_id=1, repositorio=repo)

    assert not resultado.identificado
    assert resultado.motivo == "sin_rostro"
    assert repo.registros == []


def test_mide_el_tiempo_de_respuesta(rostro_conocido):
    """El RNF-01 fija un maximo de tres segundos por identificacion."""
    repo = RepositorioFalso([Candidato(1, ROSTRO)], ESTUDIANTES)

    resultado = procesar_fotograma(np.zeros((10, 10, 3)), punto_acceso_id=1, repositorio=repo)

    assert resultado.milisegundos > 0
    assert resultado.milisegundos < 3000
