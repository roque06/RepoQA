import io
import csv
import pandas as pd
import streamlit as st
import datetime
import re
from io import StringIO


def _limpiar_texto_ejemplo(texto: str) -> str:
    """
    Elimina expresiones de ejemplo del tipo:
    - (Ej: 5,000 DOP)
    - (ej. Español)
    - (por ejemplo: Admin)
    sin tocar otros paréntesis válidos como siglas o aclaraciones funcionales.
    """
    if not isinstance(texto, str):
        return ""

    limpio = texto
    limpio = re.sub(
        r"\s*\(\s*(?:ej(?:emplo)?\.?\s*:?\s*|por ejemplo\s*:?\s*|p\.\s*ej\.?\s*:?\s*)[^)]*\)",
        "",
        limpio,
        flags=re.IGNORECASE,
    )
    limpio = re.sub(
        r"\s*[-,:]?\s*(?:ej(?:emplo)?\.?\s*:?\s*|por ejemplo\s*:?\s*|p\.\s*ej\.?\s*:?\s*)[^;\n]*",
        "",
        limpio,
        flags=re.IGNORECASE,
    )
    limpio = re.sub(r"\s{2,}", " ", limpio)
    return limpio.strip()


def _limpiar_identificadores_placeholder(texto: str) -> str:
    """
    Quita aliases/identificadores ficticios generados por el modelo, por ejemplo:
    - Usuario 'A2000'
    - Cliente 'ID_CLIENTE_001'
    - cuenta 'CTA_USD_001'
    Mantiene la frase en lenguaje natural sin exponer códigos inventados.
    """
    if not isinstance(texto, str):
        return ""

    patron_placeholder = r"(?:ID_[A-Z0-9_]+|CTA_[A-Z0-9_]+|USR_[A-Z0-9_]+|USER_[A-Z0-9_]+|CLIENTE_[A-Z0-9_]+|CUENTA_[A-Z0-9_]+|[A-Z]{1,3}\d{3,})"
    limpio = texto

    reemplazos_contextuales = [
        (rf"\bUsuario\s+[\"']{patron_placeholder}[\"']", "Usuario"),
        (rf"\bCliente\s+[\"']{patron_placeholder}[\"']", "Cliente"),
        (rf"\bcuenta\s+[\"']{patron_placeholder}[\"']", "cuenta"),
        (rf"\bCuenta\s+[\"']{patron_placeholder}[\"']", "Cuenta"),
        (rf"\btarjeta\s+[\"']{patron_placeholder}[\"']", "tarjeta"),
        (rf"\bTarjeta\s+[\"']{patron_placeholder}[\"']", "Tarjeta"),
    ]
    for patron, reemplazo in reemplazos_contextuales:
        limpio = re.sub(patron, reemplazo, limpio)

    limpio = re.sub(rf"\s*[\"']{patron_placeholder}[\"']", "", limpio)
    limpio = re.sub(r"\basociad([ao]) a\s+activa\b", r"asociad\1 a la cuenta activa", limpio, flags=re.IGNORECASE)
    limpio = re.sub(r"\b(es|sea|son)\s*(?=[,.;:]|$)", "", limpio, flags=re.IGNORECASE)
    limpio = re.sub(r"\bConfirmar que (el|la|los|las)\b", r"Confirmar \1", limpio, flags=re.IGNORECASE)
    limpio = re.sub(r"\s{2,}", " ", limpio)
    limpio = re.sub(r"\s+([,.;:])", r"\1", limpio)
    return limpio.strip()


def limpiar_csv_con_formato(texto_csv: str, columnas_esperadas: int = 6) -> str:
    import csv, io

    lineas = texto_csv.strip().split("\n")
    filas_validas = []

    reader = csv.reader(lineas, skipinitialspace=True)
    for fila in reader:
        if len(fila) == columnas_esperadas:
            filas_validas.append([campo.replace("\n", " ").strip() for campo in fila])

    if not filas_validas:
        raise ValueError("❌ Gemini generó CSV inválido o vacío.")

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerows(filas_validas)

    return output.getvalue()




def leer_csv_seguro(texto_csv: str, columnas_esperadas: int = 4) -> pd.DataFrame:
    f = StringIO(texto_csv)
    reader = csv.reader(f, quotechar='"', escapechar='\\')
    filas_validas = [row for row in reader if len(row) == columnas_esperadas]

    if not filas_validas:
        raise ValueError("❌ El CSV no contiene filas válidas.")

    return pd.DataFrame(filas_validas[1:], columns=filas_validas[0])


