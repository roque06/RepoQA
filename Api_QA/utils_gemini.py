from __future__ import annotations

import re
import time
from typing import Dict, List, Optional

import requests
import streamlit as st

if __package__:
    from .qa_engine import summarize_analysis_for_prompt
else:
    from qa_engine import summarize_analysis_for_prompt


SYSTEM_PROMPT_ES = """Eres un Arquitecto QA Senior especializado en transformar documentos heterogéneos en escenarios de prueba profesionales.
Tu trabajo no es copiar el documento, sino interpretarlo con criterio funcional, técnico y de riesgo para producir cobertura QA útil en un entorno real."""


# Modelos definidos localmente, sin depender de secrets.
# Ajusta el orden según tu preferencia de prioridad.
MODELOS_GEMINI = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]


def generar_escenarios_desde_contexto(contexto_total: str, metas: Optional[List[Dict]] = None) -> str:
    """
    Compatibilidad hacia atrás para módulos que todavía importan esta función.
    Mantiene una interfaz estable mientras el flujo principal usa el pipeline
    nuevo basado en análisis + JSON.
    """
    metas = metas or []
    resumen_fuentes = ""
    if metas:
        resumen_fuentes = "Fuentes procesadas:\n" + "\n".join(
            f"- {meta.get('filename', 'fuente')} [{meta.get('sha1_8', 'sin_hash')}]"
            for meta in metas
        )
    contexto = limitar_texto_para_gemini(contexto_total or "", max_chars=4000)
    return "\n\n".join(part for part in [SYSTEM_PROMPT_ES, resumen_fuentes, contexto] if part).strip()


def _json_schema_hint() -> str:
    return """
Devuelve SOLO JSON válido con esta estructura exacta:
{
  "document_type": "UI/Formulario | API | Workflow/Proceso | Integración | Reporte/Consulta | Financiero/Contable | Mixto",
  "functional_summary": {
    "module_or_process": "",
    "actors": [""],
    "business_rules": [""],
    "validations": [""],
    "integrations": [""],
    "calculations": [""],
    "risks": [""],
    "assumptions": [""],
    "coverage_focus": [""],
    "functional_blocks": [""]
  },
  "test_scenarios": [
    {
      "title": "",
      "preconditions": "1. ...\\n2. ...",
      "steps": "1. ...\\n2. ...\\n3. ...\\n4. ...",
      "expected_result": "",
      "type": "Funcional | Validacion | Integracion | Seguridad | Usabilidad",
      "priority": "Alta | Media | Baja",
      "source_basis": "explicito | inferido",
      "assumption": ""
    }
  ]
}
""".strip()


