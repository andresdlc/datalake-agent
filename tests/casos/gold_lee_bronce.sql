-- Caso negativo: Gold leyendo Bronce (DEBE fallar el control)
CREATE OR REFRESH MATERIALIZED VIEW kpi_incorrecto AS
SELECT segmento, count(*) FROM workspace.bronce.clientes_pn_snapshot GROUP BY segmento;
