"""Agente de modelado IA (DEMO): lee METADATOS y ESTADÍSTICAS de Bronce (sin enviar valores PII),
llama a un foundation model hospedado en Databricks y propone modelos Silver y Gold como JSON
(tablas, columnas, claves, expectations, orígenes y SQL), respetando las reglas de origen por capa.
Las propuestas quedan en workspace.estandares.propuestas_modelo con estado PENDIENTE_REVISION:
el agente NO despliega; un humano revisa e implementa.

Funciona en un notebook/job de Databricks (usa spark) o en local (usa el SQL warehouse vía dbsql.py).
"""
import json, re, hashlib, datetime, uuid, os

CAT = "workspace"
MODELO = os.environ.get("MODELO_AGENTE", "databricks-gpt-oss-120b")
TABLAS_BRONCE = ["bronce.clientes_pn_snapshot", "bronce.cuentas_pn_snapshot"]
TABLAS_REFERENCIA = ["referencia.provincias", "referencia.tipos_documento", "referencia.segmentos", "referencia.productos"]
# Columnas cuyo VALOR nunca se envía al modelo (solo nombre, tipo y estadísticas agregadas)
PATRON_PII = re.compile(r"nombre|apellido|identificacion|documento_num|email|correo|telefono|celular|direccion|nacimiento", re.I)

# ---------------------------------------------------------------- acceso a datos
def _run_sql_factory():
    try:
        from pyspark.sql import SparkSession
        sesion = SparkSession.getActiveSession()
    except Exception:
        sesion = None
    if sesion is not None:  # dentro de Databricks (notebook o job)
        def run(q):
            df = sesion.sql(q)
            return [c for c in df.columns], [list(r) for r in df.collect()]
        return run
    else:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
        from dbsql import sql
        return lambda q: sql(q, show=False)

run_sql = _run_sql_factory()

def perfil_tabla(fq):
    """Esquema + estadísticas agregadas por columna. Valores de ejemplo solo para columnas no PII y de baja cardinalidad."""
    cat_tabla = f"{CAT}.{fq}"
    _, cols = run_sql(f"SELECT column_name, data_type, comment FROM {CAT}.information_schema.columns "
                      f"WHERE table_schema='{fq.split('.')[0]}' AND table_name='{fq.split('.')[1]}' ORDER BY ordinal_position")
    _, com = run_sql(f"SELECT comment FROM {CAT}.information_schema.tables WHERE table_schema='{fq.split('.')[0]}' AND table_name='{fq.split('.')[1]}'")
    exprs = ["count(*) AS filas"]
    for c, _t, _ in cols:
        exprs += [f"round(avg(CASE WHEN `{c}` IS NULL THEN 1.0 ELSE 0 END),4) AS `{c}__nulos`",
                  f"count(DISTINCT `{c}`) AS `{c}__distintos`",
                  f"min(length(CAST(`{c}` AS STRING))) AS `{c}__lmin`", f"max(length(CAST(`{c}` AS STRING))) AS `{c}__lmax`"]
    nombres, filas = run_sql(f"SELECT {', '.join(exprs)} FROM {cat_tabla}")
    st = dict(zip(nombres, filas[0]))
    columnas = []
    for c, t, cm in cols:
        pii = bool(PATRON_PII.search(c))
        info = {"nombre": c, "tipo": t, "comentario": cm, "posible_pii": pii,
                "pct_nulos": float(st[f"{c}__nulos"]), "distintos": int(st[f"{c}__distintos"]),
                "longitud_min": st[f"{c}__lmin"], "longitud_max": st[f"{c}__lmax"]}
        if pii:
            # Solo el "formato" (dígitos->9, letras->A) de 3 valores, nunca el valor
            _, ej = run_sql(f"SELECT DISTINCT regexp_replace(regexp_replace(CAST(`{c}` AS STRING), '[0-9]', '9'), '[A-Za-zÁÉÍÓÚáéíóúÑñ]', 'A') FROM {cat_tabla} WHERE `{c}` IS NOT NULL LIMIT 3")
            info["formatos_observados"] = [e[0][:40] for e in ej]
        elif int(st[f"{c}__distintos"]) <= 30:
            _, ej = run_sql(f"SELECT CAST(`{c}` AS STRING) v, count(*) n FROM {cat_tabla} GROUP BY 1 ORDER BY 2 DESC LIMIT 12")
            info["valores_frecuentes"] = {str(v): int(n) for v, n in ej}
        columnas.append(info)
    return {"tabla": cat_tabla, "comentario": com[0][0] if com else None, "filas": int(st["filas"]), "columnas": columnas}