def prompt_generar_escenarios_profesionales(
    descripcion_refinada: str,
    contexto_original: str = "",
    target_cases: Optional[int] = 20,
    min_cases: Optional[int] = 8,
    titulos_excluir: Optional[List[str]] = None,
    analisis_documento: Optional[Dict] = None,
):
    descripcion_refinada = limitar_texto_para_gemini(descripcion_refinada, max_chars=9000)
    contexto_original = limitar_texto_para_gemini(contexto_original or "", max_chars=12000)
    analisis_documento = analisis_documento or {}
    document_type = analisis_documento.get("document_type", "Workflow/Proceso")
    analysis_summary = (
        summarize_analysis_for_prompt(analisis_documento)
        if analisis_documento
        else "- No se recibió análisis estructurado."
    )
    functional_blocks = analisis_documento.get("functional_blocks", []) if analisis_documento else []
    volume = analisis_documento.get("scenario_volume", {}) if analisis_documento else {}

    coverage_rules = {
        "API": "Incluye autenticación/autorización, códigos HTTP, validación de schema, contratos, idempotencia, manejo de errores y resiliencia.",
        "UI/Formulario": "Incluye flujo visible, validaciones de campos, mensajes, persistencia, reglas por rol, navegación y usabilidad.",
        "Workflow/Proceso": "Incluye estados, transiciones, aprobaciones, rechazos, permisos, restricciones y cambios visibles de estado.",
        "Integración": "Incluye timeout, servicio no disponible, datos incompletos, errores controlados y reintentos cuando aplique.",
        "Reporte/Consulta": "Incluye generación, filtros, consistencia de datos, visualización y exportación cuando corresponda.",
        "Financiero/Contable": "Incluye cálculos, redondeos, comisiones, reversos, consistencia y trazabilidad solo cuando el documento lo requiera.",
        "Mixto": "Combina cobertura funcional, workflow, integración, reportes, validaciones visibles y resiliencia entre componentes según la evidencia del documento.",
    }

    target_label = target_cases if isinstance(target_cases, int) else int(volume.get("target", 20) or 20)
    min_label = min_cases if isinstance(min_cases, int) else int(volume.get("minimum", 8) or 8)

    prompt_text = f"""
{SYSTEM_PROMPT_ES}

Interpreta cualquier documento como un insumo QA profesional.
Está PROHIBIDO generar escenarios cuyo objetivo principal sea configuración técnica, parametrización, setup, catálogo interno, mapeos o mantenimiento administrativo.
Cuando el documento contenga detalles técnicos, tradúcelos a comportamiento del sistema, impacto para el usuario, controles del negocio, integraciones observables y reglas verificables.

Tipo de documento detectado: {document_type}
Cobertura adaptativa obligatoria: {coverage_rules.get(document_type, coverage_rules['Workflow/Proceso'])}
Bloques funcionales detectados: {", ".join(functional_blocks) if functional_blocks else "No explícitos"}

Análisis estructurado previo del documento:
{analysis_summary}

Requisitos obligatorios de calidad:
- Genera entre {min_label} y {target_label} escenarios solo si están justificados por el contexto.
- Si el documento contiene múltiples bloques funcionales, cubre cada bloque relevante con escenarios suficientes; no resumas todo en unos pocos casos.
- Cada escenario debe ser atómico: un objetivo verificable principal.
- El resultado esperado debe ser medible, visible o auditable.
- Diferencia explícitamente escenarios basados en evidencia directa (source_basis=explicito) frente a inferencias razonables de QA (source_basis=inferido).
- Si un escenario es inferido y depende de una condición no explícita, llena assumption con una frase breve; si no aplica, deja assumption vacío.
- No incluyas códigos internos, IDs, cuentas, productos, subtransacciones ni contenido entre paréntesis.
- No repitas escenarios semánticamente equivalentes.
- Mantén el lenguaje profesional de QA y enfocado en comportamiento funcional.
- No generes explicaciones fuera del JSON.

Criterios específicos de cobertura inteligente:
- Si hay formularios o UI: validaciones de obligatoriedad, formato, mensajes, persistencia, navegación y permisos.
- Si hay API: auth, códigos HTTP, payloads, schema, errores funcionales, timeouts y resiliencia.
- Si hay lógica financiera o contable: cálculos, redondeos, reversos, asientos/impacto visible y consistencia de saldos.
- Si hay integraciones: fallas del servicio, reintentos, degradación controlada, consistencia y trazabilidad.
- Si hay reportes o consultas: filtros, consistencia, orden, paginación y exactitud de datos.
- No fuerces categorías irrelevantes para el documento.
- No priorices contabilidad, cálculos, reversos o trazabilidad financiera salvo que el documento lo indique explícitamente.

Restricciones de redacción:
- title debe ser claro, específico y sin prefijos como Escenario, Caso, TC o numeraciones.
- preconditions y steps deben venir numerados dentro del string.
- steps debe contener entre 4 y 8 pasos accionables, salvo que el contexto justifique menos.
- type solo puede ser Funcional, Validacion, Integracion, Seguridad o Usabilidad.
- priority solo puede ser Alta, Media o Baja.
- El JSON debe ser parseable con json.loads sin limpieza adicional.
- El expected_result debe describir el comportamiento observable del sistema, incluyendo validación, cambio de estado, persistencia, respuesta, mensaje o visualización cuando aplique.

{_json_schema_hint()}

Contexto funcional refinado:
{descripcion_refinada}

Contexto original de soporte:
{contexto_original}
""".strip()

    if titulos_excluir:
        prompt_text += "\n\nNo repitas títulos ya utilizados:\n" + "\n".join(
            f"- {titulo}" for titulo in titulos_excluir[:80]
        )

    return {"contents": [{"parts": [{"text": prompt_text}]}]}


def prompt_sugerencias_mejora(texto_funcional):
    return {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "Actúa como Analista QA Senior.\n"
                            "Analiza el siguiente texto funcional y genera entre 5 y 10 sugerencias claras para mejorarlo, "
                            "enfocándote en facilitar la generación de escenarios de prueba automatizados.\n\n"
                            "Las sugerencias deben centrarse en:\n"
                            "- Claridad y especificidad técnica\n"
                            "- Inclusión de validaciones de campos\n"
                            "- Casos límite o alternativos\n"
                            "- Precondiciones explícitas del sistema o del usuario\n"
                            "- Mejorar la redacción hacia comportamiento verificable\n\n"
                            f"Texto funcional:\n{texto_funcional}"
                        )
                    }
                ]
            }
        ]
    }


