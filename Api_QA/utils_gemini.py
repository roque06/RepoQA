import streamlit as st
import requests
import certifi
import re
import csv
import io
import csv
import io
import os
import argparse
import streamlit as st
import pandas as pd
import time

# utils_gemini.py
from typing import List, Dict

SYSTEM_PROMPT_ES = """Eres un analista QA senior. A partir del contexto, genera escenarios de prueba sÃ³lidos:
- Cubre flujo feliz, errores, bordes y no-funcionales (performance, seguridad, accesibilidad).
- Formato tabla: ID, TÃ­tulo, Precondiciones, Pasos, Resultado Esperado, Tipo, Prioridad, Datos de Prueba.
- Referencia evidencia con [SRC:<sha1_8|filename>] cuando corresponda.
- Si falta info, marca ASUMIDO con breve justificaciÃ³n.
"""

def _build_prompt(contexto: str, metas: List[Dict]) -> str:
    src = ""
    if metas:
        src = "Fuentes procesadas:\n" + "\n".join(
            f"- {m['filename']} [{m['sha1_8']}] ({m['ext']}, {m['size_bytes']} bytes)" for m in metas
        ) + "\n"
    cuerpo = contexto[:400_000] + ("...\n(truncado)" if len(contexto) > 400_000 else "")
    return f"{SYSTEM_PROMPT_ES}\n{src}\nContexto combinado:\n{cuerpo}"

def generar_escenarios_desde_contexto(contexto_total: str, metas: List[Dict] = None) -> str:
    prompt = _build_prompt(contexto_total, metas or [])
    # TODO: aquÃ­ invocas tu cliente Gemini real (ejemplo):
    # return gemini_client.generate_text(prompt=prompt, model="gemini-1.5-pro")
    return f"[DEBUG] Prompt de {len(prompt)} caracteres enviado a Gemini."





def prompt_generar_escenarios_profesionales(
    descripcion_refinada,
    contexto_original="",
    target_cases=20,
    min_cases=8,
    titulos_excluir=None
):
    descripcion_refinada = limitar_texto_para_gemini(descripcion_refinada, max_chars=7000)
    contexto_original = limitar_texto_para_gemini(contexto_original or "", max_chars=8000)

    prompt_text = f"""
Eres un QA Senior especialista en pruebas funcionales y de negocio para sistemas financieros.

Devuelve SOLO CSV puro con encabezado exacto y estas columnas:
Title,Preconditions,Steps,Expected Result,Type,Priority

REGLAS DE SALIDA OBLIGATORIAS:
- NO markdown, NO explicaciones, NO texto fuera del CSV.
- Genera entre {min_cases} y {target_cases} casos (sin contar encabezado).
- Prioriza calidad: no inventes casos irrelevantes solo para llenar cantidad.
- Si el contexto es limitado, devuelve solo los casos realmente justificables.
- Usa comas como separador.
- Encierra SIEMPRE cada celda entre comillas dobles, incluso si no tiene comas.
- NO uses comas fuera de comillas.
- Steps deben estar numerados (1., 2., 3., ...), cada paso en linea separada con \\n dentro de la celda.
- Cada caso debe tener entre 4 y 8 pasos accionables.
- Type solo puede ser: Funcional, Validacion, Integracion, Seguridad, Usabilidad.
- Priority solo puede ser: Alta, Media, Baja.
- En Type y Priority no agregues texto extra, comas ni saltos de linea.
- En Title NO uses prefijos de enumeracion ni labels tecnicos: prohibido "SCENARIO", "Escenario", "Caso #", "TC-", numeros al inicio o codigos.
- En Title usa estilo natural QA: frases cortas y especificas como "Validacion de ...", "Regla: ...", "Reestructuracion ...", "Integracion ...".

OBJETIVO DE COBERTURA (adaptar al contexto real):
- Flujo feliz end-to-end.
- Validaciones de campos y formatos.
- Reglas de negocio y calculos.
- Limites y valores frontera.
- Integracion y fallas de servicios/dependencias.
- Seguridad y permisos por rol.
- Usabilidad/mensajeria de error/persistencia.
Si alguna categoria no aplica al contexto, no fuerces casos artificiales.

CRITERIO PROFESIONAL DE CALIDAD:
- Evita casos duplicados o vagos.
- Cada caso debe tener un objetivo unico y verificable.
- Expected Result debe ser medible y especifico (estado, calculo, mensaje o efecto en datos).
- Incluye variantes de datos y combinaciones de parametros (montos, tasas, plazos, gradientes, periodicidad, perfiles, estados).
- Incluye escenarios negativos realistas (datos invalidos, reglas incumplidas, timeout, dependencias caidas).
- Incluye casos de trazabilidad/auditoria cuando aplique.

PRECONDITIONS (obligatorio):
- Enumeradas en lineas separadas dentro de la misma celda (1., 2., 3...).
- Deben cubrir: disponibilidad del sistema, permisos del usuario, datos de negocio y estado de servicios dependientes.
- Prohibido usar: Ninguna, N/A, o precondiciones genericas sin datos concretos.

PRIORIZACION:
- Alta para riesgos de negocio, calculo financiero, integridad de datos, seguridad y fallas de integracion.
- Media/Baja para variantes de menor impacto.

Contexto funcional refinado:
{descripcion_refinada}

Contexto original (fragmento para no perder detalle):
{contexto_original}
""".strip()

    if titulos_excluir:
        lista = "\n".join(f"- {t}" for t in titulos_excluir[:80])
        prompt_text += (
            "\n\nNO REPITAS estos titulos ya generados previamente:\n"
            f"{lista}\n"
            "Si un titulo es similar, crea una variante realmente distinta."
        )

    return {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt_text
                    }
                ]
            }
        ]
    }