def paquete_contexto():
    return {"dominio": "clientes_pn (clientes personas naturales)", "catalogo": CAT,
            "bronce": [perfil_tabla(t) for t in TABLAS_BRONCE],
            "referencia": [perfil_tabla(t) for t in TABLAS_REFERENCIA],
            "notas_carga": "Bronce recibe INSTANTÁNEAS COMPLETAS (sin CDC). version_carga identifica cada carga; "
                           "un cliente ausente en una carga posterior se considera baja."}

# ---------------------------------------------------------------- prompt
def leer_archivo(rel):
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    for p in (os.path.join(base, rel), os.path.join(os.getcwd(), rel)):
        if os.path.exists(p):
            return open(p, encoding="utf-8").read()
    raise FileNotFoundError(rel)

INSTRUCCIONES = """Eres el agente de modelado de datos del banco (arquitectura medallion en Databricks, Unity Catalog).
Tu tarea: proponer modelos de datos para la capa {capa} del dominio clientes personas naturales,
a partir del paquete de contexto (metadatos y estadísticas, sin datos personales).

REGLAS DE ORIGEN POR CAPA (OBLIGATORIAS, no negociables):
- Silver solo puede leer de: tablas de Bronce (esquema `bronce`), otras tablas Silver (esquemas `*_silver`)
  y datos de referencia (esquema `referencia`). Nunca del sistema fuente (JDBC, read_files, rutas, volúmenes) ni de Gold.
- Gold solo puede leer de tablas Silver (`*_silver`) y otras Gold (`*_gold`). NUNCA de Bronce ni de `referencia`:
  si Gold necesita un dato de referencia, la tabla Silver debe incorporarlo antes.
Reglas de origen en YAML:
{reglas}

ESTÁNDAR DE MODELADO:
{estandar}

REQUISITOS:
- Todo en español (nombres, descripciones, comentarios). Nombres en snake_case sin tildes.
- Esquema destino: `{catalogo}.clientes_pn_{capa}`. Usa nombres totalmente calificados catalogo.esquema.tabla en `origenes` y en el SQL.
- Silver debe incluir COMO MÍNIMO estas tablas:
  1) `clientes_pn_historico`: histórico SCD2 de clientes desde las instantáneas de Bronce (patron_carga = "SCD2_DESDE_SNAPSHOT",
     `version_carga` como versión). El `sql` es la consulta de UNA instantánea estandarizada: códigos en mayúsculas sin espacios,
     fechas a DATE (fecha_nacimiento viene como dd/MM/yyyy), tipo de documento y segmento homologados con `referencia`,
     nombre de provincia y región tomados de `referencia.provincias`, y una columna hash de atributos rastreados.
  2) `cuentas_pn`: cuentas/productos vigentes de la última carga (patron_carga = "VIGENTE_DESDE_SNAPSHOT"),
     saldo a DECIMAL(18,2), nombre de producto y tipo de balance desde `referencia.productos`.
  Expectations con accion WARN | DROP | FAIL (FAIL para clave nula; DROP para registros inutilizables; WARN para calidad).
  Prohibido `SELECT *`: lista y transforma cada columna.
- Gold debe incluir COMO MÍNIMO: `cliente_360` (grano: un registro por cliente vigente, con conteo de productos y saldos
  pasivos/activos agregados desde Silver) y `kpi_segmento_provincia` (grano: segmento x provincia, con número de clientes,
  saldo total y saldo promedio). Define el grano y KPIs (fórmula). Prohibido `SELECT *`. Excluye columnas PII que no aporten al análisis.
- Cada columna lleva `sensibilidad_pii` en (identificador, contacto, financiero, ninguna).
- No incluyas valores de datos personales en ningún campo.

Responde SOLO con un objeto JSON válido (sin texto adicional, sin ```), con esta forma:
{{"capa": "{capa}", "resumen": "...", "tablas": [{{"nombre": "...", "descripcion": "...", "grano": "...",
  "clave_negocio": ["..."], "patron_carga": "SCD2_DESDE_SNAPSHOT|VIGENTE_DESDE_SNAPSHOT|VISTA_MATERIALIZADA",
  "origenes": ["catalogo.esquema.tabla", ...],
  "columnas": [{{"nombre": "...", "tipo": "...", "descripcion": "...", "sensibilidad_pii": "...", "regla_transformacion": "..."}}],
  "expectations": [{{"nombre": "...", "expresion": "...", "accion": "WARN|DROP|FAIL"}}],
  "kpis": [{{"nombre": "...", "formula": "..."}}],
  "sql": "SELECT ... (consulta Databricks SQL que materializa la tabla)"}}]}}
"""

