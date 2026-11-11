-- Resultados de expectations de los pipelines (event log). Reemplazar <pipeline_id>.
SELECT d.dataset, d.nombre, sum(d.passed_records) AS pasaron, sum(d.failed_records) AS fallaron
FROM (
  SELECT explode(from_json(details:flow_progress:data_quality:expectations,
         'array<struct<name:string,dataset:string,passed_records:bigint,failed_records:bigint>>')) AS e
  FROM event_log('<pipeline_id>')
  WHERE event_type = 'flow_progress'
    AND origin.update_id = (SELECT origin.update_id FROM event_log('<pipeline_id>') WHERE event_type='create_update' ORDER BY timestamp DESC LIMIT 1)
) LATERAL VIEW inline(array(struct(e.dataset AS dataset, e.name AS nombre, e.passed_records AS passed_records, e.failed_records AS failed_records))) d
GROUP BY ALL ORDER BY 1, 2
