-- ============================================================
-- FaceGuard UMB - Script de generacion de la base de datos
-- Motor: PostgreSQL 15 (Supabase)
-- Corresponde a la seccion 3.6 del trabajo de grado.
-- ============================================================

CREATE TABLE rol (
    id            SERIAL PRIMARY KEY,
    nombre        VARCHAR(50) NOT NULL UNIQUE,
    descripcion   TEXT
);

CREATE TABLE usuario (
    id               SERIAL PRIMARY KEY,
    nombre           VARCHAR(100) NOT NULL,
    correo           VARCHAR(120) NOT NULL UNIQUE,
    contrasena_hash  VARCHAR(255) NOT NULL,
    rol_id           INTEGER NOT NULL REFERENCES rol(id),
    activo           BOOLEAN DEFAULT TRUE,
    creado_en        TIMESTAMP DEFAULT NOW()
);

CREATE TABLE estudiante (
    id                      SERIAL PRIMARY KEY,
    codigo                  VARCHAR(20) NOT NULL UNIQUE,
    nombres                 VARCHAR(100) NOT NULL,
    apellidos               VARCHAR(100) NOT NULL,
    correo                  VARCHAR(120),
    programa                VARCHAR(100),
    estado                  VARCHAR(20) NOT NULL DEFAULT 'activo'
                            CHECK (estado IN ('preinscrito','activo','suspendido','retirado')),
    consentimiento_firmado  BOOLEAN NOT NULL DEFAULT FALSE,
    creado_en               TIMESTAMP DEFAULT NOW()
);

CREATE TABLE codificacion_facial (
    id             SERIAL PRIMARY KEY,
    estudiante_id  INTEGER NOT NULL REFERENCES estudiante(id) ON DELETE CASCADE,
    vector         DOUBLE PRECISION[] NOT NULL,  -- embedding de 128 dimensiones
    fecha_captura  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE punto_acceso (
    id         SERIAL PRIMARY KEY,
    nombre     VARCHAR(80) NOT NULL,
    ubicacion  VARCHAR(150)
);

CREATE TABLE camara (
    id               SERIAL PRIMARY KEY,
    punto_acceso_id  INTEGER NOT NULL REFERENCES punto_acceso(id),
    tipo             VARCHAR(40),
    estado           VARCHAR(20) DEFAULT 'activa'
);

CREATE TABLE registro_acceso (
    id               SERIAL PRIMARY KEY,
    estudiante_id    INTEGER NOT NULL REFERENCES estudiante(id),
    punto_acceso_id  INTEGER NOT NULL REFERENCES punto_acceso(id),
    tipo_evento      VARCHAR(10) NOT NULL CHECK (tipo_evento IN ('ingreso','salida')),
    fecha_hora       TIMESTAMP NOT NULL DEFAULT NOW(),
    confianza        NUMERIC(5,4)
);

CREATE TABLE alerta_arma (
    id            SERIAL PRIMARY KEY,
    camara_id     INTEGER NOT NULL REFERENCES camara(id),
    tipo_arma     VARCHAR(40) NOT NULL,
    confianza     NUMERIC(5,4) NOT NULL,
    imagen_url    TEXT,
    fecha_hora    TIMESTAMP NOT NULL DEFAULT NOW(),
    estado        VARCHAR(20) NOT NULL DEFAULT 'generada'
                  CHECK (estado IN ('generada','notificada','en_atencion',
                                    'confirmada','falso_positivo','cerrada')),
    atendida_por  INTEGER REFERENCES usuario(id)
);

-- Indices para las consultas mas frecuentes
CREATE INDEX idx_registro_fecha    ON registro_acceso(fecha_hora);
CREATE INDEX idx_registro_est      ON registro_acceso(estudiante_id);
CREATE INDEX idx_alerta_fecha      ON alerta_arma(fecha_hora);
CREATE INDEX idx_codificacion_est  ON codificacion_facial(estudiante_id);

-- Datos iniciales de roles
INSERT INTO rol (nombre, descripcion) VALUES
 ('administrador', 'Gestion total del sistema, usuarios y reportes'),
 ('guardia',       'Monitoreo de accesos y atencion de alertas'),
 ('consulta',      'Acceso de solo lectura a registros y reportes');