def _texto_respuesta(resp):
    c = resp.choices[0].message.content
    if isinstance(c, list):  # algunos modelos devuelven bloques (razonamiento + texto)
        c = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in c if not (isinstance(b, dict) and b.get("type") == "reasoning"))
    return c

def extraer_json(texto):
    t = texto.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    i, j = t.find("{"), t.rfind("}")
    return json.loads(t[i:j+1])

def llamar_modelo(system, user, max_tokens=8000):
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.serving import ChatMessage, ChatMessageRole
    w = WorkspaceClient()
    resp = w.serving_endpoints.query(name=MODELO, max_tokens=max_tokens, temperature=0.1,
                                     messages=[ChatMessage(role=ChatMessageRole.SYSTEM, content=system),
                                               ChatMessage(role=ChatMessageRole.USER, content=user)])
    return _texto_respuesta(resp)

# ---------------------------------------------------------------- scorer de reglas de origen
REF_TABLA = re.compile(r"\b(?:FROM|JOIN)\s+(?:STREAM\s*\(\s*)?`?([\w]+)`?\.`?([\w]+)`?\.`?([\w]+)`?", re.I)
PROHIBIDO_FUENTE = re.compile(r"read_files|abfss://|s3://|jdbc|remote_query|/Volumes/", re.I)

def esquema_permitido(capa, esquema):
    if capa == "silver":
        return esquema in ("bronce", "referencia") or esquema.endswith("_silver")
    if capa == "gold":
        return esquema.endswith("_silver") or esquema.endswith("_gold")
    return True

def respeta_origen_capas(propuesta):
    """Scorer de código: valida `origenes` declarados y referencias FROM/JOIN del SQL propuesto."""
    capa = propuesta.get("capa", "").lower()
    hallazgos = []
    for t in propuesta.get("tablas", []):
        refs = set(o.lower() for o in t.get("origenes", []))
        refs |= {".".join(m).lower() for m in REF_TABLA.findall(t.get("sql", ""))}
        if PROHIBIDO_FUENTE.search(t.get("sql", "")):
            hallazgos.append(f"{t['nombre']}: lectura directa de fuente/ruta")
        for r in refs:
            partes = r.split(".")
            esq = partes[-2] if len(partes) >= 2 else ""
            if not esquema_permitido(capa, esq):
                hallazgos.append(f"{t['nombre']}: {capa} lee {r} (no permitido)")
    return {"conforme": not hallazgos, "hallazgos": hallazgos}

