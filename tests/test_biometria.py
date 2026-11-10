"""Caja blanca del tratamiento de datos biometricos.

Cubre dos pruebas de la asesoria: que no se guarden rostros sin
consentimiento y que los datos se borren cuando la persona se retira.
Ambas sostienen lo que el documento compromete frente a la Ley 1581 de 2012.
"""

from __future__ import annotations

import pytest

from tests.ayudas import vector


class TestConsentimiento:
    """Sin autorizacion expresa no se almacena ningun rostro."""

    def test_no_guarda_el_rostro_de_quien_no_autorizo(self, repo):
        pid = repo.crear_persona(nombres="Luis", apellidos="Gomez",
                                 autoriza_biometria=False)
        with pytest.raises(PermissionError):
            repo.guardar_codificacion(pid, vector(0.1))
        assert repo.codificaciones == []

    def test_guarda_el_rostro_de_quien_si_autorizo(self, repo):
        pid = repo.crear_persona(nombres="Ana", apellidos="Ruiz",
                                 autoriza_biometria=True)
        assert repo.guardar_codificacion(pid, vector(0.1)) is not None
        assert len(repo.codificaciones) == 1

    def test_el_enrolamiento_mueve_a_la_persona_a_enrolado(self, repo):
        pid = repo.crear_persona(autoriza_biometria=True, estado="preinscrito")
        repo.guardar_codificacion(pid, vector(0.1))
        assert repo.obtener_persona(pid)["estado"] == "enrolado"

    def test_persona_inexistente_falla(self, repo):
        with pytest.raises(ValueError):
            repo.guardar_codificacion(999, vector(0.1))

    def test_quien_no_autorizo_no_entra_al_catalogo(self, repo):
        sin = repo.crear_persona(autoriza_biometria=False, estado="activo")
        con = repo.crear_persona(autoriza_biometria=True, estado="activo")
        repo.guardar_codificacion(con, vector(0.2))
        ids = [c.persona_id for c in repo.cargar_catalogo()]
        assert con in ids and sin not in ids


class TestSupresion:
    """Derecho al olvido: el rostro se borra, el historico se conserva."""

    def _persona_enrolada(self, repo):
        pid = repo.crear_persona(autoriza_biometria=True, estado="activo")
        repo.guardar_codificacion(pid, vector(0.3))
        repo.registrar_acceso(punto_acceso_id=1, persona_id=pid,
                              tipo_evento="ingreso", resultado="identificado")
        return pid

    def test_borra_las_codificaciones(self, repo):
        pid = self._persona_enrolada(repo)
        assert repo.eliminar_codificaciones(pid) == 1
        assert repo.codificaciones == []

    def test_conserva_el_historico_de_accesos(self, repo):
        pid = self._persona_enrolada(repo)
        repo.eliminar_codificaciones(pid)
        assert len(repo.listar_accesos(persona_id=pid)) == 1

    def test_tras_el_borrado_deja_de_ser_identificable(self, repo):
        pid = self._persona_enrolada(repo)
        repo.eliminar_codificaciones(pid)
        assert repo.cargar_catalogo() == []

    def test_la_persona_retirada_sale_del_catalogo(self, repo):
        pid = self._persona_enrolada(repo)
        repo.actualizar_estado_persona(pid, "retirado")
        assert repo.cargar_catalogo() == []

    def test_la_persona_suspendida_sale_del_catalogo(self, repo):
        pid = self._persona_enrolada(repo)
        repo.actualizar_estado_persona(pid, "suspendido")
        assert repo.cargar_catalogo() == []

    def test_estado_invalido_se_rechaza(self, repo):
        pid = repo.crear_persona()
        with pytest.raises(ValueError):
            repo.actualizar_estado_persona(pid, "desaparecido")
