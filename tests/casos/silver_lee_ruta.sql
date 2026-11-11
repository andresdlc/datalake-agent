-- Caso negativo: Silver leyendo archivos de aterrizaje saltándose Bronce (DEBE fallar)
CREATE OR REFRESH STREAMING TABLE clientes_directo AS
SELECT * FROM STREAM read_files('/Volumes/workspace/aterrizaje/core/clientes/', format => 'csv');
