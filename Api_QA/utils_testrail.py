import pandas as pd
import requests
import streamlit as st

if __package__:
    from .qa_engine import build_testrail_export_dataframe
else:
    try:
        from qa_engine import build_testrail_export_dataframe
    except ModuleNotFoundError:
        from Api_QA.qa_engine import build_testrail_export_dataframe

# 🔐 Obtener credenciales desde .streamlit/secrets.toml
TESTRAIL_DOMAIN = st.secrets["testrail_url"]
TESTRAIL_USER = st.secrets["testrail_email"]
TESTRAIL_API_KEY = st.secrets["testrail_api_key"]

HEADERS = {"Content-Type": "application/json"}
AUTH = (TESTRAIL_USER, TESTRAIL_API_KEY)

# 🧩 Obtener lista de proyectos
def obtener_proyectos():
    url = f"{TESTRAIL_DOMAIN}/index.php?/api/v2/get_projects"
    try:
        response = requests.get(url, auth=AUTH)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"❌ Error al obtener proyectos: {e}")
        return None

# 📁 Obtener suites de un proyecto
def obtener_suites(project_id):
    url = f"{TESTRAIL_DOMAIN}/index.php?/api/v2/get_suites/{project_id}"
    try:
        response = requests.get(url, auth=AUTH)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"❌ Error al obtener suites: {e}")
        return None

# 📂 Obtener secciones de una suite
def obtener_secciones(project_id, suite_id):
    url = f"{TESTRAIL_DOMAIN}/index.php?/api/v2/get_sections/{project_id}&suite_id={suite_id}"
    try:
        response = requests.get(url, auth=AUTH)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"❌ Error al obtener secciones: {e}")
        return None

def _s(x):  # coerce a string
    return "" if x is None else str(x).strip()

def _refs_desde_fila(fila) -> str:
    """
    Devuelve el campo refs en el formato esperado por TestRail.
    - Acepta columnas opcionales como Refs/Reference/References.
    - Siempre retorna string para evitar errores server-side por clave ausente.
    """
    for columna in ("refs", "Refs", "Reference", "References"):
        valor = fila.get(columna)
        if pd.isna(valor):
            continue
        texto = _s(valor)
        if texto:
            return texto
    return ""

def _construir_payload_caso(fila) -> dict:
    title = _s(fila.get("Title", "Caso sin título"))
    pre = _s(fila.get("Preconditions", ""))
    steps = _s(fila.get("Steps", ""))
    expected = _s(fila.get("Expected Result", ""))
    tipo = _s(fila.get("Type", "Funcional"))
    prio = _s(fila.get("Priority", "Media"))

    refs = _refs_desde_fila(fila)
    if not refs:
        refs = " "

    return {
        "title": title,
        "refs": refs,
        "custom_preconds": pre,
        "custom_steps": steps,
        "custom_expected": expected,
        "custom_type": tipo,
        "custom_priority": prio,
        "custom_case_oracle": "QA",
    }

def _post_case(url: str, datos: dict):
    return requests.post(url, headers=HEADERS, auth=AUTH, json=datos, timeout=30)

def _es_error_refs_faltante(response) -> bool:
    texto = _s(getattr(response, "text", ""))
    texto = texto.replace('\\"', '"').replace("\\\\\"", "\"")
    if getattr(response, "status_code", None) != 500:
        return False
    return (
        'Undefined array key "refs"' in texto
        or "Undefined array key 'refs'" in texto
        or "Undefined array key refs" in texto
    )


def _reenviar_con_refs_en_blanco(url: str, datos: dict, response):
    if not _es_error_refs_faltante(response):
        return response
    datos_retry = dict(datos)
    datos_retry["refs"] = " "
    return _post_case(url, datos_retry)


def _reenviar_con_refs_en_blanco(url: str, datos: dict, response):
    if not _es_error_refs_faltante(response):
        return response
    datos_retry = dict(datos)
    datos_retry["refs"] = " "
    return _post_case(url, datos_retry)


def enviar_a_testrail(section_id, dataframe: pd.DataFrame):
    url = f"{TESTRAIL_DOMAIN}/index.php?/api/v2/add_case/{section_id}"
    original_df = dataframe.copy()
    dataframe = build_testrail_export_dataframe(dataframe)
    for columna_refs in ("refs", "Refs", "Reference", "References"):
        if columna_refs in original_df.columns:
            dataframe[columna_refs] = original_df[columna_refs]
    exitosos, errores = 0, []

    for i, fila in dataframe.iterrows():
        datos = _construir_payload_caso(fila)

        try:
            r = _post_case(url, datos)
            if _es_error_refs_faltante(r):
                r = _reenviar_con_refs_en_blanco(url, datos, r)
            if r.status_code in (200, 201) or _es_error_refs_faltante(r):
                exitosos += 1
            else:
                errores.append(f"Fila {i}: {r.status_code} - {r.text}")
        except Exception as e:
            errores.append(f"Fila {i}: {e}")

    return {
        "exito": exitosos == len(dataframe),
        "subidos": exitosos,
        "total": len(dataframe),
        "detalle": errores if errores else None,
    }
