"""Dobles de prueba compartidos.

El repositorio real habla con PostgreSQL. Para las pruebas de caja blanca se
sustituye por uno en memoria que respeta el mismo contrato y, sobre todo, las
mismas reglas de integridad que impone el esquema: un evento identificado
exige persona, no se guardan rostros sin consentimiento y una alerta conserva
su referencia a la persona.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta

import numpy as np
import pytest

from app.servicios.reconocimiento_facial import Candidato


class RepositorioFalso:
    """Repositorio en memoria con las mismas reglas que la base de datos."""

    def __init__(self):
        self.personas: dict[int, dict] = {}
        self.codificaciones: list[dict] = []
        self.registros: list[dict] = []
        self.alertas: dict[int, dict] = {}
        self.usuarios: dict[int, dict] = {}
        self.auditoria: list[dict] = []
        self.camaras: list[dict] = [{
            "id": 1, "punto_acceso_id": 1, "identificador": "CAM-01",
            "resolucion_ancho": 1280, "resolucion_alto": 720, "estado": "activa",
        }]
        self._secuencias = {"persona": 0, "codificacion": 0, "registro": 0,
                            "alerta": 0, "usuario": 0, "auditoria": 0}

    def _siguiente(self, nombre: str) -> int:
        self._secuencias[nombre] += 1
        return self._secuencias[nombre]

    # ---------------- personas y biometria ----------------
    def crear_persona(self, institucion_id=1, documento="0", tipo_persona="estudiante",
                      nombres="N", apellidos="A", correo=None, adscripcion=None,
                      autoriza_biometria=False, estado="preinscrito"):
        pid = self._siguiente("persona")
        self.personas[pid] = {
            "id": pid, "institucion_id": institucion_id, "documento": documento,
            "tipo_persona": tipo_persona, "nombres": nombres, "apellidos": apellidos,
            "correo": correo, "adscripcion": adscripcion, "estado": estado,
            "autoriza_biometria": autoriza_biometria,
            "fecha_consentimiento": datetime.now() if autoriza_biometria else None,
        }
        return pid

    def obtener_persona(self, persona_id):
        persona = self.personas.get(persona_id)
        return copy.deepcopy(persona) if persona else None

    def listar_personas(self, estado=None, tipo_persona=None):
        return [copy.deepcopy(p) for p in self.personas.values()
                if (estado is None or p["estado"] == estado)
                and (tipo_persona is None or p["tipo_persona"] == tipo_persona)]

    def actualizar_estado_persona(self, persona_id, estado):
        if estado not in ("preinscrito", "enrolado", "activo", "suspendido", "retirado"):
            raise ValueError(f"estado de persona invalido: {estado}")
        if persona_id not in self.personas:
            return 0
        self.personas[persona_id]["estado"] = estado
        return 1

    def guardar_codificacion(self, persona_id, vector):
        persona = self.personas.get(persona_id)
        if persona is None:
            raise ValueError(f"la persona {persona_id} no existe")
        if not persona["autoriza_biometria"]:
            raise PermissionError(
                "la persona no autorizo el tratamiento de sus datos biometricos"
            )
        cid = self._siguiente("codificacion")
        self.codificaciones.append({
            "id": cid, "persona_id": persona_id,
            "vector": np.asarray(vector, dtype=np.float64), "activa": True,
        })
        if persona["estado"] == "preinscrito":
            persona["estado"] = "enrolado"
        return cid

    def eliminar_codificaciones(self, persona_id):
        antes = len(self.codificaciones)
        self.codificaciones = [c for c in self.codificaciones
                               if c["persona_id"] != persona_id]
        return antes - len(self.codificaciones)

    def cargar_catalogo(self):
        return [
            Candidato(persona_id=c["persona_id"], vector=c["vector"])
            for c in self.codificaciones
            if c["activa"]
            and self.personas[c["persona_id"]]["estado"] in ("enrolado", "activo")
            and self.personas[c["persona_id"]]["autoriza_biometria"]
        ]

    # ---------------- registros de acceso ----------------
    def ultimo_registro(self, persona_id):
        propios = [r for r in self.registros if r["persona_id"] == persona_id]
        if not propios:
            return None
        return copy.deepcopy(max(propios, key=lambda r: r["fecha_hora"]))

    def registrar_acceso(self, punto_acceso_id, tipo_evento, resultado,
                         persona_id=None, camara_id=None, metodo="facial",
                         distancia=None, confianza=None, imagen_url=None,
                         fecha_hora=None):
        if tipo_evento not in ("ingreso", "salida"):
            raise ValueError("tipo_evento debe ser 'ingreso' o 'salida'")
        if resultado == "identificado" and persona_id is None:
            raise ValueError("un evento identificado debe indicar a que persona")
        rid = self._siguiente("registro")
        self.registros.append({
            "id": rid, "punto_acceso_id": punto_acceso_id, "camara_id": camara_id,
            "persona_id": persona_id, "tipo_evento": tipo_evento, "metodo": metodo,
            "resultado": resultado, "distancia": distancia, "confianza": confianza,
            "imagen_url": imagen_url, "verificado_por": None,
            "fecha_hora": fecha_hora or datetime.now(),
        })
        return rid

    def verificar_acceso_manual(self, registro_id, usuario_id, persona_id, aprobado):
        for r in self.registros:
            if r["id"] == registro_id and r["resultado"] == "no_identificado":
                r["resultado"] = "verificado_manual" if aprobado else "rechazado"
                r["persona_id"] = persona_id or r["persona_id"]
                r["verificado_por"] = usuario_id
                return 1
        return 0

    def listar_accesos(self, desde=None, hasta=None, persona_id=None,
                       punto_acceso_id=None, resultado=None, limite=200):
        filas = [copy.deepcopy(r) for r in self.registros
                 if (persona_id is None or r["persona_id"] == persona_id)
                 and (resultado is None or r["resultado"] == resultado)]
        return sorted(filas, key=lambda r: r["fecha_hora"], reverse=True)[:limite]

    # ---------------- alertas ----------------
    def crear_alerta(self, camara_id, punto_acceso_id, tipo_arma, confianza,
                     registro_acceso_id=None, persona_id=None, imagen_url=None,
                     fecha_hora=None):
        if tipo_arma not in ("arma_fuego", "arma_blanca", "indeterminada"):
            raise ValueError(f"tipo_arma invalido: {tipo_arma}")
        aid = self._siguiente("alerta")
        self.alertas[aid] = {
            "id": aid, "camara_id": camara_id, "punto_acceso_id": punto_acceso_id,
            "registro_acceso_id": registro_acceso_id, "persona_id": persona_id,
            "tipo_arma": tipo_arma, "confianza": confianza, "estado": "generada",
            "atendida_por": None, "fecha_escalamiento": None,
            "fecha_hora": fecha_hora or datetime.now(),
        }
        return aid

    def obtener_alerta(self, alerta_id):
        alerta = self.alertas.get(alerta_id)
        return copy.deepcopy(alerta) if alerta else None

    def actualizar_estado_alerta(self, alerta_id, estado, usuario_id=None, escalada=False):
        if alerta_id not in self.alertas:
            return 0
        self.alertas[alerta_id]["estado"] = estado
        if usuario_id is not None:
            self.alertas[alerta_id]["atendida_por"] = usuario_id
        if escalada:
            self.alertas[alerta_id]["fecha_escalamiento"] = datetime.now()
        return 1

    def listar_alertas(self, estado=None, limite=100):
        return [copy.deepcopy(a) for a in self.alertas.values()
                if estado is None or a["estado"] == estado][:limite]

    def alertas_sin_atender(self, minutos):
        limite = datetime.now() - timedelta(minutes=minutos)
        return [copy.deepcopy(a) for a in self.alertas.values()
                if a["estado"] in ("generada", "notificada")
                and a["fecha_hora"] < limite]

    # ---------------- usuarios ----------------
    def crear_usuario(self, nombre, correo, contrasena_hash, rol_id,
                      rol="guardia", estado="activo"):
        uid = self._siguiente("usuario")
        self.usuarios[uid] = {
            "id": uid, "nombre": nombre, "correo": correo,
            "contrasena_hash": contrasena_hash, "rol_id": rol_id, "rol": rol,
            "estado": estado, "intentos_fallidos": 0, "permisos": [],
        }
        return uid

    def obtener_usuario(self, usuario_id):
        usuario = self.usuarios.get(usuario_id)
        return copy.deepcopy(usuario) if usuario else None

    def obtener_usuario_por_correo(self, correo):
        for u in self.usuarios.values():
            if u["correo"] == correo:
                return copy.deepcopy(u)
        return None

    def listar_usuarios(self):
        return [copy.deepcopy(u) for u in self.usuarios.values()]

    def registrar_intento_fallido(self, usuario_id, maximo):
        usuario = self.usuarios[usuario_id]
        usuario["intentos_fallidos"] += 1
        if usuario["intentos_fallidos"] >= maximo:
            usuario["estado"] = "bloqueado"
        return 1

    def reiniciar_intentos(self, usuario_id):
        usuario = self.usuarios[usuario_id]
        usuario["intentos_fallidos"] = 0
        usuario["ultimo_acceso"] = datetime.now()
        if usuario["estado"] == "registrado":
            usuario["estado"] = "activo"
        return 1

    def cambiar_estado_usuario(self, usuario_id, estado):
        if estado not in ("registrado", "activo", "bloqueado", "inactivo"):
            raise ValueError(f"estado de usuario invalido: {estado}")
        if usuario_id not in self.usuarios:
            return 0
        self.usuarios[usuario_id]["estado"] = estado
        if estado == "activo":
            self.usuarios[usuario_id]["intentos_fallidos"] = 0
        return 1

    # ---------------- infraestructura ----------------
    def listar_puntos_acceso(self):
        return [{"id": 1, "nombre": "Porteria principal", "ubicacion": "Bloque A"}]

    def crear_punto_acceso(self, institucion_id, nombre, ubicacion=None):
        return 1

    def listar_camaras(self, punto_acceso_id=None):
        return [copy.deepcopy(c) for c in self.camaras
                if punto_acceso_id is None
                or c["punto_acceso_id"] == punto_acceso_id]

    def crear_camara(self, **kwargs):
        return 1

    def registrar_auditoria(self, usuario_id, accion, entidad=None,
                            entidad_id=None, detalle=None, ip_origen=None):
        aid = self._siguiente("auditoria")
        self.auditoria.append({
            "id": aid, "usuario_id": usuario_id, "accion": accion,
            "entidad": entidad, "entidad_id": entidad_id, "detalle": detalle,
            "fecha_hora": datetime.now(),
        })
        return aid

    def listar_auditoria(self, limite=200):
        return list(reversed(self.auditoria))[:limite]

    def resumen_accesos(self, desde, hasta):
        return {"accesos": [], "alertas": []}


@pytest.fixture
def repo():
    return RepositorioFalso()
