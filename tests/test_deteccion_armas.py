"""Caja blanca de la deteccion de armas visibles.

El modelo YOLOv8 se inyecta como doble, de modo que estas pruebas verifican
la logica de filtrado y de traduccion de etiquetas sin cargar los pesos ni
depender de Ultralytics.

Cubre tambien los casos negativos que pide la asesoria para las pruebas de
caja negra: un celular o una sombrilla no deben generar alerta.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.servicios.deteccion_armas import (
    ARMA_BLANCA, ARMA_FUEGO, DetectorArmas, traducir_etiqueta,
)


class CajaFalsa:
    """Imita una caja de Ultralytics."""

    def __init__(self, clase: int, confianza: float, xyxy=(10, 10, 50, 50)):
        self.cls = clase
        self.conf = confianza
        self.xyxy = [list(xyxy)]


class ResultadoFalso:
    def __init__(self, nombres: dict, cajas: list):
        self.names = nombres
        self.boxes = cajas


class ModeloFalso:
    """Doble del modelo. Devuelve siempre el resultado que se le configura."""

    def __init__(self, nombres: dict, cajas: list):
        self.nombres = nombres
        self.cajas = cajas
        self.llamadas = 0

    def predict(self, imagen, conf=None, verbose=False):
        self.llamadas += 1
        return [ResultadoFalso(self.nombres, self.cajas)]


@pytest.fixture
def imagen():
    return np.zeros((480, 640, 3), dtype=np.uint8)


class TestTraduccionDeEtiquetas:
    """El dataset habla su idioma; la base de datos, el suyo."""

    @pytest.mark.parametrize("etiqueta,esperado", [
        ("pistol", ARMA_FUEGO),
        ("Gun", ARMA_FUEGO),
        ("RIFLE", ARMA_FUEGO),
        ("arma_de_fuego", ARMA_FUEGO),
        ("knife", ARMA_BLANCA),
        ("machete", ARMA_BLANCA),
        ("arma_blanca", ARMA_BLANCA),
    ])
    def test_traduce_las_clases_de_arma(self, etiqueta, esperado):
        assert traducir_etiqueta(etiqueta) == esperado

    @pytest.mark.parametrize("etiqueta", ["cell phone", "umbrella", "person", "backpack"])
    def test_lo_que_no_es_arma_no_se_traduce(self, etiqueta):
        assert traducir_etiqueta(etiqueta) is None

    def test_el_vocabulario_coincide_con_la_base_de_datos(self):
        """Los valores deben ser los que admite el CHECK de alerta_arma."""
        assert ARMA_FUEGO == "arma_fuego"
        assert ARMA_BLANCA == "arma_blanca"


class TestDeteccion:
    def test_detecta_una_pistola(self, imagen):
        modelo = ModeloFalso({0: "pistol"}, [CajaFalsa(0, 0.93)])
        detecciones = DetectorArmas(umbral=0.7, modelo=modelo).detectar(imagen)
        assert len(detecciones) == 1
        assert detecciones[0].tipo_arma == ARMA_FUEGO
        assert detecciones[0].confianza == pytest.approx(0.93)

    def test_detecta_un_cuchillo(self, imagen):
        modelo = ModeloFalso({0: "knife"}, [CajaFalsa(0, 0.78)])
        detecciones = DetectorArmas(umbral=0.7, modelo=modelo).detectar(imagen)
        assert detecciones[0].tipo_arma == ARMA_BLANCA

    def test_un_celular_no_genera_deteccion(self, imagen):
        modelo = ModeloFalso({0: "cell phone"}, [CajaFalsa(0, 0.99)])
        assert DetectorArmas(umbral=0.7, modelo=modelo).detectar(imagen) == []

    def test_una_sombrilla_no_genera_deteccion(self, imagen):
        modelo = ModeloFalso({0: "umbrella"}, [CajaFalsa(0, 0.95)])
        assert DetectorArmas(umbral=0.7, modelo=modelo).detectar(imagen) == []

    def test_descarta_lo_que_no_alcanza_el_umbral(self, imagen):
        modelo = ModeloFalso({0: "pistol"}, [CajaFalsa(0, 0.40)])
        assert DetectorArmas(umbral=0.7, modelo=modelo).detectar(imagen) == []

    def test_un_umbral_mas_bajo_deja_pasar_la_misma_deteccion(self, imagen):
        modelo = ModeloFalso({0: "pistol"}, [CajaFalsa(0, 0.40)])
        assert len(DetectorArmas(umbral=0.3, modelo=modelo).detectar(imagen)) == 1

    def test_separa_armas_de_objetos_en_la_misma_escena(self, imagen):
        modelo = ModeloFalso(
            {0: "pistol", 1: "person", 2: "knife"},
            [CajaFalsa(0, 0.88), CajaFalsa(1, 0.99), CajaFalsa(2, 0.75)],
        )
        detecciones = DetectorArmas(umbral=0.7, modelo=modelo).detectar(imagen)
        assert sorted(d.tipo_arma for d in detecciones) == [ARMA_BLANCA, ARMA_FUEGO]

    def test_conserva_la_caja_del_objeto(self, imagen):
        modelo = ModeloFalso({0: "pistol"}, [CajaFalsa(0, 0.9, (12, 34, 56, 78))])
        assert DetectorArmas(umbral=0.7, modelo=modelo).detectar(imagen)[0].caja == (12, 34, 56, 78)

    def test_escena_vacia_no_detecta_nada(self, imagen):
        modelo = ModeloFalso({}, [])
        assert DetectorArmas(umbral=0.7, modelo=modelo).detectar(imagen) == []


class TestMasProbable:
    """La alerta se genera con la deteccion de mayor confianza."""

    def test_elige_la_de_mayor_confianza(self, imagen):
        modelo = ModeloFalso(
            {0: "knife", 1: "pistol"},
            [CajaFalsa(0, 0.74), CajaFalsa(1, 0.96)],
        )
        mejor = DetectorArmas(umbral=0.7, modelo=modelo).mas_probable(imagen)
        assert mejor.tipo_arma == ARMA_FUEGO

    def test_sin_detecciones_devuelve_none(self, imagen):
        modelo = ModeloFalso({0: "person"}, [CajaFalsa(0, 0.99)])
        assert DetectorArmas(umbral=0.7, modelo=modelo).mas_probable(imagen) is None


class TestConfiguracion:
    def test_toma_el_umbral_de_la_configuracion_por_defecto(self):
        from app.config import Config

        assert DetectorArmas().umbral == Config.UMBRAL_ARMA

    def test_el_umbral_explicito_tiene_prioridad(self):
        assert DetectorArmas(umbral=0.55).umbral == 0.55
