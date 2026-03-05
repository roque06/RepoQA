# ============================ Cleantest.py (LIMPIO + PATCH + HEADER FIX) ============================
import io
import pandas as pd
import streamlit as st
from datetime import datetime
import io, re
from utils_ingest import consolidate_attachments


# 1) SIEMPRE la primera llamada Streamlit
st.set_page_config(page_title="Generador QA", layout="wide", initial_sidebar_state="collapsed")

# 2) Importar utilidades propias SOLO una vez
from auth_ui import SecureShell
from utils_ui import titulo_seccion, spinner_accion
from utils_csv import (
    limpiar_markdown_csv, normalizar_preconditions, corregir_csv_con_comas,
    normalizar_steps, limpiar_csv_con_formato, leer_csv_seguro
)
from utils_testrail import (
    obtener_proyectos, obtener_suites, obtener_secciones, enviar_a_testrail
)
from utils_gemini import (
    enviar_a_gemini, extraer_texto_de_respuesta_gemini,
    prompt_generar_escenarios_profesionales, limitar_texto_para_gemini
)

# 3) Login + tamaños independientes
shell = SecureShell(
    auth_yaml=".streamlit/auth.yaml",
    login_page_width=560,   # <-- ancho SOLO del login
    app_page_width=1600,    # <-- ancho SOLO del contenido de la app
    logout_top=12,
    logout_right=96,
)
if not shell.login():
    st.stop()

# ============================ APP (UNA SOLA VEZ) ============================
st.title("🧪 Generador de Escenarios QA para TestRail")

# Estado global
st.session_state.setdefault("historial_generaciones", [])
st.session_state.setdefault("historial", [])
st.session_state.setdefault("df_editable", None)
st.session_state.setdefault("generado", False)
st.session_state.setdefault("texto_funcional", "")
st.session_state.setdefault("descripcion_refinada", "")











# Tabs principales
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "✏️ Generar", "🛠️ Editar", "🧪 Revisar", "📚 Historial", "🚀 Subir a TestRail"
])

def limpiar_pestanas():
    """Limpia variables de estado menos el historial."""
    keys_keep = {"historial_generaciones"}
    for key in list(st.session_state.keys()):
        if key not in keys_keep:
            st.session_state[key] = [] if isinstance(st.session_state.get(key), list) else ""
            if key in ("df_editable", "generado"):
                st.session_state[key] = None if key == "df_editable" else False


st.markdown(
    """
<style>
.divider { border-top: 1px solid #CCC; margin: 20px 0 10px; }
</style>
<div class="divider"></div>
""",
    unsafe_allow_html=True,
)



def render_df_paginado(df, key_prefix: str, filas_por_pagina: int = 20, titulo: str = "Vista previa"):
    if df is None or df.empty:
        st.info("ℹ️ No hay datos para mostrar.")
        return

    total_filas = len(df)
    total_paginas = (total_filas - 1) // filas_por_pagina + 1

    st.markdown(f"### {titulo}")
    paginas = [str(i+1) for i in range(total_paginas)]
    pagina_actual = st.radio(
        "📑 Página",
        paginas,
        index=0,
        horizontal=True,
        key=f"{key_prefix}_paginador"
    )
    pagina_idx = int(pagina_actual) - 1

    inicio = pagina_idx * filas_por_pagina
    fin = inicio + filas_por_pagina

    st.dataframe(df.iloc[inicio:fin], use_container_width=True)
    st.caption(f"Mostrando {inicio+1}–{min(fin, total_filas)} de {total_filas} filas")









