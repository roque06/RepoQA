import re

import pandas as pd
import requests
import streamlit as st

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

    # Oráculo breve y distinto del expected
    oracle = _oraculo_breve_sin_duplicar(title, steps, expected)
    if not oracle:
        oracle = "Regla: validar condición de aceptación sin duplicar el resultado esperado."

    return {
        "title": title,
        "refs": _refs_desde_fila(fila),
        "custom_preconds": pre,
        "custom_steps": steps,
        "custom_expected": expected,
        "custom_type": tipo,
        "custom_priority": prio,
        "custom_case_oracle": oracle,  # <- aquí el campo obligatorio
    }

def _post_case(url: str, datos: dict):
    return requests.post(url, headers=HEADERS, auth=AUTH, json=datos, timeout=30)

def _es_error_refs_faltante(response) -> bool:
    texto = _s(response.text).replace('\\"', '"')
    return response.status_code == 500 and 'Undefined array key "refs"' in texto

def _oraculo_breve_sin_duplicar(title: str, steps: str, expected: str) -> str:
    """
    Genera un oráculo corto (regla verificable) que NO sea igual al Expected.
    - Si el expected habla de 'obligatorio'/'no se envía', convertirlo a regla genérica.
    - Si sigue quedando idéntico, usar una regla de validación compacta.
    """
    t = _s(title).lower()
    s = _s(steps).lower()
    e = _s(expected).strip()

    # Heurísticas simples para casos comunes
    if re.search(r"obligatori|requerid", e.lower()) or "no se envía" in e.lower():
        # intenta extraer el campo implicado del título o pasos
        m = re.search(r"(campo|nombre)\s*['“\"]?([^'”\"]+)['”\"]?", t) or \
            re.search(r"(campo|nombre)\s*['“\"]?([^'”\"]+)['”\"]?", s)
        campo = m.group(2) if m else "el campo requerido"
        oracle = f"Regla: si falta {campo}, el formulario debe bloquear el envío y mostrar validación."
    else:
        # Regla general corta basada en título
        oracle = f"Regla: { _s(title) } cumple condición de aceptación sin persistir datos inválidos."

    # Evita igualdad exacta con Expected
    if oracle.strip().lower() == e.strip().lower():
        oracle = "Regla: validar mensaje y bloqueo en ausencia de dato requerido."

    return oracle

def enviar_a_testrail(section_id, dataframe: pd.DataFrame):
    url = f"{TESTRAIL_DOMAIN}/index.php?/api/v2/add_case/{section_id}"
    exitosos, errores = 0, []

    for i, fila in dataframe.iterrows():
        datos = _construir_payload_caso(fila)

        try:
            r = _post_case(url, datos)
            if _es_error_refs_faltante(r) and not datos["refs"]:
                # Compatibilidad defensiva: algunos gateways descartan strings vacíos.
                datos["refs"] = " "
                r = _post_case(url, datos)
            if r.status_code in (200, 201):
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
