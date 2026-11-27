"""Caja blanca de la interfaz del panel y del banco de escenas de la demo."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from PIL import Image

from app.web import filtro_fecha_corta, filtro_hora, filtro_iniciales
from tests.test_api import ConfigPrueba, app, client, entrar_como  # noqa: F401


class TestPanel:
    def test_el_fragmento_de_accesos_trae_las_cifras_del_dia(self, client, repo):
        pid = repo.crear_persona(nombres="Ana", apellidos="Ruiz", tipo_persona="estudiante")
        repo.registrar_acceso(punto_acceso_id=1, camara_id=1, persona_id=pid,
                              tipo_evento="ingreso", resultado="identificado",
                              fecha_hora=datetime.now())
        repo.registrar_acceso(punto_acceso_id=1, camara_id=1, persona_id=None,
                              tipo_evento="ingreso", resultado="no_identificado",
                              fecha_hora=datetime.now())
        entrar_como(client, "guardia")
        html = client.get("/panel/accesos").get_data(as_text=True)
        assert "Ana Ruiz" in html
        assert "Identificados hoy" in html and "Sin identificar hoy" in html

    def test_el_panel_refresca_alertas_y_accesos(self, client, repo):
        entrar_como(client, "guardia")
        html = client.get("/panel").get_data(as_text=True)
        assert 'data-url="/panel/accesos"' in html
        assert "Todo en orden" in html            # sin alertas abiertas

    def test_el_fragmento_exige_sesion(self, client):
        assert client.get("/panel/accesos").status_code in (302, 401)


class TestFiltros:
    def test_hora_y_fecha_legibles(self):
        ahora = datetime.now().replace(hour=9, minute=5, second=7)
        assert filtro_hora(ahora) == "09:05:07"
        assert filtro_fecha_corta(ahora) == "hoy, 09:05"
        assert filtro_fecha_corta(ahora - timedelta(days=1)).startswith("ayer")
        assert filtro_fecha_corta(datetime(2026, 3, 2, 14, 30)) == "2 mar, 14:30"
        assert filtro_hora(None) == ""

    def test_iniciales(self):
        assert filtro_iniciales("Ana", "Ruiz") == "AR"
        assert filtro_iniciales("Andrés Rojas") == "AR"
        assert filtro_iniciales(None) == "?"


class TestBancoDeEscenas:
    def _banco(self, tmp_path, detecciones):
        (tmp_path / "imagenes").mkdir()
        Image.new("RGB", (320, 240), (90, 90, 90)).save(tmp_path / "imagenes" / "escena_001.jpg")
        (tmp_path / "detecciones.json").write_text(
            json.dumps({"imagenes": {"escena_001.jpg": detecciones}}), encoding="utf-8")
        from scripts.demo import Banco
        return Banco(tmp_path)

    def test_usa_la_deteccion_real_mas_confiable(self, tmp_path):
        from scripts.demo import aviso_de_arma
        banco = self._banco(tmp_path, [
            {"clase": "knife", "confianza": 0.81, "caja": [10, 10, 60, 60]},
            {"clase": "pistol", "confianza": 0.93, "caja": [80, 80, 140, 140]},
            {"clase": "person", "confianza": 0.9, "caja": [0, 0, 200, 230]},
            {"clase": "person", "confianza": 0.7, "caja": [150, 0, 300, 230]},
            {"clase": "smartphone", "confianza": 0.95, "caja": [5, 5, 20, 20]},
        ])
        assert banco.modo == "banco"
        aviso = aviso_de_arma(banco, 0.70)
        assert aviso["tipo_arma"] == "arma_fuego"
        assert aviso["confianza"] == 0.93
        assert aviso["rostros_en_escena"] == 2     # dos personas: sin contexto
        assert aviso["imagen"]

    def test_bajo_el_umbral_no_hay_alerta(self, tmp_path):
        from scripts.demo import aviso_de_arma
        banco = self._banco(tmp_path, [{"clase": "knife", "confianza": 0.4, "caja": [1, 1, 9, 9]}])
        assert aviso_de_arma(banco, 0.70) is None

    def test_sin_banco_usa_el_fotograma_sintetico(self, tmp_path):
        from scripts.demo import Banco
        assert Banco(tmp_path / "no_existe").modo == "sintetico"