def corregir_csv_con_comas(texto_csv: str, columnas_objetivo: int = 6) -> str:
    """
    Encierra en comillas los campos de cada línea si hay columnas de más o mal separadas.
    """
    import csv
    import io

    lineas = texto_csv.strip().split("\n")
    corregido = []

    for linea in lineas:
        campos = list(csv.reader([linea]))[0]

        if len(campos) != columnas_objetivo:
            # Encierra todo campo entre comillas si no lo está
            campos = [f'"{campo.strip()}"' if not campo.strip().startswith('"') else campo for campo in campos]
            nueva_linea = ",".join(campos)
            corregido.append(nueva_linea)
        else:
            corregido.append(linea)

    return "\n".join(corregido)


import re

def normalizar_preconditions(preconds: str) -> str:
    """
    Idempotente: quita numeraciones previas (1., 2., …), separa por saltos de línea o ';',
    limpia vacíos/duplicados y vuelve a enumerar una sola vez.
    """
    if not isinstance(preconds, str):
        return ""
    txt = preconds.replace("\\n", "\n").strip()
    if not txt:
        return ""

    # Romper por líneas o ';' y también trocear si metieron varias en la misma línea
    candidatos = []
    for linea in txt.split("\n"):
        for trozo in re.split(r";", linea):
            trozo = trozo.strip()
            if not trozo:
                continue
            # Quitar viñetas/numeraciones previas al inicio de cada item
            trozo = re.sub(r"^\s*(?:-|\*|•)?\s*", "", trozo)
            trozo = re.sub(r"^\s*\d+\.\s*", "", trozo)
            trozo = _limpiar_texto_ejemplo(trozo)
            trozo = _limpiar_identificadores_placeholder(trozo)
            if trozo:
                candidatos.append(trozo)

    # Dejar únicos en el orden de aparición
    vistos, items = set(), []
    for c in candidatos:
        if c not in vistos:
            vistos.add(c)
            items.append(c)

    return "\n".join(f"{i+1}. {c}" for i, c in enumerate(items))


def normalizar_steps(steps: str) -> str:
    """
    Idempotente: si viene '1. … 2. …' en una línea o varias, quita numeraciones
    antiguas y vuelve a enumerar en líneas separadas.
    """
    if not isinstance(steps, str):
        return ""
    txt = steps.replace("\\n", "\n").strip()
    if not txt:
        return ""

    partes = []
    for linea in txt.split("\n"):
        linea = linea.strip()
        if not linea:
            continue
        # Si trae varios pasos en la misma línea: '1. foo 2. bar 3. baz'
        trozos = re.split(r"(?=\d+\.\s)", linea) if re.search(r"\d+\.\s", linea) else [linea]
        for t in trozos:
            t = t.strip()
            if not t:
                continue
            # Quitar numeración/bullets previas
            t = re.sub(r"^\s*(?:-|\*|•)?\s*", "", t)
            t = re.sub(r"^\s*\d+\.\s*", "", t)
            t = _limpiar_texto_ejemplo(t)
            t = _limpiar_identificadores_placeholder(t)
            if t:
                partes.append(t)

    return "\n".join(f"{i+1}. {p}" for i, p in enumerate(partes))



def validar_lineas_csv(texto_csv: str, columnas_esperadas: int) -> str:
    lineas = texto_csv.strip().splitlines()
    filtradas = [l for l in lineas if l.count(",") == columnas_esperadas - 1]
    return "\n".join(filtradas)



def limpiar_csv_sugerencias(csv_text, columnas_esperadas=4):
    """
    Elimina líneas que no tengan el número correcto de columnas.
    """
    lineas = csv_text.strip().splitlines()
    resultado = []

    for linea in lineas:
        partes = list(csv.reader([linea]))[0]
        if len(partes) == columnas_esperadas:
            resultado.append(",".join(partes))

    return "\n".join(resultado)



    """
    Convierte un texto plano separado por puntos o comas en una lista numerada con saltos de línea.
    """
    if not texto or not isinstance(texto, str):
        return texto

    delimitadores = [". ", "; ", "\n"]
    for delim in delimitadores:
        if delim in texto:
            partes = [p.strip() for p in texto.split(delim) if p.strip()]
            break
    else:
        partes = [texto.strip()]

    return "\n".join([f"{i+1}. {parte}" for i, parte in enumerate(partes)])


def limpiar_markdown_csv(respuesta):
    """
    Elimina delimitadores Markdown y valida que haya contenido CSV real.
    """
    if "```csv" in respuesta:
        partes = respuesta.split("```csv")
        respuesta = partes[1] if len(partes) > 1 else ""

    if "```" in respuesta:
        respuesta = respuesta.split("```")[0]

    respuesta = respuesta.strip()

    # Validar que tenga al menos una coma (separador CSV)
    if "," not in respuesta:
        return ""

    return respuesta




def generar_csv_descargable(csv_raw):
    """
    Ordena los escenarios por prioridad y devuelve un archivo CSV descargable.
    """
    df = pd.read_csv(io.StringIO(csv_raw))
    
    # Orden descendente por prioridad (Alta > Media > Baja)
    prioridad_orden = {"Alta": 3, "Media": 2, "Baja": 1}
    df["orden"] = df["Priority"].map(prioridad_orden)
    df = df.sort_values(by="orden", ascending=False).drop(columns=["orden"])

    output = io.StringIO()
    df.to_csv(output, index=False)
    return output.getvalue()

