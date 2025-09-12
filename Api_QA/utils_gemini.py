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

SYSTEM_PROMPT_ES = """Eres un analista QA senior. A partir del contexto, genera escenarios de prueba sólidos:
- Cubre flujo feliz, errores, bordes y no-funcionales (performance, seguridad, accesibilidad).
- Formato tabla: ID, Título, Precondiciones, Pasos, Resultado Esperado, Tipo, Prioridad, Datos de Prueba.
- Referencia evidencia con [SRC:<sha1_8|filename>] cuando corresponda.
- Si falta info, marca ASUMIDO con breve justificación.
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
    # TODO: aquí invocas tu cliente Gemini real (ejemplo):
    # return gemini_client.generate_text(prompt=prompt, model="gemini-1.5-pro")
    return f"[DEBUG] Prompt de {len(prompt)} caracteres enviado a Gemini."





def prompt_generar_escenarios_profesionales(descripcion_refinada):
    return {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "Eres un Analista QA Senior experto en diseño de pruebas funcionales para sistemas empresariales.\n\n"
                            "A partir de la siguiente descripción funcional RECIÉN REFINADA, genera una tabla en formato CSV puro "
                            "con exactamente estas columnas (encabezado incluido):\n"
                            "Title,Preconditions,Steps,Expected Result,Type,Priority\n\n"

                            "⚠️ REGLAS ESTRICTAS DE SALIDA:\n"
                            "- SOLO imprime el CSV. Nada de texto extra, títulos, explicaciones ni bloques Markdown.\n"
                            "- Usa comas como separador; si una celda contiene comas o saltos de línea, enciérrala entre comillas dobles.\n"
                            "- Steps numerados como: 1. 2. 3. (cada paso en su propia línea usando \\n dentro de la celda).\n"
                            "- Type ∈ {Funcional, Validación, Seguridad, Usabilidad}.\n"
                            "- Priority ∈ {Alta, Media, Baja}.\n"
                            "- No establezcas un número fijo de casos: genera **todos los escenarios distintos y relevantes** que identifiques.\n"
                            "- Desglosa variaciones por datos/condiciones (p. ej., distintas validaciones de campos, reglas de negocio, estados, "
                            "perfiles/roles, productos/monedas/plazos, límites mínimos/máximos, flujos con/sin relacionados, consolidaciones, "
                            "y clientes con o sin productos previos), evitando duplicados.\n"
                            "- Si dos escenarios solo difieren en un parámetro, crea filas separadas y explícitalo en Title/Steps.\n\n"

                            "🎯 INSTRUCCIONES ESPECÍFICAS PARA **Preconditions** (obligatorio cumplir):\n"
                            "- Deben ser **concretas y accionables**, derivadas de la descripción. Evita genéricos como "
                            "\"Usuario con sesión iniciada\" si no están acompañados de supuestos de datos y servicios.\n"
                            "- Cuando la funcionalidad mencione o implique:\n"
                            "  • **Identificación** (tipo/número de documento): incluir 'Cliente registrado en la base de datos con documento vigente'.\n"
                            "  • **Producto Tarjeta de Crédito**: incluir 'Cliente con al menos una tarjeta de crédito activa/válida'.\n"
                            "  • **Segmento del cliente**: incluir 'Producto habilitado/compatible con el segmento del cliente'.\n"
                            "  • **Validaciones/Reglas**: incluir 'Servicios/reglas de negocio y motores de validación operativos'.\n"
                            "  • **Sesión**: incluir 'Aplicación disponible y sesión iniciada'.\n"
                            "- Si aplica más de una, **combínalas** en la precondición (separadas por '; ').\n"
                            "- Prohibido: 'Ninguna', 'N/A', precondiciones vacías o genéricas sin contexto de datos/servicios.\n\n"

                            "🧪 FEW-SHOT (NO IMPRIMIR EN LA RESPUESTA):\n"
                            "Ejemplo de buena precondición cuando hay identificación + tarjeta + segmento:\n"
                            "  'Aplicación disponible y sesión iniciada; "
                            "Cliente registrado en la base de datos con documento vigente; "
                            "Cliente con al menos una tarjeta de crédito activa; "
                            "La tarjeta está habilitada para el segmento del cliente; "
                            "Servicios de validación y reglas de negocio operativos'\n\n"

                            "✅ CHECKLIST PRE-SALIDA (interno, NO imprimir):\n"
                            "- Cobertura de flujo feliz, negativos/validaciones, seguridad, usabilidad, casos borde y variaciones de datos.\n"
                            "- Si la descripción/Steps mencionan identificación → incluir 'cliente registrado + documento vigente'.\n"
                            "- Si mencionan tarjeta de crédito → incluir 'tarjeta activa/válida'.\n"
                            "- Si mencionan segmento → incluir 'producto habilitado para el segmento'.\n"
                            "- Si hay 'validar' o reglas → incluir 'servicios/reglas operativos'.\n"
                            "- Si hay acciones en la UI → incluir 'aplicación disponible y sesión iniciada'.\n"
                            "- Evitar duplicados; títulos claros que indiquen la variante cubierta.\n\n"

                            "📄 Descripción funcional (refinada):\n"
                            f"{descripcion_refinada}"
                        )
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
                            "Actúa como Analista QA Senior.\n"
                            "Analiza el siguiente texto funcional y genera entre 5 y 10 sugerencias claras para mejorarlo, "
                            "enfocándote en facilitar la generación de escenarios de prueba automatizados.\n\n"
                            "🎯 Las sugerencias deben centrarse en:\n"
                            "- Claridad y especificidad técnica\n"
                            "- Inclusión de validaciones de campos\n"
                            "- Casos límite o alternativos\n"
                            "- Precondiciones explícitas del sistema o del usuario\n"
                            "- Mejorar la redacción hacia comportamiento verificable\n\n"
                            f"📄 Texto funcional:\n{texto_funcional}"
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

    # Separar por líneas o viñetas
    sugerencias = [
        linea.strip("•-1234567890. ") for linea in texto_sugerencias.strip().split("\n")
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

        # Limpiar líneas vacías y espacios extras
        lineas = [line.strip() for line in texto.strip().splitlines() if line.strip()]
        return "\n".join(lineas)

    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"❌ No se pudo extraer texto de Gemini: {e}")

def generar_prompt_csv_robusto(texto_funcional):
    prompt = f"""
