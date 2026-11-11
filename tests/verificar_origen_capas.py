"""Control ESTÁTICO de reglas de origen por capa (DEMO).
Revisa: (1) el código de src/silver/** y src/gold/** (SQL y Python), (2) las propuestas del agente guardadas en
workspace.estandares.propuestas_modelo (opcional, --propuestas) y (3) casos negativos de tests/casos (deben FALLAR).
Salida: PASS/FAIL por elemento; código de salida 1 si algo conforme no lo es.
"""
import re, sys, pathlib, json, os
import yaml

BASE = pathlib.Path(__file__).resolve().parents[1]
reglas = yaml.safe_load(open(BASE / "estandares/reglas_origen_capas.yml", encoding="utf-8"))
REF = set(reglas["capas"]["referencia"]["esquemas"])
BRONCE = set(reglas["capas"]["bronce"]["esquemas"])
# catalogo.esquema.tabla, con catálogo literal o variable ({CAT}, ${catalogo})
PATRON_FQ = re.compile(r"(?:\{CAT\}|\$\{\w+\}|[\"']\w+)\.(\w+)\.(\w+)[\"']")
PATRON_FROM = re.compile(r"\b(?:FROM|JOIN)\s+(?:STREAM\s*\(\s*)?([\w`${}.]+)", re.I)
PROHIBIDO_FUENTE = re.compile(r"read_files|abfss://|s3://|jdbc|remote_query|/Volumes/|format\(\s*[\"'](?:jdbc|csv|parquet|json)", re.I)

def permitido(capa, esquema):
    if capa == "silver":
        return esquema in BRONCE or esquema in REF or esquema.endswith("_silver")
    if capa == "gold":
        return esquema.endswith("_silver") or esquema.endswith("_gold")
    return True

def referencias(texto, lenguaje):
    refs = set()
    if lenguaje == "sql":
        sin_com = re.sub(r"--[^\n]*", "", texto)
        for r in PATRON_FROM.findall(sin_com):
            partes = r.replace("`", "").split(".")
            if len(partes) >= 3: refs.add((partes[-2], partes[-1]))
    else:
        sin_com = re.sub(r"#[^\n]*", "", texto)
        refs |= set(PATRON_FQ.findall(sin_com))
    return {(e, t) for e, t in refs if not e.lower() in ("sql", "functions")}

def revisar(capa, texto, lenguaje):
    hallazgos = []
    sin_com = re.sub(r"--[^\n]*|#[^\n]*", "", texto)
    if PROHIBIDO_FUENTE.search(sin_com):
        hallazgos.append("lectura directa de fuente o ruta")
    for esq, tab in sorted(referencias(texto, lenguaje)):
        if not permitido(capa, esq):
            hallazgos.append(f"{capa} lee {esq}.{tab}")
    return hallazgos

def main():
    resultados = []
    for capa in ("silver", "gold"):
        for f in sorted((BASE / "src" / capa).rglob("*")):
            if f.suffix in (".sql", ".py"):
                h = revisar(capa, f.read_text(encoding="utf-8"), "sql" if f.suffix == ".sql" else "py")
                resultados.append(("codigo", str(f.relative_to(BASE)), capa, h, True))
    for f in sorted((BASE / "tests" / "casos").glob("*.sql")):
        capa = "gold" if f.name.startswith("gold") else "silver"
        h = revisar(capa, f.read_text(encoding="utf-8"), "sql")
        resultados.append(("caso_negativo", str(f.relative_to(BASE)), capa, h, False))
    if "--propuestas" in sys.argv or os.environ.get("CONTROL_PROPUESTAS") == "1":
        try:
            from pyspark.sql import SparkSession
            sesion = SparkSession.getActiveSession()
        except Exception:
            sesion = None
        if sesion is not None:
            sql = lambda q, show=False: (None, [list(r) for r in sesion.sql(q).collect()])
        else:
            sys.path.insert(0, str(BASE))
            from dbsql import sql
        _, filas = sql("SELECT id_propuesta, capa, propuesta_json FROM workspace.estandares.propuestas_modelo "
                       "QUALIFY row_number() OVER (PARTITION BY capa ORDER BY fecha_generacion DESC) = 1", show=False)
        for idp, capa, pj in filas:
            p = json.loads(pj); h = []
            for t in p.get("tablas", []):
                for o in t.get("origenes", []):
                    partes = o.split(".")
                    if not permitido(capa, partes[-2] if len(partes) >= 2 else ""):
                        h.append(f"{t['nombre']}: origen declarado {o}")
                h += [f"{t['nombre']}: {x}" for x in revisar(capa, t.get("sql", ""), "sql")]
            resultados.append(("propuesta_agente", idp, capa, h, True))
    errores = 0
    for tipo, nombre, capa, h, debe_cumplir in resultados:
        ok = (not h) if debe_cumplir else bool(h)
        errores += 0 if ok else 1
        detalle = "; ".join(h) if h else "sin hallazgos"
        esperado = "" if debe_cumplir else " (se esperaba violación)"
        print(f"{'PASS' if ok else 'FAIL'} | {tipo} | {capa} | {nombre} | {detalle}{esperado}")
    print("RESULTADO CONTROL ESTÁTICO:", "CONFORME" if errores == 0 else f"NO CONFORME ({errores})")
    return 1 if errores else 0

if __name__ == "__main__":
    sys.exit(main())