def generar_sugerencias_con_gemini(texto_funcional):
    prompt = prompt_sugerencias_mejora(texto_funcional)
    respuesta = enviar_a_gemini(prompt)
    texto_sugerencias = extraer_texto_de_respuesta_gemini(respuesta)
    return [
        linea.strip("•-1234567890. ")
        for linea in texto_sugerencias.strip().split("\n")
        if len(linea.strip()) > 5
    ]


def respuesta_es_valida(respuesta_json: dict) -> bool:
    return (
        isinstance(respuesta_json, dict)
        and "candidates" in respuesta_json
        and len(respuesta_json["candidates"]) > 0
        and "content" in respuesta_json["candidates"][0]
        and "parts" in respuesta_json["candidates"][0]["content"]
    )


def extraer_texto_de_respuesta_gemini(respuesta_json: dict) -> str:
    try:
        texto = respuesta_json["candidates"][0]["content"]["parts"][0]["text"]
        lineas = [line.rstrip() for line in texto.strip().splitlines()]
        return "\n".join(lineas).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"No se pudo extraer texto de Gemini: {exc}") from exc


def generar_prompt_csv_robusto(texto_funcional):
    return (
        "Actúa como un analista de QA experto. "
        "Resume el siguiente texto funcional en escenarios profesionales usando formato JSON estructurado.\n\n"
        f"Texto funcional:\n{texto_funcional}"
    )


def validar_respuesta_gemini(texto_csv, columnas_esperadas=6):
    lineas = texto_csv.strip().split("\n")
    casos_validos = []
    for linea in lineas:
        partes = [p.strip() for p in linea.split(",")]
        if len(partes) == columnas_esperadas and all(partes):
            casos_validos.append(linea)
    return casos_validos


def invocar_con_reintento(prompt, max_intentos=3, espera_inicial=2):
    for intento in range(1, max_intentos + 1):
        try:
            return enviar_a_gemini(prompt, max_intentos=1)
        except ValueError as exc:
            if "503" in str(exc) and intento < max_intentos:
                time.sleep(espera_inicial * intento)
            else:
                raise


def _obtener_api_keys_gemini():
    keys = []

    key_unica = st.secrets.get("gemini_api_key", "")
    if isinstance(key_unica, str) and key_unica.strip():
        keys.append(key_unica.strip())

    keys_multiples = st.secrets.get("gemini_api_keys", [])
    if isinstance(keys_multiples, str):
        keys_multiples = [key.strip() for key in keys_multiples.split(",") if key.strip()]
    if isinstance(keys_multiples, list):
        for key in keys_multiples:
            if isinstance(key, str) and key.strip():
                keys.append(key.strip())

    dedup = []
    seen = set()
    for key in keys:
        if key not in seen:
            seen.add(key)
            dedup.append(key)

    if not dedup:
        raise ValueError("No hay gemini_api_key configurada en .streamlit/secrets.toml.")

    return dedup


def _obtener_modelos_gemini():
    dedup = []
    seen = set()

    for modelo in MODELOS_GEMINI:
        if isinstance(modelo, str) and modelo.strip():
            m = modelo.strip()
            if m not in seen:
                seen.add(m)
                dedup.append(m)

    if not dedup:
        dedup = ["gemini-2.5-flash", "gemini-2.0-flash"]

    return dedup


def _parsear_error_http(response):
    status = response.status_code if response is not None else None
    detalle = ""
    mensaje = ""
    razon = ""
    metrica = ""
    retry_seconds = None

    if response is None:
        return status, mensaje, razon, metrica, detalle, retry_seconds

    try:
        payload = response.json()
        err = payload.get("error", {}) if isinstance(payload, dict) else {}
        mensaje = str(err.get("message", "")).strip()
        details = err.get("details", [])

        if isinstance(details, list):
            for item in details:
                if not isinstance(item, dict):
                    continue

                if not razon:
                    razon = str(item.get("reason", "")).strip()

                metadata = item.get("metadata", {})
                if isinstance(metadata, dict) and not metrica:
                    metrica = (
                        str(metadata.get("quota_metric", "")).strip()
                        or str(metadata.get("metric", "")).strip()
                    )

                tipo = str(item.get("@type", "")).strip()
                if "RetryInfo" in tipo and retry_seconds is None:
                    retry_delay = str(item.get("retryDelay", "")).strip()
                    match = re.search(r"(\d+(?:\.\d+)?)s", retry_delay)
                    if match:
                        retry_seconds = max(1, int(round(float(match.group(1)))))

        if mensaje and not metrica:
            match = re.search(r"Quota exceeded for metric:\s*([^,\s]+)", mensaje)
            if match:
                metrica = match.group(1)

        if retry_seconds is None and mensaje:
            match = re.search(r"Please retry in\s+(\d+(?:\.\d+)?)s", mensaje, flags=re.IGNORECASE)
            if match:
                retry_seconds = max(1, int(round(float(match.group(1)))))
    except Exception:
        pass

    try:
        detalle = response.text[:500]
    except Exception:
        detalle = ""

    return status, mensaje, razon, metrica, detalle, retry_seconds


