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


def _alerta(repo, estado="notificada", tipo="arma_fuego", **extra):
    aid = repo.crear_alerta(camara_id=1, punto_acceso_id=1, tipo_arma=tipo, confianza=0.9, **extra)
    repo.alertas[aid]["estado"] = estado
    return aid


class TestSeguimientoDeAlertas:
    def test_el_desenlace_queda_guardado_al_cerrar(self, client, repo):
        from app.servicios import alertas as servicio
        aid = _alerta(repo, "en_atencion")
        repo.alertas[aid]["atendida_por"] = 7
        servicio.resolver(aid, 7, confirmada=False, repositorio=repo)
        assert repo.alertas[aid]["estado"] == "cerrada"
        assert repo.alertas[aid]["desenlace"] == "falso_positivo"
        assert repo.alertas[aid]["fecha_cierre"] is not None

    def test_filtra_confirmadas_y_falsos_positivos(self, client, repo):
        confirmada = _alerta(repo, "cerrada")
        repo.alertas[confirmada]["desenlace"] = "confirmada"
        falso = _alerta(repo, "cerrada", tipo="arma_blanca")
        repo.alertas[falso]["desenlace"] = "falso_positivo"
        _alerta(repo, "notificada")
        entrar_como(client, "guardia")
        html = client.get("/alertas?estado=confirmadas").get_data(as_text=True)
        assert f"#{confirmada}" in html and f"#{falso}<" not in html
        html = client.get("/alertas?estado=falsos").get_data(as_text=True)
        assert "Falso positivo" in html and f"#{confirmada}<" not in html
        html = client.get("/alertas?tipo=arma_blanca").get_data(as_text=True)
        assert f"#{falso}" in html

    def test_las_pestanas_del_panel_filtran_las_abiertas(self, client, repo):
        escalada = _alerta(repo, "escalada")
        nueva = _alerta(repo, "notificada")
        entrar_como(client, "guardia")
        html = client.get("/panel/alertas?ver=escaladas").get_data(as_text=True)
        assert f'id="alerta-{escalada}"' in html
        assert f'id="alerta-{nueva}"' not in html
        assert "Alertas abiertas (2)" in html          # el total no cambia

    def test_consulta_ve_las_alertas_pero_no_puede_gestionarlas(self, client, repo):
        aid = _alerta(repo, "escalada")
        entrar_como(client, "consulta")
        for ruta in ("/panel/alertas", "/alertas"):
            html = client.get(ruta).get_data(as_text=True)
            assert f"#{aid}" in html                       # la ve
            for accion in ("Atender", "Confirmar arma", "Descartar", "Gestionar", "data-evidencia="):
                assert accion not in html, f"consulta ve '{accion}' en {ruta}"
        assert client.get(f"/panel/alertas/{aid}/evidencia").status_code == 403
        assert client.post(f"/panel/alertas/{aid}/atender").status_code == 403
        assert repo.alertas[aid]["estado"] == "escalada"   # nada cambio
        entrar_como(client, "guardia")
        assert "Gestionar" in client.get("/alertas").get_data(as_text=True)

    def test_la_bitacora_es_solo_del_administrador(self, client, repo):
        repo.registrar_auditoria(1, "ver_evidencia", "alerta_arma", 3)
        entrar_como(client, "guardia")
        assert client.get("/bitacora").status_code == 403
        entrar_como(client, "administrador")
        html = client.get("/bitacora").get_data(as_text=True)
        assert "Ver evidencia" in html