def prompt_sugerencias_mejora(texto_funcional):
    return {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "ActÃºa como Analista QA Senior.\n"
                            "Analiza el siguiente texto funcional y genera entre 5 y 10 sugerencias claras para mejorarlo, "
                            "enfocÃ¡ndote en facilitar la generaciÃ³n de escenarios de prueba automatizados.\n\n"
                            "ðŸŽ¯ Las sugerencias deben centrarse en:\n"
                            "- Claridad y especificidad tÃ©cnica\n"
                            "- InclusiÃ³n de validaciones de campos\n"
                            "- Casos lÃ­mite o alternativos\n"
                            "- Precondiciones explÃ­citas del sistema o del usuario\n"
                            "- Mejorar la redacciÃ³n hacia comportamiento verificable\n\n"
                            f"ðŸ“„ Texto funcional:\n{texto_funcional}"
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

    # Separar por lÃ­neas o viÃ±etas
    sugerencias = [
        linea.strip("â€¢-1234567890. ") for linea in texto_sugerencias.strip().split("\n")
        if len(linea.strip()) > 5
    ]

    return sugerencias



def respuesta_es_valida(respuesta_json: dict) -> bool:
    """
    Verifica si la respuesta de Gemini contiene la estructura esperada.
    """
    return (
        isinstance(respuesta_json, dict)
        and "candidates" in respuesta_json
        and len(respuesta_json["candidates"]) > 0
        and "content" in respuesta_json["candidates"][0]
        and "parts" in respuesta_json["candidates"][0]["content"]
    )



def extraer_texto_de_respuesta_gemini(respuesta_json: dict) -> str:
    """
    Extrae texto plano desde respuesta Gemini JSON.
    Remueve bloques markdown y limpia espacios innecesarios.
    """
    try:
        texto = respuesta_json['candidates'][0]['content']['parts'][0]['text']

        # Quitar bloques Markdown ```csv ```
        if '```csv' in texto:
            texto = texto.split('```csv')[1]
        if '```' in texto:
            texto = texto.split('```')[0]

        # Limpiar lÃ­neas vacÃ­as y espacios extras
        lineas = [line.strip() for line in texto.strip().splitlines() if line.strip()]
        return "\n".join(lineas)

    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"âŒ No se pudo extraer texto de Gemini: {e}")

def generar_prompt_csv_robusto(texto_funcional):
    prompt = f"""
ActÃºa como un analista de QA experto.

Genera 3 escenarios de prueba funcionales en formato CSV, usando exactamente estas columnas:
Title,Preconditions,Steps,Expected Result,Type,Priority

âš ï¸ Instrucciones estrictas:
- No expliques nada.
- No uses formato Markdown.
- Usa comas como separadores.
- Cada lÃ­nea debe tener contenido realista, tÃ©cnico y profesional.
- Sin encabezados duplicados. Solo la tabla.

Texto funcional:
\"\"\"{texto_funcional}\"\"\"
    """.strip()
    return prompt


def validar_respuesta_gemini(texto_csv, columnas_esperadas=6):
    lineas = texto_csv.strip().split("\n")
    casos_validos = []

    for i, linea in enumerate(lineas):
        partes = [p.strip() for p in linea.split(",")]
        if len(partes) == columnas_esperadas and all(partes):
            casos_validos.append(linea)

    return casos_validos