def _es_cuota_agotada(mensaje_error: str) -> bool:
    txt = (mensaje_error or "").lower()
    return (
        "quota exceeded" in txt
        or "exceeded your current quota" in txt
        or "free_tier_input_token_count" in txt
    )


def construir_mensaje_error_gemini(error: Exception | str) -> str:
    """
    Convierte errores crudos de Gemini en mensajes orientados al usuario final.
    """
    raw = str(error or "").strip()
    txt = raw.lower()

    if "503" in txt and ("high demand" in txt or "unavailable" in txt or "temporarily unavailable" in txt):
        return (
            "Gemini está temporalmente saturado (HTTP 503). "
            "Intenta de nuevo en 30-90 segundos; el pico de demanda suele ser temporal."
        )

    if "429" in txt and _es_cuota_agotada(raw):
        return (
            "Gemini alcanzó el límite de cuota (HTTP 429). "
            "Espera unos minutos o cambia la API key disponible."
        )

    return raw or "Ocurrió un error al invocar Gemini."


def enviar_a_gemini(prompt_dict, max_intentos=4, espera_inicial=2):
    api_keys = _obtener_api_keys_gemini()
    modelos = _obtener_modelos_gemini()
    estados_reintentables = {429, 500, 502, 503, 504}
    ultimo_error = None

    for modelo in modelos:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"

        for idx_key, api_key in enumerate(api_keys, start=1):
            headers = {"Content-Type": "application/json", "X-goog-api-key": api_key}

            for intento in range(1, max_intentos + 1):
                response = None

                try:
                    response = requests.post(url, headers=headers, json=prompt_dict, timeout=60)
                    response.raise_for_status()
                    return response.json()

                except requests.exceptions.HTTPError as exc:
                    status, mensaje, razon, metrica, detalle, retry_seconds = _parsear_error_http(response)
                    ultimo_intento = intento == max_intentos
                    hay_mas_keys = idx_key < len(api_keys)
                    hay_mas_modelos = modelo != modelos[-1]

                    if razon == "API_KEY_INVALID" or "api key expired" in mensaje.lower():
                        ultimo_error = (
                            f"Error HTTP {status}: API key invalida/expirada. "
                            f"Modelo: {modelo}. Detalle: {detalle}"
                        )
                        if hay_mas_keys:
                            st.warning(
                                f"API key {idx_key}/{len(api_keys)} invalida o expirada. "
                                f"Probando siguiente key..."
                            )
                            break
                        if hay_mas_modelos:
                            st.warning(
                                f"Modelo {modelo} no usable con la key actual. "
                                f"Probando siguiente modelo..."
                            )
                            break
                        raise ValueError(f"Error HTTP al invocar Gemini ({status}): {mensaje}") from exc

                    if status == 429 and _es_cuota_agotada(mensaje):
                        if not ultimo_intento and retry_seconds:
                            st.warning(
                                f"Gemini alcanzó límite temporal de cuota ({metrica or 'quota'}). "
                                f"Reintentando en {retry_seconds}s..."
                            )
                            time.sleep(retry_seconds)
                            continue

                        ultimo_error = (
                            f"Error HTTP 429: cuota agotada. "
                            f"Métrica: {metrica or 'desconocida'}. Modelo: {modelo}."
                        )

                        if hay_mas_keys:
                            st.warning(
                                f"Cuota agotada en key {idx_key}/{len(api_keys)} "
                                f"(modelo {modelo}). Probando siguiente key..."
                            )
                            break

                        if hay_mas_modelos:
                            st.warning(
                                f"Cuota agotada en modelo {modelo}. "
                                f"Probando siguiente modelo..."
                            )
                            break

                        raise ValueError(
                            f"Error HTTP al invocar Gemini (429): cuota agotada. "
                            f"Métrica: {metrica or 'desconocida'}. Mensaje: {mensaje}"
                        ) from exc

                    if status in estados_reintentables and not ultimo_intento:
                        retry_after = response.headers.get("Retry-After") if response is not None else None

                        if retry_after:
                            try:
                                espera = max(1, int(round(float(retry_after))))
                            except Exception:
                                espera = espera_inicial * (2 ** (intento - 1))
                        elif retry_seconds:
                            espera = retry_seconds
                        else:
                            espera = espera_inicial * (2 ** (intento - 1))

                        st.warning(
                            f"Gemini devolvió {status}. Reintentando en {espera}s "
                            f"(intento {intento}/{max_intentos}, "
                            f"key {idx_key}/{len(api_keys)}, modelo {modelo})..."
                        )
                        time.sleep(espera)
                        continue

                    if status in {500, 502, 503, 504}:
                        ultimo_error = (
                            f"Error HTTP {status} en modelo {modelo}. "
                            f"Mensaje: {mensaje or detalle}"
                        )

                        if hay_mas_keys:
                            st.warning(
                                f"Gemini devolvió {status} con la key {idx_key}/{len(api_keys)} "
                                f"en modelo {modelo}. Probando siguiente key..."
                            )
                            break

                        if hay_mas_modelos:
                            st.warning(
                                f"Gemini devolvió {status} en modelo {modelo}. "
                                f"Probando siguiente modelo..."
                            )
                            break

                    raise ValueError(
                        f"Error HTTP al invocar Gemini ({status}): {mensaje or exc}. "
                        f"Detalle: {detalle}"
                    ) from exc

                except requests.exceptions.Timeout:
                    if intento < max_intentos:
                        espera = espera_inicial * (2 ** (intento - 1))
                        st.warning(
                            f"Timeout al invocar Gemini. Reintentando en {espera}s "
                            f"(intento {intento}/{max_intentos}, "
                            f"key {idx_key}/{len(api_keys)}, modelo {modelo})..."
                        )
                        time.sleep(espera)
                        continue

                    ultimo_error = f"Timeout al invocar Gemini tras varios intentos en modelo {modelo}."
                    if idx_key < len(api_keys):
                        st.warning(
                            f"Timeout persistente con key {idx_key}/{len(api_keys)} "
                            f"en modelo {modelo}. Probando siguiente key..."
                        )
                        break
                    if modelo != modelos[-1]:
                        st.warning(
                            f"Timeout persistente en modelo {modelo}. "
                            f"Probando siguiente modelo..."
                        )
                        break
                    break

                except Exception as exc:
                    raise ValueError(f"Error general al invocar Gemini: {exc}") from exc

    raise ValueError(ultimo_error or "Gemini no respondió tras varios intentos.")