def validar_csv_qa(csv_raw):
    lines = csv_raw.strip().splitlines()
    header_line = lines[0].replace("\t", ",").strip()
    header = [h.strip() for h in header_line.split(",")]

    expected_cols = ["Title", "Preconditions", "Steps", "Expected Result", "Type", "Priority"]

    if header != expected_cols:
        raise ValueError(f"❌ Las columnas del CSV no coinciden con el formato requerido.\nSe recibió: {header}")
    
    for i, line in enumerate(lines[1:], start=2):
        row = list(csv.reader([line]))[0]
        if len(row) != len(expected_cols):
            raise ValueError(f"❌ Fila {i} tiene {len(row)} columnas, se esperaban {len(expected_cols)}.")
        if any(not cell.strip() for cell in row):
            raise ValueError(f"⚠️ Fila {i} tiene campos vacíos.")

    return True


# 🔍 Extraer solo el contenido del CSV
def extraer_csv(texto_generado):
    """
    Recorta encabezados o texto adicional fuera del CSV, dejando solo la tabla.
    """
    lineas = texto_generado.strip().split("\n")
    lineas_csv = []

    encabezados = ["Title", "Preconditions", "Steps", "Expected Result", "Type", "Priority"]
    encabezado_detectado = False

    for linea in lineas:
        if not encabezado_detectado and all(col in linea for col in encabezados):
            encabezado_detectado = True

        if encabezado_detectado:
            lineas_csv.append(linea)

    return "\n".join(lineas_csv)


# 🛡️ Corregir CSV con comas internas mal escapadas
def corregir_csv_con_comas(texto_csv, columnas_objetivo):
    """
    Encierra en comillas los campos de cada línea si la cantidad de columnas no coincide.
    """
    lineas = texto_csv.strip().split("\n")
    corregido = []

    for linea in lineas:
        campos = list(csv.reader([linea]))[0]

        if len(campos) != columnas_objetivo:
            campos = [f'"{campo.strip()}"' if not campo.strip().startswith('"') else campo for campo in campos]
            nueva_linea = ",".join(campos)
            corregido.append(nueva_linea)
        else:
            corregido.append(linea)

    return "\n".join(corregido)


# 🧪 Convertir el CSV en DataFrame blindado
def procesar_csv_seguro(csv_raw, columnas_esperadas=6):
    """
    Convierte un CSV generado por Gemini en un DataFrame limpio y lo guarda en session_state.
    """
    if not csv_raw or not csv_raw.strip():
        st.error("❌ El CSV recibido está vacío.")
        st.session_state.df_editable = None
        st.session_state.generado = False
        return

    try:
        csv_limpio = extraer_csv(csv_raw)
    except Exception as e:
        st.error("❌ Error al limpiar el CSV.")
        st.text_area("Respuesta cruda", csv_raw, height=300)
        return

    try:
        csv_corregido = corregir_csv_con_comas(csv_limpio, columnas_esperadas)
        df = pd.read_csv(io.StringIO(csv_corregido))

        columnas_clave = ["Title", "Preconditions", "Steps", "Expected Result", "Type", "Priority"]
        for col in columnas_clave:
            if col not in df.columns:
                df[col] = ""
            df[col] = df[col].fillna("").astype(str)

        if "Steps" in df.columns:
            df["Steps"] = df["Steps"].apply(lambda t: str(t).replace("\\n", "\n").strip())

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        st.session_state.historial.append({"ts": ts, "df": df})
        st.session_state.df_editable = df
        st.session_state.ultimo_ts = ts
        st.session_state.generado = True

        st.success(f"✅ Se generaron {len(df)} escenarios.")
        st.dataframe(df)

    except Exception as e:
        st.error(f"❌ Error al procesar CSV: {e}")
        st.text_area("CSV corregido", csv_corregido, height=300)
        st.session_state.df_editable = None
        st.session_state.generado = False


def corregir_csv_gemini(csv_raw):
    """
    Limpia y corrige el CSV generado por Gemini para que tenga el número correcto de columnas.
    """
    lines = csv_raw.strip().splitlines()
    header = lines[0].split(",")
    num_cols = len(header)

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(header)

    for line in lines[1:]:
        row = list(csv.reader([line]))[0]
        if len(row) == num_cols:
            writer.writerow(row)
        else:
            # Intenta recomponer la fila si tiene comas internas
            fixed_row = []
            buffer = ""
            for item in row:
                buffer += item
                if buffer.count('"') % 2 == 0:
                    fixed_row.append(buffer.strip())
                    buffer = ""
            if len(fixed_row) == num_cols:
                writer.writerow(fixed_row)

    return output.getvalue()