def invocar_con_reintento(prompt, max_intentos=3, espera_inicial=2):
    from utils_gemini import llamar_a_gemini
    import time

    for intento in range(1, max_intentos + 1):
        try:
            resultado = llamar_a_gemini(prompt)
            if isinstance(resultado, tuple):
                resultado = resultado[0]
            return resultado
        except ValueError as e:
            if "503" in str(e) and intento < max_intentos:
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
        keys_multiples = [k.strip() for k in keys_multiples.split(",") if k.strip()]

    if isinstance(keys_multiples, list):
        for key in keys_multiples:
            if isinstance(key, str) and key.strip():
                keys.append(key.strip())

    dedup = []
    vistos = set()
    for key in keys:
        if key not in vistos:
            vistos.add(key)
            dedup.append(key)

    if not dedup:
        raise ValueError("No hay gemini_api_key configurada en .streamlit/secrets.toml.")

    return dedup


def _obtener_modelos_gemini():
    modelos = []

    modelo_unico = st.secrets.get("gemini_model", "")
    if isinstance(modelo_unico, str) and modelo_unico.strip():
        modelos.append(modelo_unico.strip())

    modelos_multiples = st.secrets.get("gemini_models", [])
    if isinstance(modelos_multiples, str):
        modelos_multiples = [m.strip() for m in modelos_multiples.split(",") if m.strip()]

    if isinstance(modelos_multiples, list):
        for modelo in modelos_multiples:
            if isinstance(modelo, str) and modelo.strip():
                modelos.append(modelo.strip())

    if not modelos:
        modelos = ["gemini-2.5-flash", "gemini-2.0-flash"]

    dedup = []
    vistos = set()
    for modelo in modelos:
        if modelo not in vistos:
            vistos.add(modelo)
            dedup.append(modelo)

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
                violations = item.get("violations", [])
                if isinstance(violations, list) and violations and not metrica:
                    first = violations[0]
                    if isinstance(first, dict):
                        metrica = (
                            str(first.get("quotaMetric", "")).strip()
                            or str(first.get("quota_metric", "")).strip()
                        )
                tipo = str(item.get("@type", "")).strip()
                if "RetryInfo" in tipo and retry_seconds is None:
                    retry_delay = str(item.get("retryDelay", "")).strip()
                    m_retry = re.search(r"(\d+(?:\.\d+)?)s", retry_delay)
                    if m_retry:
                        retry_seconds = max(1, int(round(float(m_retry.group(1)))))
        if mensaje and not metrica:
            m = re.search(r"Quota exceeded for metric:\s*([^,\s]+)", mensaje)
            if m:
                metrica = m.group(1)
        if retry_seconds is None and mensaje:
            m_wait = re.search(r"Please retry in\s+(\d+(?:\.\d+)?)s", mensaje, flags=re.IGNORECASE)
            if m_wait:
                retry_seconds = max(1, int(round(float(m_wait.group(1)))))
    except Exception:
        pass

    try:
        detalle = response.text[:500]
    except Exception:
        detalle = ""

    return status, mensaje, razon, metrica, detalle, retry_seconds


def _es_cuota_agotada(mensaje_error: str) -> bool:
    if not mensaje_error:
        return False
    txt = mensaje_error.lower()
    return (
        "quota exceeded" in txt
        or "exceeded your current quota" in txt
        or "free_tier_input_token_count" in txt
    )


