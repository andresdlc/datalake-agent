-- Caso negativo: Gold leyendo referencia directamente (DEBE fallar: la referencia entra primero a Silver)
CREATE OR REFRESH MATERIALIZED VIEW kpi_incorrecto2 AS
SELECT p.region, count(*) FROM workspace.clientes_pn_silver.cuentas_pn c
JOIN workspace.referencia.provincias p ON p.cod_provincia = '09' GROUP BY p.region;
