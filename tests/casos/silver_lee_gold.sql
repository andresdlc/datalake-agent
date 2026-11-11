-- Caso negativo: Silver leyendo Gold (DEBE fallar)
CREATE OR REFRESH MATERIALIZED VIEW silver_incorrecta AS
SELECT * FROM workspace.clientes_pn_gold.cliente_360;