Actúa como un analista de QA experto.

Genera 3 escenarios de prueba funcionales en formato CSV, usando exactamente estas columnas:
Title,Preconditions,Steps,Expected Result,Type,Priority

⚠️ Instrucciones estrictas:
- No expliques nada.
- No uses formato Markdown.
- Usa comas como separadores.
- Cada línea debe tener contenido realista, técnico y profesional.
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



def enviar_a_gemini(prompt_dict, max_intentos=4, espera_inicial=2):

    API_KEY = st.secrets["gemini_api_key"]
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": API_KEY
    }

    intentos = 0
    while intentos < max_intentos:
        try:
            response = requests.post(url, headers=headers, json=prompt_dict)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if response.status_code == 503:
                # Si es 503, espera un momento y reintenta
                espera = espera_inicial * (intentos + 1)
                st.warning(f"⚠️ Gemini está saturado (503). Reintentando en {espera} segundos... (Intento {intentos+1}/{max_intentos})")
                time.sleep(espera)
                intentos += 1
            else:
                # Otros errores HTTP, se lanza inmediatamente
                raise ValueError(f"❌ Error HTTP al invocar Gemini: {e}")
        except Exception as e:
            raise ValueError(f"❌ Error general al invocar Gemini: {e}")

    # Si fallaron todos los intentos
    raise ValueError("❌ Gemini no respondió tras varios intentos (503 repetidos).")


def prompt_refinar_descripcion(texto_funcional):
    return {
        "contents": [{
            "parts": [{
                "text": (
                    "Eres un analista experto en QA. Debes reestructurar claramente la siguiente descripción funcional "
                    "en formato técnico y profesional, preparándola para que luego se generen escenarios de prueba. "
                    "Obligatoriamente incluye estas tres secciones claramente separadas y completas:\n\n"
                    "- Módulo: (Nombre breve del módulo o componente involucrado)\n"
                    "- Función: (Acción principal que permite esta funcionalidad)\n"
                    "- Detalle técnico del comportamiento esperado: (Breve pero clara descripción técnica de cómo debería funcionar exactamente la funcionalidad)\n\n"
                    "📌 Ejemplo claro:\n"
                    "- Módulo: Registro de usuarios\n"
                    "- Función: Permitir que usuarios nuevos se registren\n"
                    "- Detalle técnico del comportamiento esperado: El formulario validará campos obligatorios como usuario, correo y contraseña. Se mostrará un mensaje de éxito al completar correctamente el registro y mensajes específicos en caso de error en cualquier validación.\n\n"
                    f"⚠️ Ahora reestructura profesionalmente el siguiente texto:\n\n{texto_funcional}"
                )
            }]
        }]
    }

def obtener_descripcion_refinada(texto_funcional, max_intentos=3):
    intentos = 0
    while intentos < max_intentos:
        respuesta_estructurada = enviar_a_gemini(prompt_refinar_descripcion(texto_funcional))
        descripcion_refinada = extraer_texto_de_respuesta_gemini(respuesta_estructurada).strip()

        if descripcion_refinada:
            return descripcion_refinada

        intentos += 1
        time.sleep(1)  # pequeño retardo antes de reintentar

    # si llega aquí, todos los intentos fallaron

    raise ValueError("⚠️ Gemini no devolvió descripción válida tras varios intentos.")