def enviar_a_gemini(prompt_dict, max_intentos=4, espera_inicial=2):
    api_keys = _obtener_api_keys_gemini()
    modelos = _obtener_modelos_gemini()
    estados_reintentables = {429, 500, 502, 503, 504}
    ultimo_error = None

    for modelo in modelos:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"

        for idx_key, api_key in enumerate(api_keys, start=1):
            headers = {
                "Content-Type": "application/json",
                "X-goog-api-key": api_key,
            }
            for intento in range(1, max_intentos + 1):
                response = None
                try:
                    response = requests.post(url, headers=headers, json=prompt_dict, timeout=60)
                    response.raise_for_status()
                    return response.json()
                except requests.exceptions.HTTPError as e:
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
                                "Probando siguiente key..."
                            )
                            break
                        raise ValueError(f"Error HTTP al invocar Gemini ({status}): {mensaje}")

                    if status == 429 and _es_cuota_agotada(mensaje):
                        if not ultimo_intento and retry_seconds:
                            st.warning(
                                f"Gemini alcanzó limite temporal de cuota ({metrica or 'quota'}). "
                                f"Reintentando en {retry_seconds}s..."
                            )
                            time.sleep(retry_seconds)
                            continue

                        ultimo_error = (
                            "Error HTTP 429: cuota agotada para el proyecto/key actual. "
                            f"Metrica: {metrica or 'desconocida'}. Modelo: {modelo}."
                        )
                        if hay_mas_keys:
                            st.warning(
                                f"Cuota agotada en key {idx_key}/{len(api_keys)} (modelo {modelo}). "
                                "Probando siguiente key..."
                            )
                            break
                        if hay_mas_modelos:
                            st.warning(
                                f"Cuota agotada en modelo {modelo}. Probando siguiente modelo..."
                            )
                            break
                        raise ValueError(
                            "Error HTTP al invocar Gemini (429): cuota agotada. "
                            f"Metrica: {metrica or 'desconocida'}. Mensaje: {mensaje}"
                        )

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
                            f"Gemini devolvio {status}. Reintentando en {espera}s "
                            f"(intento {intento}/{max_intentos}, key {idx_key}/{len(api_keys)}, modelo {modelo})..."
                        )
                        time.sleep(espera)
                        continue

                    raise ValueError(
                        f"Error HTTP al invocar Gemini ({status}): {mensaje or e}. Detalle: {detalle}"
                    )
                except requests.exceptions.Timeout:
                    if intento < max_intentos:
                        espera = espera_inicial * (2 ** (intento - 1))
                        st.warning(
                            f"Timeout al invocar Gemini. Reintentando en {espera}s "
                            f"(intento {intento}/{max_intentos}, key {idx_key}/{len(api_keys)}, modelo {modelo})..."
                        )
                        time.sleep(espera)
                        continue
                    ultimo_error = "Timeout al invocar Gemini tras varios intentos."
                    break
                except Exception as e:
                    raise ValueError(f"Error general al invocar Gemini: {e}")

    raise ValueError(ultimo_error or "Gemini no respondio tras varios intentos.")


def limitar_texto_para_gemini(texto_funcional: str, max_chars: int = 18000) -> str:
    """Reduce el contexto para evitar agotar cuota de tokens en free tier."""
    if not texto_funcional:
        return ""
    texto = texto_funcional.strip()
    if len(texto) <= max_chars:
        return texto
    return texto[:max_chars] + "\n\n[TRUNCADO_POR_LIMITE_DE_CUOTA]"


def prompt_refinar_descripcion(texto_funcional):
    return {
        "contents": [{
            "parts": [{
                "text": (
                    "Eres un analista experto en QA. Debes reestructurar claramente la siguiente descripciÃ³n funcional "
                    "en formato tÃ©cnico y profesional, preparÃ¡ndola para que luego se generen escenarios de prueba. "
                    "Obligatoriamente incluye estas tres secciones claramente separadas y completas:\n\n"
                    "- MÃ³dulo: (Nombre breve del mÃ³dulo o componente involucrado)\n"
                    "- FunciÃ³n: (AcciÃ³n principal que permite esta funcionalidad)\n"
                    "- Detalle tÃ©cnico del comportamiento esperado: (Breve pero clara descripciÃ³n tÃ©cnica de cÃ³mo deberÃ­a funcionar exactamente la funcionalidad)\n\n"
                    "ðŸ“Œ Ejemplo claro:\n"
                    "- MÃ³dulo: Registro de usuarios\n"
                    "- FunciÃ³n: Permitir que usuarios nuevos se registren\n"
                    "- Detalle tÃ©cnico del comportamiento esperado: El formulario validarÃ¡ campos obligatorios como usuario, correo y contraseÃ±a. Se mostrarÃ¡ un mensaje de Ã©xito al completar correctamente el registro y mensajes especÃ­ficos en caso de error en cualquier validaciÃ³n.\n\n"
                    f"âš ï¸ Ahora reestructura profesionalmente el siguiente texto:\n\n{texto_funcional}"
                )
            }]
        }]
    }

def obtener_descripcion_refinada(texto_funcional, max_intentos=3):
    texto_ajustado = limitar_texto_para_gemini(texto_funcional, max_chars=18000)
    if texto_funcional and len(texto_ajustado) < len(texto_funcional):
        st.warning(
            "⚠️ El texto de entrada es muy largo para la cuota actual. "
            "Se envio una version recortada para reducir consumo de tokens."
        )
    intentos = 0
    while intentos < max_intentos:
        respuesta_estructurada = enviar_a_gemini(prompt_refinar_descripcion(texto_ajustado))
        descripcion_refinada = extraer_texto_de_respuesta_gemini(respuesta_estructurada).strip()

        if descripcion_refinada:
            return descripcion_refinada

        intentos += 1
        time.sleep(1)  # pequeÃ±o retardo antes de reintentar

    # si llega aquÃ­, todos los intentos fallaron

    raise ValueError("âš ï¸ Gemini no devolviÃ³ descripciÃ³n vÃ¡lida tras varios intentos.")