def _render_pdf_pages(file_bytes, dpi=140):
    """Devuelve una lista de BytesIO (PNG) por página PDF."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        st.error("Falta 'pymupdf'. Instala con: pip install pymupdf")
        return []
    pages = []
    with fitz.open(stream=bytes(file_bytes), filetype="pdf") as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            pages.append(io.BytesIO(pix.tobytes("png")))
    return pages

def _paginate_text(text, max_chars=3000):
    """Corta el texto en 'páginas' sin perder párrafos."""
    if not text:
        return [""]
    text = re.sub(r'\r\n?', '\n', text).strip()
    paras = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]
    pages, buf = [], ""
    for p in paras:
        chunk = (("\n\n" if buf else "") + p)
        if len(buf) + len(chunk) <= max_chars:
            buf += chunk
        else:
            if buf:
                pages.append(buf)
            if len(chunk) > max_chars:
                for i in range(0, len(chunk), max_chars):
                    pages.append(chunk[i:i+max_chars])
                buf = ""
            else:
                buf = chunk
    if buf:
        pages.append(buf)
    return pages or [""]

# Reemplaza COMPLETA esta función por la de abajo
def preview_document_paginado_inline(
    file_label: str,
    file_name: str = "",
    file_bytes: bytes | None = None,
    text_extraido: str | None = None,
    tipo: str | None = None,
    key_ns: str = "pview",
    collapsible: bool = True,        # <— nuevo: mostrar/ocultar
    expanded: bool = False           # <— nuevo: por defecto colapsado
):
    """Renderiza un preview paginado (PDF como imágenes, texto paginado) con expander opcional."""
    # Inferencia del tipo
    if not tipo and file_name:
        tipo = "pdf" if file_name.lower().endswith(".pdf") else "texto"
    tipo = tipo or ("texto" if text_extraido is not None else "pdf")
    state_key = f"{key_ns}:{file_label}:{file_name}:page"

    # Contenedor colapsable
    header = f"{file_label} — Preview paginado"
    container = st.expander(header, expanded=expanded) if collapsible else st.container()

    with container:
        if tipo == "pdf":
            if not file_bytes:
                st.info("No se recibieron bytes del PDF.")
                return
            pages = _render_pdf_pages(file_bytes)
            total = len(pages)
            if total == 0:
                st.warning("No se pudo renderizar el PDF.")
                return
            if state_key not in st.session_state:
                st.session_state[state_key] = 1

            c1, c2, c3, c4, c5 = st.columns([1, 1.2, 2, 1.2, 1])
            with c1:
                if st.button("⏮️", key=f"{state_key}-f", use_container_width=True):
                    st.session_state[state_key] = 1
            with c2:
                if st.button("◀️", key=f"{state_key}-p", use_container_width=True):
                    st.session_state[state_key] = max(1, st.session_state[state_key]-1)
            with c3:
                page = st.number_input(
                    "Ir a página", min_value=1, max_value=total,
                    value=st.session_state[state_key], step=1, label_visibility="collapsed",
                    key=f"{state_key}-n"
                )
                st.session_state[state_key] = int(page)
            with c4:
                if st.button("▶️", key=f"{state_key}-nxt", use_container_width=True):
                    st.session_state[state_key] = min(total, st.session_state[state_key]+1)
            with c5:
                if st.button("⏭️", key=f"{state_key}-l", use_container_width=True):
                    st.session_state[state_key] = total

            st.caption(f"Página {st.session_state[state_key]} de {total}")
            # 👇 Cambio clave: usar use_container_width (NO use_column_width)
            st.image(pages[st.session_state[state_key]-1], use_container_width=True)

        else:
            if not text_extraido and file_bytes:
                try:
                    text_extraido = file_bytes.decode("utf-8", errors="ignore")
                except Exception:
                    text_extraido = ""
            pages = _paginate_text(text_extraido or "", max_chars=3000)
            total = len(pages)
            if state_key not in st.session_state:
                st.session_state[state_key] = 1

            c1, c2, c3, c4, c5 = st.columns([1, 1.2, 2, 1.2, 1])
            with c1:
                if st.button("⏮️", key=f"{state_key}-tf", use_container_width=True):
                    st.session_state[state_key] = 1
            with c2:
                if st.button("◀️", key=f"{state_key}-tp", use_container_width=True):
                    st.session_state[state_key] = max(1, st.session_state[state_key]-1)
            with c3:
                page = st.number_input(
                    "Ir a página", min_value=1, max_value=total,
                    value=st.session_state[state_key], step=1, label_visibility="collapsed",
                    key=f"{state_key}-tn"
                )
                st.session_state[state_key] = int(page)
            with c4:
                if st.button("▶️", key=f"{state_key}-tnx", use_container_width=True):
                    st.session_state[state_key] = min(total, st.session_state[state_key]+1)
            with c5:
                if st.button("⏭️", key=f"{state_key}-tl", use_container_width=True):
                    st.session_state[state_key] = total

            st.caption(f"Página {st.session_state[state_key]} de {total}")
            with st.container(border=True):
                st.markdown(pages[st.session_state[state_key]-1])




# =========================
# TAB 1 — Generar + Preview + Limpiar (con reset seguro y borrado de sugerencias)
# =========================
import io, re
from datetime import datetime
import pandas as pd
import streamlit as st

# ---------- RESET PRE-RUN (se ejecuta ANTES de crear widgets) ----------
# Si el botón "Limpiar" se presionó en el run anterior, aquí se vacía todo
if st.session_state.get("tab1_do_reset", False):
    # Estados base del Tab1
    st.session_state["texto_funcional"] = ""
    st.session_state["attachments_text"] = ""
    st.session_state["attachments_meta"] = []
    st.session_state["use_attachments"] = True
    st.session_state["df_editable"] = None
    st.session_state["generado"] = False
    st.session_state["descripcion_refinada"] = ""

    # Borrar estados de preview/paginación (keys creadas por el preview)
    for k in list(st.session_state.keys()):
        if k.startswith("t1:") or k.startswith("pview:") or (":page" in k):
            st.session_state.pop(k, None)

    # 🔁 Forzar reset REAL del uploader cambiando la key (nonce)
    st.session_state["tab1_uploader_nonce"] = st.session_state.get("tab1_uploader_nonce", 0) + 1

    # 🧹 Borrar estados de SUGERENCIAS (Tab de Sugerencias)
    # Limpia nombres típicos; si usas otros, añade aquí sus keys:
    suger_keys = [
        "sugerencias_df", "sugerencias_seleccionadas", "sugerencias_aplicadas",
        "df_sugerencias", "df_sugerencias_edit", "sugerencias_table_state",
        "sugerencias_csv_raw", "sugerencias_preview", "sugerencias_selected_rows",
        "tab3_uploader_nonce", "tab3:page_state", "tab3:filters"
    ]
    for k in list(st.session_state.keys()):
        if k in suger_keys or k.startswith("suger") or k.startswith("tab3:"):
            st.session_state.pop(k, None)

    # No borrar historial
    st.session_state.pop("tab1_do_reset", None)  # consume el flag para este run

# ---------- ESTADOS INICIALES (defaults) ----------
st.session_state.setdefault("attachments_text", "")
st.session_state.setdefault("attachments_meta", [])
st.session_state.setdefault("use_attachments", True)
st.session_state.setdefault("df_editable", None)
st.session_state.setdefault("generado", False)
st.session_state.setdefault("descripcion_refinada", "")
st.session_state.setdefault("historial_generaciones", [])
st.session_state.setdefault("tab1_uploader_nonce", 0)

with tab1:
    st.subheader("📌 Generar escenarios de prueba automáticamente")

    # ---- Estado por defecto seguro (no reasignar despues del text_area) ----
    st.session_state.setdefault("attachments_text", "")
    st.session_state.setdefault("attachments_meta", [])
    st.session_state.setdefault("use_attachments", True)
    st.session_state.setdefault("tab1_uploader_nonce", 0)
    st.session_state.setdefault("tab1_do_reset", False)

    # ---- TextArea de entrada (NO sobrescribir session_state luego) ----
    texto_funcional = st.text_area(
        "Texto funcional original",
        value=st.session_state.get("texto_funcional", ""),
        height=250,
        key="texto_funcional"
    )  # ← no reasignes st.session_state["texto_funcional"] más abajo

    # ---- Adjuntar documentos e imágenes ----
    st.markdown("### Adjuntar documentos e imágenes (opcional)")
    uploads = st.file_uploader(
        "PDF, DOCX, TXT, CSV, XLSX, PNG, JPG, WEBP, TIFF",
        type=["pdf","docx","txt","csv","xlsx","png","jpg","jpeg","webp","tiff"],
        accept_multiple_files=True,
        key=f"tab1_uploader_{st.session_state['tab1_uploader_nonce']}"
    )

    colA, colB = st.columns([1,1])
    with colA:
        st.checkbox(
            "Usar adjuntos para generar",
            key="use_attachments",
            help="Si está activo, el texto extraído de los archivos se enviará al generador."
        )
    with colB:
        if st.button("Procesar adjuntos", key="btn_procesar_adjuntos"):
            if uploads:
                try:
                    from utils_ingest import consolidate_attachments
                except Exception:
                    consolidate_attachments = None
                if consolidate_attachments is None:
                    st.error("❌ Falta utils_ingest.consolidate_attachments en el entorno.")
                else:
                    files = [(f.name, f.read()) for f in uploads]
                    txt, metas = consolidate_attachments(files, max_chars=60_000)
                    st.session_state["attachments_text"] = txt or ""
                    st.session_state["attachments_meta"] = metas or []
                    st.success(f"Procesado: {len(st.session_state['attachments_meta'])} archivo(s).")
            else:
                st.info("No seleccionaste archivos.")

    # ---- Metadatos de adjuntos (si existen) ----
    if st.session_state["attachments_meta"]:
        with st.expander("Fuentes procesadas", expanded=False):
            for m in st.session_state["attachments_meta"]:
                st.caption(
                    f"• {m['filename']} ({m['ext']}, {m['size_bytes']} bytes) — "
                    f"{m['sha1_8']} — {m['chars']} chars"
                )

    # ---- Preview paginado (colapsable) ----
    st.markdown("### Preview paginado del documento")
    if uploads:
        for i, f in enumerate(uploads, start=1):
            bytes_f = f.getvalue() if hasattr(f, "getvalue") else f.read()
            preview_document_paginado_inline(
                file_label=f"Archivo {i}: {f.name}",
                file_name=f.name,
                file_bytes=bytes_f,
                tipo=("pdf" if f.name.lower().endswith(".pdf") else "texto"),
                key_ns="t1",
                collapsible=True,
                expanded=False
            )
    elif st.session_state.get("attachments_text"):
        preview_document_paginado_inline(
            file_label="Texto consolidado de adjuntos",
            file_name="adjuntos.txt",
            text_extraido=st.session_state["attachments_text"],
            tipo="texto",
            key_ns="t1",
            collapsible=True,
            expanded=False
        )
    else:
        st.caption("Sube archivos y/o presiona **Procesar adjuntos** para ver aquí el preview paginado.")

    st.markdown("---")

    def _normalizar_type(valor):
        t = str(valor).strip().lower()
        if not t:
            return "Funcional"
        if "valid" in t:
            return "Validacion"
        if "integr" in t or "api" in t or "servicio" in t or "motor" in t:
            return "Integracion"
        if "segur" in t or "permis" in t or "autoriz" in t or "rol" in t:
            return "Seguridad"
        if "usab" in t or "ux" in t or "mensaje" in t:
            return "Usabilidad"
        if "func" in t or "regla" in t or "negocio" in t or "calculo" in t:
            return "Funcional"
        return "Funcional"

    def _normalizar_title(valor):
        titulo = str(valor or "").strip()
        if not titulo:
            return ""

        # Quitar prefijos de enumeracion/labels tecnicos del modelo
        patrones = [
            r"^(?:SCENARIO|ESCENARIO|CASO(?:\s+DE\s+PRUEBA)?|TEST\s*CASE|TC)\s*[_:\-#]*\s*[\d\.]*\s*[:\-]*\s*",
            r"^\s*[\d]+\s*[\)\.\-:]\s*",
        ]
        for patron in patrones:
            titulo = re.sub(patron, "", titulo, flags=re.IGNORECASE).strip()

        # Limpieza final de separadores sobrantes
        titulo = re.sub(r"^[\s\-\:\._]+", "", titulo).strip()
        return titulo

    def _normalizar_priority(valor):
        p = str(valor).strip().lower()
        if not p:
            return "Media"
        if "alta" in p or "high" in p or "critical" in p:
            return "Alta"
        if "baja" in p or "low" in p:
            return "Baja"
        return "Media"

    def _normalizar_df_generado(df_in):
        df_out = df_in.copy()

        for c in ["Title", "Preconditions", "Steps", "Expected Result"]:
            if c in df_out.columns:
                df_out[c] = df_out[c].apply(lambda x: x.strip() if isinstance(x, str) else x)

        if "Title" in df_out.columns:
            df_out["Title"] = df_out["Title"].apply(_normalizar_title)

        if "Type" in df_out.columns:
            df_out["Type"] = df_out["Type"].apply(_normalizar_type)
        if "Priority" in df_out.columns:
            df_out["Priority"] = df_out["Priority"].apply(_normalizar_priority)

        requeridas = [c for c in ["Title", "Steps", "Expected Result"] if c in df_out.columns]
        if requeridas:
            mask = pd.Series([True] * len(df_out))
            for c in requeridas:
                mask = mask & df_out[c].astype(str).str.strip().ne("")
            df_out = df_out.loc[mask].copy()

        if "Title" in df_out.columns:
            df_out = df_out.drop_duplicates(subset=["Title"], keep="first")

        return df_out.reset_index(drop=True)

    def _estimar_rango_casos(texto_base: str):
        txt = (texto_base or "").strip()
        chars = len(txt)

        if chars < 800:
            objetivo = 10
        elif chars < 2_000:
            objetivo = 14
        elif chars < 5_000:
            objetivo = 18
        elif chars < 10_000:
            objetivo = 24
        else:
            objetivo = 30

        patrones_complejidad = [
            r"\bvalid", r"\bregla", r"\berror", r"\bpermis", r"\brol",
            r"\bintegr", r"\bapi", r"\bservicio", r"\bsegur", r"\bl[ií]mite",
            r"\bmin", r"\bmax", r"\bc[aá]lcul", r"\btasa", r"\bplazo",
            r"\bgradiente", r"\breestruct", r"\bauditor", r"\bnegativ"
        ]
        hits = sum(1 for p in patrones_complejidad if re.search(p, txt, flags=re.IGNORECASE))
        objetivo += min(8, hits // 2)

        objetivo = max(8, min(36, objetivo))
        minimo_aceptable = max(6, objetivo - 5)
        return minimo_aceptable, objetivo

    # ---- Generar escenarios ----
    if st.button("Generar escenarios de prueba", key="btn_generar_tab1"):
        # 1) Si se usarán adjuntos y hay archivos subidos pero NO procesados aún, procesarlos aquí automáticamente
        usar_adj = st.session_state.get("use_attachments", True)
        if usar_adj and uploads and not st.session_state.get("attachments_text"):
            try:
                from utils_ingest import consolidate_attachments
            except Exception:
                consolidate_attachments = None
            if consolidate_attachments:
                files = [(f.name, f.read()) for f in uploads]
                txt, metas = consolidate_attachments(files, max_chars=60_000)
                st.session_state["attachments_text"] = txt or ""
                st.session_state["attachments_meta"] = metas or []

        # 2) Validar: solo advertir si NO hay NI texto funcional NI adjuntos procesados
        tiene_texto = bool(st.session_state["texto_funcional"].strip())
        tiene_adjuntos = bool(st.session_state.get("attachments_text"))
        if not (tiene_texto or (usar_adj and tiene_adjuntos)):
            st.warning("⚠️ Ingresa el texto funcional o adjunta archivos y procésalos primero.")
        else:
            try:
                # Construir entrada combinada sin tocar el text_area
                extra = st.session_state.get("attachments_text", "") if usar_adj else ""
                texto_entrada = (
                    st.session_state["texto_funcional"] + ("\n\n" + extra if extra else "")
                ).strip()

                with st.spinner("🧠 Preparando contexto para generación..."):
                    # Evita una llamada LLM adicional para ahorrar cuota.
                    descripcion_refinada = limitar_texto_para_gemini(texto_entrada, max_chars=5000)
                st.session_state["descripcion_refinada"] = descripcion_refinada

                with st.spinner("📄 Generando escenarios CSV profesionales..."):
                    min_casos_aceptables, objetivo_casos = _estimar_rango_casos(texto_entrada)
                    max_intentos_generacion = 3 if objetivo_casos >= 24 else 2
                    texto_csv_raw = ""
                    df = pd.DataFrame()

                    for intento_gen in range(1, max_intentos_generacion + 1):
                        titulos_previos = []
                        if not df.empty and "Title" in df.columns:
                            titulos_previos = df["Title"].astype(str).tolist()

                        respuesta_csv = enviar_a_gemini(
                            prompt_generar_escenarios_profesionales(
                                descripcion_refinada,
                                contexto_original=texto_entrada,
                                target_cases=objetivo_casos,
                                min_cases=min_casos_aceptables,
                                titulos_excluir=titulos_previos
                            )
                        )
                        texto_csv_raw = extraer_texto_de_respuesta_gemini(respuesta_csv).strip()

                        # Limpieza y normalización CSV → DF
                        csv_limpio = limpiar_markdown_csv(texto_csv_raw)
                        csv_valido = limpiar_csv_con_formato(csv_limpio, columnas_esperadas=6)
                        csv_corregido = corregir_csv_con_comas(csv_valido, columnas_objetivo=6)

                        df_intento = pd.read_csv(io.StringIO(csv_corregido))
                        df_intento = df_intento.applymap(lambda x: x.strip() if isinstance(x, str) else x)
                        df_intento = _normalizar_df_generado(df_intento)

                        if "Steps" in df_intento.columns:
                            df_intento["Steps"] = df_intento["Steps"].apply(normalizar_steps).str.replace(r'\\n', '\n', regex=True)
                        if "Preconditions" in df_intento.columns:
                            df_intento["Preconditions"] = df_intento["Preconditions"].apply(normalizar_preconditions)
                        df_intento["Estado"] = "Pendiente"

                        total_antes = len(df)
                        if df.empty:
                            df = df_intento.copy()
                        else:
                            if "Title" in df.columns and "Title" in df_intento.columns:
                                existentes = set(df["Title"].astype(str).str.strip().str.lower())
                                nuevos = df_intento[
                                    ~df_intento["Title"].astype(str).str.strip().str.lower().isin(existentes)
                                ].copy()
                            else:
                                nuevos = df_intento.copy()
                            df = pd.concat([df, nuevos], ignore_index=True)
                        crecieron = len(df) - total_antes

                        if len(df) >= objetivo_casos:
                            break

                        if intento_gen > 1 and crecieron == 0:
                            break

                        if intento_gen < max_intentos_generacion:
                            st.warning(
                                f"⚠️ Cobertura parcial ({len(df)} casos acumulados). "
                                "Reintentando generación para ampliar casos..."
                            )

                    if len(df) < min_casos_aceptables:
                        st.warning(
                            f"⚠️ Se generaron {len(df)} casos tras {max_intentos_generacion} intentos. "
                            f"Rango esperado por contexto: {min_casos_aceptables}-{objetivo_casos}."
                        )
                    elif len(df) < objetivo_casos:
                        st.info(
                            f"ℹ️ Se generaron {len(df)} casos reales según el contexto disponible. "
                            f"Objetivo estimado: {objetivo_casos}."
                        )

                st.session_state.df_editable = df
                st.session_state.generado = True

                st.session_state["historial_generaciones"].append({
                    "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "fuente": "QA",
                    "origen": "Generación inicial (con adjuntos)" if extra else "Generación inicial",
                    "descripcion": descripcion_refinada,
                    "escenarios": df.copy()
                })

            except Exception as e:
                st.error(f"❌ Error durante el proceso: {e}")
                st.text_area("⚠️ CSV que causó error", texto_csv_raw if 'texto_csv_raw' in locals() else "", height=250)
                st.session_state.df_editable = None
                st.session_state.generado = False

    # ---- Tabla paginada de escenarios generados ----
    if st.session_state.get("df_editable") is not None:
        render_df_paginado(
            st.session_state.df_editable,
            key_prefix="t1",
            filas_por_pagina=20,
            titulo="✅ Escenarios generados (vista paginada)"
        )

    # ---- Limpiar todo (dispara reset en el siguiente run) ----
    if st.button("🧹 Limpiar todo", key="btn_limpiar_tab1"):
        st.session_state["tab1_do_reset"] = True
        st.success("Se limpiará el contenido del Tab 1, adjuntos, preview y Sugerencias.")
        st.rerun()




with tab2:
    titulo_seccion("Editar escenarios generados", "🛠️")

    if not st.session_state.get("generado") or st.session_state.get("df_editable") is None:
        st.info("ℹ️ No hay escenarios generados para editar.")
    else:
        df = st.session_state.df_editable.copy()

        # Agregar columna de estado si no existe
        if "Estado" not in df.columns:
            df["Estado"] = "Pendiente"

        # Normalización de Steps, Expected y Preconditions
        if "Steps" in df.columns:
            df["Steps"] = df["Steps"].apply(normalizar_steps)
        if "Expected Result" in df.columns:
            df["Expected Result"] = df["Expected Result"].apply(normalizar_steps)
        if "Preconditions" in df.columns:
            df["Preconditions"] = df["Preconditions"].apply(normalizar_preconditions)

        df.reset_index(drop=True, inplace=True)

        edited_df = st.data_editor(
            df,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Priority": st.column_config.SelectboxColumn("Priority", options=["Alta", "Media", "Baja"]),
                "Type": st.column_config.SelectboxColumn("Type", options=["Funcional", "Validación", "Usabilidad", "Integración", "Seguridad"]),
                "Estado": st.column_config.SelectboxColumn("Estado", options=["Pendiente", "Listo", "Descartado"])
            }
        )

        st.session_state.df_editable = edited_df

        # Botón para marcar todos como listos
        if st.button("✅ Marcar todos como listos"):
            edited_df["Estado"] = "Listo"
            st.session_state.df_editable = edited_df
            st.success("Todos los escenarios han sido marcados como listos.")


# --------------------------- TAB 3: REVISAR / SUGERENCIAS ---------------------------
with tab3:
    st.subheader("💡 Sugerencias de nuevos escenarios a partir del análisis actual")

    df_actual = st.session_state.get("df_editable")
    if df_actual is None or df_actual.empty:
        st.info("ℹ️ No hay escenarios generados aún.")
    else:
        # Tomamos solo los estados de interés y las columnas necesarias
        columnas_base = ["Title", "Preconditions", "Steps", "Expected Result"]
        cols_presentes = [c for c in columnas_base if c in df_actual.columns]
        df_revisar = (
            df_actual.loc[df_actual["Estado"].isin(["Pendiente", "Listo"]), cols_presentes]
            .copy()
        )

        if df_revisar.empty:
            st.info("ℹ️ No hay datos para evaluar.")
        else:
            st.dataframe(df_revisar, use_container_width=True)

            # CSV de contexto para el LLM
            contexto_csv = df_revisar.to_csv(index=False)

            if st.button("🔍 Evaluar sugerencias", key="btn_eval_sug"):
                try:
                    prompt = {
                        "contents": [
                            {
                                "parts": [
                                    {
                                        "text": (
                                            "Eres un Analista QA Senior especializado en diseño de pruebas funcionales.\n\n"
                                            "A partir del CSV de escenarios existente, sugiere nuevos casos COMPLEMENTARIOS "
                                            "(sin repetir los actuales) y devuélvelos en **CSV puro** con columnas EXACTAS:\n"
                                            "Title,Preconditions,Steps,Expected Result\n\n"
                                            "REGLAS DE SALIDA (obligatorias):\n"
                                            "- SOLO imprime el CSV (sin explicaciones, sin markdown, sin texto adicional).\n"
                                            "- Usa comas como separador; si un campo contiene comas o saltos de línea, ENCERRAR en comillas dobles.\n"
                                            "- Steps numerados como '1. ', '2. ', '3. ', cada uno en su propia línea usando \\n dentro de la celda.\n"
                                            "- Genera 4–8 casos nuevos, profesionales y no redundantes con el contexto.\n\n"
                                            "PRECONDITIONS (formato y contenido OBLIGATORIOS):\n"
                                            "- Deben ir **enumeradas** y en **líneas separadas dentro de la misma celda** usando \\n.\n"
                                            "- Sigue SIEMPRE este patrón (según aplique por el escenario):\n"
                                            "  1. Aplicación disponible y sesión iniciada\n"
                                            "  2. Usuario con permisos para <ACCIÓN inferida de los Steps>\n"
                                            "  3. Existen <DATOS DE NEGOCIO requeridos> (p. ej., asiento contable X, movimientos en rango, cliente válido)\n"
                                            "  4. Servicios de <MÓDULO/SUBMÓDULO> <operativos | NO operativos (si el caso es negativo por indisponibilidad)>\n"
                                            "- Inferir **<ACCIÓN>** desde los Steps (mapa típico):\n"
                                            "    consultar/ver → 'consultar'; exportar/descargar → 'exportar';\n"
                                            "    generar reporte → 'consultar y generar reportes'; acceder → 'acceder al módulo';\n"
                                            "    crear/editar/eliminar → 'crear/editar/eliminar <objeto>' según corresponda.\n"
                                            "- Si los Steps implican error por caída/indisponibilidad → usa 'NO operativos'; de lo contrario 'operativos'.\n"
                                            "- Prohibido: 'Ninguna', 'N/A', o solo 'Usuario con sesión iniciada' sin permisos ni datos.\n\n"
                                            "CHECKLIST interno antes de responder (NO imprimir):\n"
                                            "- ¿Permisos alineados con la acción principal de los Steps? ✔\n"
                                            "- ¿Datos de negocio explícitos y realistas? ✔\n"
                                            "- ¿Servicios correctamente marcados operativos/NO operativos según el objetivo del caso? ✔\n"
                                            "- ¿Preconditions enumeradas con '\\n' dentro de la celda y sin duplicados? ✔\n\n"
                                            "Contexto (CSV existente):\n"
                                            f"{contexto_csv}"
                                        )
                                    }
                                ]
                            }
                        ]
                    }

                    # Llama a Gemini y limpia salida
                    respuesta = enviar_a_gemini(prompt)
                    texto_raw = extraer_texto_de_respuesta_gemini(respuesta)
                    texto_csv = limpiar_markdown_csv(texto_raw)

                    # Cargar sugerencias (4 columnas)
                    df_sugerencias = leer_csv_seguro(texto_csv, columnas_esperadas=4)

                    # No normalizamos Precondition localmente: dejamos el formato tal como viene de Gemini
                    # (sí limpiamos Steps para garantizar saltos de línea visibles)
                    if "Steps" in df_sugerencias.columns:
                        df_sugerencias["Steps"] = df_sugerencias["Steps"].apply(normalizar_steps)

                    # Completar metadatos faltantes para integrarse con el DF principal
                    for c, dflt in [("Type", "Funcional"), ("Priority", "Media"), ("Estado", "Pendiente")]:
                        if c not in df_sugerencias.columns:
                            df_sugerencias[c] = dflt

                    st.session_state["sugerencias_df"] = df_sugerencias
                    st.success("✅ Sugerencias generadas.")
                except Exception as e:
                    st.error(f"❌ Error al generar sugerencias: {e}")

    # Render de sugerencias si existen
    df_sugerencias = st.session_state.get("sugerencias_df")
    if isinstance(df_sugerencias, pd.DataFrame) and not df_sugerencias.empty:
        st.markdown("### 💡 Sugerencias de nuevos escenarios")
        st.dataframe(df_sugerencias, use_container_width=True)

        st.markdown("### ✅ Selecciona los escenarios que deseas aplicar:")
        seleccion_indices = []
        for i, row in df_sugerencias.iterrows():
            titulo = str(row.get("Title", f"Escenario {i}")).strip()
            if st.checkbox(titulo, key=f"t3_sug_{i}"):
                seleccion_indices.append(i)

        hay_seleccion = len(seleccion_indices) > 0

        if st.button("➕ Aplicar escenarios seleccionados", key="btn_aplicar_sug", disabled=not hay_seleccion):
            try:
                df_aplicar = df_sugerencias.loc[seleccion_indices].copy()

                # Evitar duplicados por Title contra el DF actual
                titulos_existentes = set(st.session_state["df_editable"]["Title"].astype(str))
                df_aplicar = df_aplicar[~df_aplicar["Title"].astype(str).isin(titulos_existentes)]

                if df_aplicar.empty:
                    st.info("ℹ️ Todos los seleccionados ya estaban aplicados o no hay nuevos.")
                else:
                    # Alinear columnas con df_editable
                    cols_destino = list(st.session_state["df_editable"].columns)
                    for c in cols_destino:
                        if c not in df_aplicar.columns:
                            df_aplicar[c] = ""  # relleno vacío para columnas faltantes
                    df_aplicar = df_aplicar[cols_destino]

                    # Actualiza el DF principal
                    st.session_state["df_editable"] = pd.concat(
                        [st.session_state["df_editable"], df_aplicar], ignore_index=True
                    )
                    st.session_state["generado"] = True

                    # Guarda en historial
                    st.session_state.setdefault("historial_generaciones", [])
                    st.session_state["historial_generaciones"].append({
                        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "origen": "Sugerencias",
                        "escenarios": df_aplicar.copy()
                    })

                    st.success(f"✅ {len(df_aplicar)} escenario(s) aplicados. Revisa 'Historial' y 'Subir a TestRail'.")
            except Exception as e:
                st.error(f"❌ Error al aplicar sugerencias: {e}")


# --------------------------- TAB 4: HISTORIAL ---------------------------
with tab4:
    if "historial_generaciones" not in st.session_state:
        st.session_state["historial_generaciones"] = []

    historial = st.session_state["historial_generaciones"]

    if not historial:
        st.info(
            "ℹ️ Aún no hay historial disponible. Genera escenarios para comenzar a registrar."
        )
    else:
        resumen = pd.DataFrame(
            [
                {
                    "Fecha": item["fecha"],
                    "Fuente": f"{item.get('fuente', 'Desconocida')} ({item.get('origen', 'N/A')})",
                    "Escenarios": len(item["escenarios"]),
                    "Ver": f"📝 Ver #{i}",
                }
                for i, item in enumerate(historial)
            ]
        )

        st.markdown("### 🧾 Generaciones previas")
        st.dataframe(resumen, use_container_width=True, hide_index=True)

        seleccion = st.selectbox(
            "Selecciona una generación para revisar:",
            options=[
                f"#{i+1} | {item['fecha']} ({item.get('fuente', 'N/A')})"
                for i, item in enumerate(historial)
            ],
            index=len(historial) - 1,
        )

        idx = int(seleccion.split("|")[0].replace("#", "")) - 1
        item = historial[idx]

        if st.button("↩ Restaurar esta generación"):
            st.session_state.df_editable = item["escenarios"].copy()
            st.success("✅ Escenarios restaurados.")
            st.rerun()

# --------------------------- TAB 5: SUBIR A TESTRAIL ---------------------------
# --------------------------- TAB 5: SUBIR A TESTRAIL ---------------------------
with tab5:
    st.subheader("🚀 Subir casos a TestRail")

    # 📡 Obtener proyectos desde TestRail
    proyectos_raw = obtener_proyectos()

    # 🛡️ Validación segura del formato
    if isinstance(proyectos_raw, dict) and "projects" in proyectos_raw:
        proyectos = proyectos_raw["projects"]
    else:
        st.error("❌ Formato inesperado al recibir proyectos.")
        st.stop()

    # 🎛️ Selector de proyecto
    sel_proy = st.selectbox("Proyecto", [p["name"] for p in proyectos], key="select_proy")
    id_proy = next((p["id"] for p in proyectos if p["name"] == sel_proy), None)

    # 📢 Mostrar anuncio del proyecto (si existe)
    anuncio = next((p.get("announcement") for p in proyectos if p["id"] == id_proy), None)
    if anuncio:
        st.info(f"📢 {anuncio}")

    # 📁 Obtener suites del proyecto
    suites_raw = obtener_suites(id_proy)
    if isinstance(suites_raw, dict) and "suites" in suites_raw:
        suites = suites_raw["suites"]
    elif isinstance(suites_raw, list):
        suites = suites_raw
    else:
        st.error("❌ Error al recibir suites desde TestRail.")
        st.json(suites_raw)
        st.stop()

    sel_suite = st.selectbox("Suite", [s["name"] for s in suites], key="select_suite")
    suite_id = next((s["id"] for s in suites if s["name"] == sel_suite), None)

    # 📂 Obtener secciones de la suite
    secciones_raw = obtener_secciones(id_proy, suite_id)
    if isinstance(secciones_raw, dict) and "sections" in secciones_raw:
        secciones = secciones_raw["sections"]
    elif isinstance(secciones_raw, list):
        secciones = secciones_raw
    else:
        st.error("❌ Error al recibir secciones desde TestRail.")
        st.json(secciones_raw)
        st.stop()

    sel_seccion = st.selectbox("Sección", [s["name"] for s in secciones], key="select_seccion")
    section_id = next((s["id"] for s in secciones if s["name"] == sel_seccion), None)

    # ✅ Validar si hay escenarios generados para subir
    df = st.session_state.get("df_editable")

    if df is not None and section_id:
        st.markdown("### 🧪 Vista previa de los casos a subir")
        st.dataframe(df, use_container_width=True)

        # —————————————————— CONFIRMACIÓN EN DOS PASOS ——————————————————
        # 1) Primer click: pedir confirmación y guardar selección
        if st.button("📤 Subir casos a TestRail", key="btn_subir_preconfirm"):
            st.session_state["confirm_subida"] = {
                "proyecto": sel_proy,
                "suite": sel_suite,
                "seccion": sel_seccion,
                "section_id": section_id,
                "total": len(df)
            }
            st.rerun()

        # 2) Si hay confirmación pendiente, mostrar resumen + Confirmar/Cancelar
        confirm_ctx = st.session_state.get("confirm_subida")
        if confirm_ctx:
            st.markdown("#### 🔎 Confirma antes de subir")
            st.info(
                f"**Proyecto:** {confirm_ctx['proyecto']}\n\n"
                f"**Suite:** {confirm_ctx['suite']}\n\n"
                f"**Sección:** {confirm_ctx['seccion']}\n\n"
                f"**Casos a subir:** {confirm_ctx['total']}"
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ Confirmar subida", key="btn_confirmar_subida"):
                    with st.spinner("📡 Subiendo casos..."):
                        resultado = enviar_a_testrail(confirm_ctx["section_id"], df)  # usa mapping title/custom_*

                    # Limpiar estado de confirmación
                    st.session_state.pop("confirm_subida", None)

                    if resultado["exito"]:
                        st.success(f"✅ {resultado['subidos']} casos subidos correctamente.")
                        st.rerun()
                    else:
                        st.error(f"❌ Solo se subieron {resultado['subidos']} de {resultado['total']} casos.")
                        if resultado["detalle"]:
                            with st.expander("🔍 Ver detalles del error"):
                                for err in resultado["detalle"]:
                                    st.write(err)
            with c2:
                if st.button("❌ Cancelar", key="btn_cancelar_subida"):
                    st.session_state.pop("confirm_subida", None)
                    st.toast("Operación cancelada", icon="❌")
                    st.rerun()
        # ——————————————————————————————————————————————————————————————
    else:
        st.info("Genera los casos en el Tab '✏️ Generar' y selecciona Proyecto, Suite y Sección.")