# ---------------------------------------------------------------- orquestación
def proponer(capa, contexto, propuesta_silver=None, reintentos=2):
    system = INSTRUCCIONES.format(capa=capa, catalogo=CAT, reglas=leer_archivo("estandares/reglas_origen_capas.yml"),
                                  estandar=leer_archivo("estandares/estandar_modelado.md"))
    if capa == "silver":
        user = "PAQUETE DE CONTEXTO (Bronce y referencia):\n" + json.dumps(contexto, ensure_ascii=False)
    else:
        resumen_silver = [{"tabla": f"{CAT}.clientes_pn_silver.{t['nombre']}", "descripcion": t.get("descripcion"), "grano": t.get("grano"),
                           "patron_carga": t.get("patron_carga"),
                           "columnas": [{"nombre": c["nombre"], "tipo": c.get("tipo"), "sensibilidad_pii": c.get("sensibilidad_pii")} for c in t.get("columnas", [])]}
                          for t in propuesta_silver["tablas"]]
        extra = ("\nNOTA: las tablas SCD2 tienen columnas __START_AT y __END_AT; el registro vigente cumple __END_AT IS NULL."
                 "\nGold NO puede leer Bronce ni referencia: usa solo estas tablas Silver.")
        user = "TABLAS SILVER DISPONIBLES (única fuente permitida para Gold):\n" + json.dumps(resumen_silver, ensure_ascii=False) + extra
    ultimo_error = None
    for intento in range(reintentos + 1):
        u = user if not ultimo_error else user + f"\n\nTu respuesta anterior fue rechazada: {ultimo_error}. Corrige y responde solo JSON."
        texto = llamar_modelo(system, u)
        try:
            prop = extraer_json(texto)
        except Exception as e:
            ultimo_error = f"JSON inválido ({e})"; continue
        prop["capa"] = capa
        score = respeta_origen_capas(prop)
        if score["conforme"]:
            return prop, score, intento, hashlib.sha256((system + user).encode()).hexdigest()[:16]
        ultimo_error = "viola reglas de origen: " + "; ".join(score["hallazgos"])
    return prop, score, intento, hashlib.sha256((system + user).encode()).hexdigest()[:16]

def guardar(propuestas):
    run_sql(f"""CREATE TABLE IF NOT EXISTS {CAT}.estandares.propuestas_modelo (
      id_propuesta STRING, id_ejecucion STRING, capa STRING, modelo STRING, fecha_generacion TIMESTAMP,
      hash_prompt STRING, reintentos INT, respeta_origen_capas BOOLEAN, hallazgos_origen STRING,
      propuesta_json STRING, estado STRING)
      COMMENT 'Propuestas de modelos Silver/Gold generadas por el agente de modelado IA. Estado inicial PENDIENTE_REVISION (revisión humana obligatoria).'""")
    for p in propuestas:
        esc = lambda s: s.replace("\\", "\\\\").replace("'", "\\'")
        run_sql(f"""INSERT INTO {CAT}.estandares.propuestas_modelo VALUES ('{p['id']}', '{p['ejecucion']}', '{p['capa']}', '{MODELO}',
          current_timestamp(), '{p['hash']}', {p['reintentos']}, {str(p['score']['conforme']).lower()}, '{esc(json.dumps(p['score']['hallazgos'], ensure_ascii=False))}',
          '{esc(json.dumps(p['propuesta'], ensure_ascii=False))}', 'PENDIENTE_REVISION')""")

def ejecutar(directorio_salida=None):
    ejec = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    ctx = paquete_contexto()
    assert all("valores_frecuentes" not in c for t in ctx["bronce"] for c in t["columnas"] if c["posible_pii"]), "PII en paquete"
    resultados = []
    silver, s_score, s_rei, s_hash = proponer("silver", ctx)
    resultados.append({"id": f"{ejec}-silver", "ejecucion": ejec, "capa": "silver", "propuesta": silver, "score": s_score, "reintentos": s_rei, "hash": s_hash})
    gold, g_score, g_rei, g_hash = proponer("gold", ctx, propuesta_silver=silver)
    resultados.append({"id": f"{ejec}-gold", "ejecucion": ejec, "capa": "gold", "propuesta": gold, "score": g_score, "reintentos": g_rei, "hash": g_hash})
    guardar(resultados)
    if directorio_salida:
        os.makedirs(directorio_salida, exist_ok=True)
        json.dump(ctx, open(os.path.join(directorio_salida, "paquete_contexto.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        for r in resultados:
            json.dump(r, open(os.path.join(directorio_salida, f"propuesta_{r['capa']}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    for r in resultados:
        print(f"[{r['capa']}] tablas={[t['nombre'] for t in r['propuesta'].get('tablas', [])]} conforme={r['score']['conforme']} reintentos={r['reintentos']}")
    return resultados

if __name__ == "__main__":
    ejecutar(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "salidas"))
