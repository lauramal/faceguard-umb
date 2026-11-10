"""Caja blanca de autenticacion, roles y cifrado de contrasenas.

Cubre tres pruebas de la asesoria: que las contrasenas vayan cifradas, que
la cuenta se bloquee tras varios intentos y que cada rol haga solo lo suyo.
"""

from __future__ import annotations

import pytest

from app import seguridad
from app.config import Config


@pytest.fixture
def usuario(repo):
    uid = repo.crear_usuario(
        nombre="Guardia Uno", correo="g1@ejemplo.edu",
        contrasena_hash=seguridad.hashear("clave-correcta"),
        rol_id=2, rol="guardia",
    )
    return uid


class TestCifradoDeContrasenas:
    """Nunca se guarda la contrasena en claro."""

    def test_el_hash_no_contiene_la_contrasena(self):
        hash_guardado = seguridad.hashear("mi-clave-secreta")
        assert "mi-clave-secreta" not in hash_guardado

    def test_el_hash_usa_pbkdf2_o_scrypt(self):
        hash_guardado = seguridad.hashear("x")
        assert hash_guardado.startswith(("pbkdf2:", "scrypt:"))

    def test_dos_hashes_de_la_misma_clave_son_distintos(self):
        """La sal aleatoria impide tablas precalculadas."""
        assert seguridad.hashear("igual") != seguridad.hashear("igual")

    def test_verifica_la_clave_correcta(self):
        assert seguridad.verificar("abc", seguridad.hashear("abc"))

    def test_rechaza_la_clave_incorrecta(self):
        assert not seguridad.verificar("otra", seguridad.hashear("abc"))


class TestAutenticacion:
    def test_credenciales_correctas_devuelven_el_usuario(self, repo, usuario):
        resultado = seguridad.autenticar("g1@ejemplo.edu", "clave-correcta", repo)
        assert resultado is not None
        assert resultado["id"] == usuario

    def test_credenciales_incorrectas_no_autentican(self, repo, usuario):
        assert seguridad.autenticar("g1@ejemplo.edu", "mala", repo) is None

    def test_correo_inexistente_no_autentica(self, repo):
        assert seguridad.autenticar("nadie@ejemplo.edu", "x", repo) is None

    def test_el_intento_fallido_queda_en_la_bitacora(self, repo, usuario):
        seguridad.autenticar("g1@ejemplo.edu", "mala", repo)
        assert any(a["accion"] == "login_fallido" for a in repo.auditoria)

    def test_el_ingreso_exitoso_queda_en_la_bitacora(self, repo, usuario):
        seguridad.autenticar("g1@ejemplo.edu", "clave-correcta", repo)
        assert any(a["accion"] == "login_exitoso" for a in repo.auditoria)


class TestBloqueoDeCuenta:
    """Tras varios intentos fallidos la cuenta se bloquea."""

    def test_se_bloquea_al_alcanzar_el_maximo(self, repo, usuario):
        for _ in range(Config.MAX_INTENTOS_FALLIDOS):
            seguridad.autenticar("g1@ejemplo.edu", "mala", repo)
        assert repo.obtener_usuario(usuario)["estado"] == "bloqueado"

    def test_no_se_bloquea_antes_de_tiempo(self, repo, usuario):
        for _ in range(Config.MAX_INTENTOS_FALLIDOS - 1):
            seguridad.autenticar("g1@ejemplo.edu", "mala", repo)
        assert repo.obtener_usuario(usuario)["estado"] == "activo"

    def test_la_cuenta_bloqueada_no_entra_ni_con_la_clave_correcta(self, repo, usuario):
        for _ in range(Config.MAX_INTENTOS_FALLIDOS):
            seguridad.autenticar("g1@ejemplo.edu", "mala", repo)
        assert seguridad.autenticar("g1@ejemplo.edu", "clave-correcta", repo) is None

    def test_un_ingreso_exitoso_reinicia_el_contador(self, repo, usuario):
        seguridad.autenticar("g1@ejemplo.edu", "mala", repo)
        seguridad.autenticar("g1@ejemplo.edu", "clave-correcta", repo)
        assert repo.obtener_usuario(usuario)["intentos_fallidos"] == 0

    def test_el_administrador_desbloquea_la_cuenta(self, repo, usuario):
        for _ in range(Config.MAX_INTENTOS_FALLIDOS):
            seguridad.autenticar("g1@ejemplo.edu", "mala", repo)
        repo.cambiar_estado_usuario(usuario, "activo")
        assert seguridad.autenticar("g1@ejemplo.edu", "clave-correcta", repo) is not None

    def test_la_cuenta_inactiva_no_entra(self, repo, usuario):
        repo.cambiar_estado_usuario(usuario, "inactivo")
        assert seguridad.autenticar("g1@ejemplo.edu", "clave-correcta", repo) is None


class TestEstadosDeUsuario:
    def test_estado_invalido_se_rechaza(self, repo, usuario):
        with pytest.raises(ValueError):
            repo.cambiar_estado_usuario(usuario, "zombi")
