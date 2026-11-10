-- Datos minimos para levantar un entorno de pruebas.
-- Requiere haber ejecutado antes db/schema.sql.

INSERT INTO institucion (nombre, ciudad, retencion_dias)
VALUES ('Institucion de educacion superior', 'Bogota', 180);

INSERT INTO punto_acceso (institucion_id, nombre, ubicacion) VALUES
 (1, 'Porteria principal', 'Bloque A'),
 (1, 'Acceso peatonal norte', 'Bloque C');

INSERT INTO camara (punto_acceso_id, identificador, tipo,
                    resolucion_ancho, resolucion_alto, lux_minimo) VALUES
 (1, 'CAM-01', 'IP',     1280, 720, 220),
 (2, 'CAM-02', 'webcam',  640, 480, 150);   -- no cumple el RNF-14, a proposito

-- Personas de distintos tipos. La poblacion del estudio no son solo
-- estudiantes, de modo que el modelo tampoco.
INSERT INTO persona (institucion_id, documento, tipo_persona, nombres, apellidos,
                     adscripcion, estado, autoriza_biometria, fecha_consentimiento) VALUES
 (1, '1001', 'estudiante',     'Ana',    'Ruiz',   'Ingenieria de Software', 'activo', TRUE,  NOW()),
 (1, '1002', 'docente',        'Carlos', 'Mejia',  'Facultad de Ingenierias', 'activo', TRUE,  NOW()),
 (1, '1003', 'administrativo', 'Lucia',  'Pardo',  'Registro academico',      'activo', FALSE, NULL),
 (1, '1004', 'visitante',      'Jorge',  'Nieto',  NULL,                      'preinscrito', FALSE, NULL);

-- Lucia no autorizo el tratamiento biometrico: entra con credencial.
INSERT INTO registro_acceso (punto_acceso_id, persona_id, tipo_evento, metodo, resultado)
VALUES (1, 3, 'ingreso', 'credencial', 'identificado');

-- Un evento que el sistema no pudo resolver y que espera verificacion.
INSERT INTO registro_acceso (punto_acceso_id, camara_id, tipo_evento, metodo,
                             resultado, imagen_url)
VALUES (1, 1, 'ingreso', 'facial', 'no_identificado', 's3://evidencias/demo.jpg');
