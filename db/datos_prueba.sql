-- Datos minimos para levantar el entorno de pruebas del sprint 2.
-- Las contrasenas se generan con scripts/crear_usuario.py, nunca a mano.

INSERT INTO punto_acceso (nombre, ubicacion) VALUES
 ('Porteria principal', 'Avenida Circunvalar, entrada peatonal'),
 ('Acceso bloque B',    'Segundo piso, torre B'),
 ('Acceso biblioteca',  'Primer piso, ala sur');

INSERT INTO camara (punto_acceso_id, tipo, estado) VALUES
 (1, 'webcam-1080p', 'activa'),
 (2, 'webcam-720p',  'activa'),
 (3, 'webcam-720p',  'inactiva');