def limitar_texto_para_gemini(texto_funcional: str, max_chars: int = 18000) -> str:
    if not texto_funcional:
        return ""
    texto = texto_funcional.strip()
    if len(texto) <= max_chars:
        return texto
    return texto[:max_chars] + "\n\n[TRUNCADO_POR_LIMITE_DE_CUOTA]"


def prompt_refinar_descripcion(texto_funcional):
    return {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "Eres un analista experto en QA. Debes reestructurar la siguiente descripción funcional "
                            "de forma técnica y profesional antes de generar escenarios. "
                            "Incluye estas secciones: Módulo, Función, Reglas de negocio, Validaciones, Integraciones y Riesgos QA.\n\n"
                            f"Texto fuente:\n{texto_funcional}"
                        )
                    }
                ]
            }
        ]
    }


def obtener_descripcion_refinada(texto_funcional, max_intentos=3):
    texto_ajustado = limitar_texto_para_gemini(texto_funcional, max_chars=18000)

    if texto_funcional and len(texto_ajustado) < len(texto_funcional):
        st.warning(
            "⚠️ El texto de entrada es muy largo para la cuota actual. "
            "Se envió una versión recortada para reducir consumo de tokens."
        )

    intentos = 0
    while intentos < max_intentos:
        respuesta_estructurada = enviar_a_gemini(prompt_refinar_descripcion(texto_ajustado))
        descripcion_refinada = extraer_texto_de_respuesta_gemini(respuesta_estructurada).strip()
        if descripcion_refinada:
            return descripcion_refinada
        intentos += 1
        time.sleep(1)

    raise ValueError("Gemini no devolvió descripción válida tras varios intentos.")