# ============================ Cleantest.py (LIMPIO + PATCH + HEADER FIX) ============================
import io
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

_CURRENT_DIR = Path(__file__).resolve().parent
if str(_CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(_CURRENT_DIR))

from utils_ingest import consolidate_attachments

# ──── Persistencia del historial ────────────────────────────────────────────
_HISTORIAL_PATH = "historial_generaciones.json"

def _serializar_historial(historial: list) -> list:
    result = []
    for item in historial:
        entry = {k: v for k, v in item.items() if k != "escenarios"}
        esc = item.get("escenarios")
        if esc is not None:
            try:
                entry["escenarios"] = esc.to_dict(orient="records")
            except Exception:
                entry["escenarios"] = []
        result.append(entry)
    return result

def _deserializar_historial(data: list) -> list:
    result = []
    for item in data:
        entry = {k: v for k, v in item.items() if k != "escenarios"}
        esc = item.get("escenarios")
        if esc is not None:
            try:
                entry["escenarios"] = pd.DataFrame(esc)
            except Exception:
                entry["escenarios"] = pd.DataFrame()
        result.append(entry)
    return result

def guardar_historial(historial: list) -> None:
    try:
        with open(_HISTORIAL_PATH, "w", encoding="utf-8") as f:
            json.dump(_serializar_historial(historial), f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def cargar_historial() -> list:
    if not os.path.exists(_HISTORIAL_PATH):
        return []
    try:
        with open(_HISTORIAL_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _deserializar_historial(data)
    except Exception:
        return []
# ────────────────────────────────────────────────────────────────────────────


# 1) SIEMPRE la primera llamada Streamlit
st.set_page_config(page_title="Generador QA", layout="wide", initial_sidebar_state="collapsed")

# 2) Importar utilidades propias SOLO una vez
from auth_ui import SecureShell
from utils_ui import titulo_seccion, spinner_accion
from utils_csv import (
    limpiar_markdown_csv, normalizar_preconditions, corregir_csv_con_comas,
    normalizar_steps, limpiar_csv_con_formato, leer_csv_seguro, limpiar_texto_qa,
    detectar_y_separar_escenarios_compuestos,
)
from utils_testrail import (
    obtener_proyectos, obtener_suites, obtener_secciones, enviar_a_testrail
)
from utils_gemini import (
    enviar_a_gemini, extraer_texto_de_respuesta_gemini,
    prompt_generar_escenarios_profesionales, limitar_texto_para_gemini
)
from qa_engine import (
    analyze_document_structure,
    build_testrail_export_dataframe,
    enforce_expected_results_quality,
    estimate_scenario_volume,
    parse_gemini_json_response,
    prepare_extended_export,
    summarize_analysis_for_prompt,
    scenarios_dataframe_to_csv,
    validate_and_prepare_scenarios,
)

# 3) Login + tamaños independientes
shell = SecureShell(
    auth_yaml=".streamlit/auth.yaml",
    login_page_width=560,
    app_page_width=1600,
    logout_top=12,
    logout_right=96,
)
if not shell.login():
    st.stop()

# ============================ APP (UNA SOLA VEZ) ============================
shell.render_header("🧪 Generador de Escenarios QA para TestRail")

# Estado global
if "historial_generaciones" not in st.session_state:
    st.session_state["historial_generaciones"] = cargar_historial()
st.session_state.setdefault("historial", [])
st.session_state.setdefault("df_editable", None)
st.session_state.setdefault("generado", False)
st.session_state.setdefault("texto_funcional", "")
st.session_state.setdefault("descripcion_refinada", "")
st.session_state.setdefault("analisis_documento", {})
st.session_state.setdefault("ultima_validacion_qa", {})

# Tabs principales
tab1, tab2 = st.tabs(["✏️ Generar", "📚 Historial"])

def limpiar_pestanas():
    """Limpia variables de estado menos el historial."""
    keys_keep = {"historial_generaciones"}
    for key in list(st.session_state.keys()):
        if key not in keys_keep:
            st.session_state[key] = [] if isinstance(st.session_state.get(key), list) else ""
            if key in ("df_editable", "generado"):
                st.session_state[key] = None if key == "df_editable" else False


st.divider()


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

def preview_document_paginado_inline(
    file_label: str,
    file_name: str = "",
    file_bytes: bytes | None = None,
    text_extraido: str | None = None,
    tipo: str | None = None,
    key_ns: str = "pview",
    collapsible: bool = True,
    expanded: bool = False
):
    """Renderiza un preview paginado (PDF como imágenes, texto paginado) con expander opcional."""
    if not tipo and file_name:
        tipo = "pdf" if file_name.lower().endswith(".pdf") else "texto"
    tipo = tipo or ("texto" if text_extraido is not None else "pdf")
    state_key = f"{key_ns}:{file_label}:{file_name}:page"

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
# TAB 1 — RESET PRE-RUN (se ejecuta ANTES de crear widgets)
# =========================
import io, re
from datetime import datetime
import pandas as pd
import streamlit as st

if st.session_state.get("tab1_do_reset", False):
    st.session_state["texto_funcional"]   = ""
    st.session_state["attachments_text"]  = ""
    st.session_state["attachments_meta"]  = []
    st.session_state["use_attachments"]   = True
    st.session_state["df_editable"]       = None
    st.session_state["generado"]          = False
    st.session_state["descripcion_refinada"] = ""
    st.session_state["analisis_documento"] = {}
    st.session_state["ultima_validacion_qa"] = {}
    st.session_state["tab1_input_mode"]   = None
    st.session_state["t1_show_testrail"]  = False

    for k in list(st.session_state.keys()):
        if k.startswith("t1:") or k.startswith("pview:") or (":page" in k):
            st.session_state.pop(k, None)

    st.session_state["tab1_uploader_nonce"] = st.session_state.get("tab1_uploader_nonce", 0) + 1

    suger_keys = [
        "sugerencias_df", "sugerencias_seleccionadas", "sugerencias_aplicadas",
        "df_sugerencias", "df_sugerencias_edit", "sugerencias_table_state",
        "sugerencias_csv_raw", "sugerencias_preview", "sugerencias_selected_rows",
        "tab3_uploader_nonce", "tab3:page_state", "tab3:filters"
    ]
    for k in list(st.session_state.keys()):
        if k in suger_keys or k.startswith("suger") or k.startswith("tab3:"):
            st.session_state.pop(k, None)

    st.session_state.pop("tab1_do_reset", None)

# ---------- ESTADOS INICIALES (defaults) ----------
st.session_state.setdefault("attachments_text", "")
st.session_state.setdefault("attachments_meta", [])
st.session_state.setdefault("use_attachments", True)
st.session_state.setdefault("df_editable", None)
st.session_state.setdefault("generado", False)
st.session_state.setdefault("descripcion_refinada", "")
if "historial_generaciones" not in st.session_state:
    st.session_state["historial_generaciones"] = cargar_historial()
st.session_state.setdefault("tab1_uploader_nonce", 0)
st.session_state.setdefault("tab1_input_mode", None)
st.session_state.setdefault("tab1_last_upload_signature", ())


# =========================
# TAB 1 — WIZARD MODERNO
# =========================
with tab1:

    # ─────────────────────────── CSS WIZARD ───────────────────────────
    st.markdown("""<style>

/* ══════════════════════════════════════════
   GLOBAL — App background & typography
══════════════════════════════════════════ */
[data-testid="stAppViewContainer"]{background:#f8fafc!important}
[data-testid="stHeader"]{background:transparent!important}
[data-testid="block-container"]{padding-top:1.6rem!important}
section[data-testid="stSidebar"]{background:#fff!important}

/* ══════════════════════════════════════════
   STEP BAR
══════════════════════════════════════════ */
.wz-bar{
    display:flex;align-items:flex-start;
    background:#fff;
    border:1px solid #e2e8f0;
    border-radius:16px;
    padding:20px 28px;
    margin-bottom:24px;
    box-shadow:0 1px 4px rgba(0,0,0,.06);
}
.wz-step{display:flex;flex-direction:column;align-items:center;flex:1;position:relative}
.wz-circle{
    width:36px;height:36px;border-radius:50%;
    display:flex;align-items:center;justify-content:center;
    font-size:13px;font-weight:800;flex-shrink:0;
    transition:all .25s;
}
.wz-circle.done{
    background:#10b981;color:#fff;
    box-shadow:0 2px 8px rgba(16,185,129,.35);
}
.wz-circle.active{
    background:#ef4444;color:#fff;
    box-shadow:0 0 0 5px rgba(239,68,68,.15),0 4px 12px rgba(239,68,68,.4);
    transform:scale(1.08);
}
.wz-circle.pending{background:#e5e7eb;color:#9ca3af}
.wz-lbl{
    font-size:10.5px;margin-top:7px;color:#9ca3af;
    text-align:center;max-width:70px;line-height:1.4;
    font-weight:500;letter-spacing:.2px;
}
.wz-lbl.active{color:#ef4444;font-weight:800}
.wz-lbl.done{color:#059669;font-weight:600}
.wz-line{
    position:absolute;top:18px;
    left:calc(50% + 18px);right:calc(-50% + 18px);
    height:2px;background:#e5e7eb;border-radius:2px;
}
.wz-line.done{background:linear-gradient(90deg,#10b981,#34d399)}
.wz-step:last-child .wz-line{display:none}

/* ══════════════════════════════════════════
   SECTION HEADER  (qa-card-hdr)
══════════════════════════════════════════ */
.qa-card-hdr{
    font-size:16px;font-weight:800;color:#0f172a;
    margin-bottom:20px;
    display:flex;align-items:center;gap:10px;
    padding-bottom:14px;
    border-bottom:1px solid #f1f5f9;
    letter-spacing:-.2px;
}

/* ══════════════════════════════════════════
   SOURCE CARDS  (Step 1)
══════════════════════════════════════════ */
.sc-wrap button,
.sc-sel button{
    width:100%!important;
    min-height:120px!important;
    border-radius:14px!important;
    border:2px solid #e2e8f0!important;
    background:#ffffff!important;
    padding:18px 16px!important;
    text-align:left!important;
    white-space:pre-wrap!important;
    font-size:13.5px!important;
    line-height:1.6!important;
    box-shadow:0 2px 8px rgba(0,0,0,.05)!important;
    transition:all .2s cubic-bezier(.4,0,.2,1)!important;
    color:#1e293b!important;
    cursor:pointer!important;
}
.sc-wrap button:hover{
    border-color:#ef4444!important;
    box-shadow:0 6px 18px rgba(239,68,68,.18)!important;
    transform:translateY(-3px)!important;
    background:#fff!important;
}
.sc-sel button{
    border-color:#ef4444!important;
    background:linear-gradient(145deg,#fff5f5,#ffffff)!important;
    box-shadow:0 0 0 3px rgba(239,68,68,.12),0 6px 20px rgba(239,68,68,.2)!important;
    transform:translateY(-2px)!important;
}
/* ══════════════════════════════════════════
   TEXTAREA  — visual prominence
══════════════════════════════════════════ */
[data-testid="stTextArea"] textarea{
    border:1.5px solid #e2e8f0!important;
    border-radius:12px!important;
    padding:16px!important;
    font-size:14px!important;
    line-height:1.65!important;
    color:#1e293b!important;
    background:#fdfdff!important;
    box-shadow:inset 0 2px 4px rgba(0,0,0,.04)!important;
    transition:border-color .18s,box-shadow .18s!important;
}
[data-testid="stTextArea"] textarea:focus{
    border-color:#ef4444!important;
    box-shadow:0 0 0 3px rgba(239,68,68,.1),inset 0 2px 4px rgba(0,0,0,.03)!important;
    outline:none!important;
}

/* ══════════════════════════════════════════
   GENERATE BUTTON  (gen-wrap)
══════════════════════════════════════════ */
.gen-wrap button{
    background:#ef4444!important;
    color:#fff!important;
    border:none!important;
    border-radius:12px!important;
    padding:18px 24px!important;
    font-size:16px!important;
    font-weight:800!important;
    width:100%!important;
    letter-spacing:.3px!important;
    box-shadow:0 6px 20px rgba(239,68,68,.4),0 2px 6px rgba(239,68,68,.2)!important;
    transition:all .22s cubic-bezier(.4,0,.2,1)!important;
    min-height:58px!important;
}
.gen-wrap button:hover:not(:disabled){
    background:#dc2626!important;
    box-shadow:0 10px 28px rgba(239,68,68,.5),0 3px 8px rgba(239,68,68,.25)!important;
    transform:translateY(-2px)!important;
}
.gen-wrap button:disabled{
    background:#cbd5e1!important;
    color:#94a3b8!important;
    box-shadow:none!important;
    transform:none!important;
    cursor:not-allowed!important;
}

/* ══════════════════════════════════════════
   BADGES
══════════════════════════════════════════ */
.bdg{
    padding:3px 10px;border-radius:20px;
    font-size:11.5px;font-weight:700;
    display:inline-block;vertical-align:middle;
    margin-right:5px;margin-bottom:4px;
}
.bdg-g{background:#d1fae5;color:#065f46}
.bdg-r{background:#fee2e2;color:#991b1b}
.bdg-y{background:#fef3c7;color:#92400e}
.bdg-b{background:#dbeafe;color:#1e40af}
.bdg-p{background:#ede9fe;color:#5b21b6}
.bdg-gr{background:#f1f5f9;color:#475569}

/* ══════════════════════════════════════════
   PILLS  (summary bar)
══════════════════════════════════════════ */
.pill{
    background:#f1f5f9;border:1px solid #e2e8f0;
    border-radius:10px;padding:8px 16px;
    display:inline-block;font-size:13px;
    margin-right:8px;margin-bottom:10px;
    color:#334155;font-weight:500;
}
.pill b{color:#ef4444;font-weight:800}

/* ══════════════════════════════════════════
   TESTRAIL SECTION  — cierre de flujo
══════════════════════════════════════════ */
.tr-header{
    background:linear-gradient(135deg,#6366f1 0%,#4f46e5 100%);
    padding:20px 28px;
    display:flex;align-items:center;justify-content:space-between;
    gap:16px;
}
.tr-header-title{
    font-size:17px;font-weight:800;color:#ffffff;
    letter-spacing:-.2px;
}
.tr-header-sub{
    font-size:12.5px;color:rgba(255,255,255,.8);
    margin-top:3px;
}
.tr-summary{
    display:flex;align-items:center;gap:12px;
    background:#f0f4ff;
    border:1px solid #c7d2fe;
    border-radius:10px;
    padding:12px 18px;
    margin-bottom:20px;
    font-size:13.5px;
    color:#1e293b;
}
.tr-summary strong{color:#4f46e5;font-size:20px;font-weight:800;margin-right:4px}
.tr-badge{
    background:#e0e7ff;color:#3730a3;
    border-radius:6px;padding:3px 10px;
    font-size:11.5px;font-weight:700;
    display:inline-block;margin-left:6px;
}
.tr-select-lbl{
    font-size:12px;font-weight:700;
    color:#374151;letter-spacing:.3px;
    text-transform:uppercase;margin-bottom:4px;
}
.tr-divider{
    border:none;border-top:1px solid #e5e7eb;
    margin:18px 0;
}

/* ── Upload CTA button ── */
.tr-upload-wrap button{
    background:#10b981!important;
    color:#fff!important;
    border:none!important;
    border-radius:12px!important;
    padding:16px 24px!important;
    font-size:15px!important;
    font-weight:800!important;
    width:100%!important;
    letter-spacing:.2px!important;
    box-shadow:0 6px 20px rgba(16,185,129,.38)!important;
    transition:all .22s!important;
    min-height:54px!important;
}
.tr-upload-wrap button:hover:not(:disabled){
    background:#059669!important;
    box-shadow:0 10px 28px rgba(16,185,129,.48)!important;
    transform:translateY(-2px)!important;
}
.tr-upload-wrap button:disabled{
    background:#cbd5e1!important;color:#94a3b8!important;
    box-shadow:none!important;transform:none!important;
}

/* ── Connect button ── */
.tr-connect-wrap button{
    background:#6366f1!important;
    color:#fff!important;
    border:none!important;
    border-radius:10px!important;
    padding:12px 24px!important;
    font-size:14px!important;
    font-weight:700!important;
    box-shadow:0 4px 14px rgba(99,102,241,.3)!important;
    transition:all .2s!important;
}
.tr-connect-wrap button:hover{
    background:#4f46e5!important;
    box-shadow:0 6px 20px rgba(99,102,241,.42)!important;
    transform:translateY(-1px)!important;
}

/* ══════════════════════════════════════════
   MISC — file uploader, data editor
══════════════════════════════════════════ */
[data-testid="stFileUploader"]{
    border:2px dashed #dbe3ea!important;
    border-radius:12px!important;
    background:#f8fafc!important;
    padding:8px!important;
}
[data-testid="stFileUploader"]:hover{border-color:#ef4444!important}

button[kind="secondary"]{
    border-radius:10px!important;
    border:1.5px solid #dbe3ea!important;
    color:#374151!important;
    font-weight:600!important;
    transition:all .18s!important;
}
button[kind="secondary"]:hover{
    border-color:#ef4444!important;
    color:#ef4444!important;
    background:#fff5f5!important;
}

[data-testid="stDataEditor"]{
    border:1px solid #dbe3ea!important;
    border-radius:12px!important;
    overflow:hidden!important;
}

/* selectbox labels */
[data-testid="stSelectbox"] label{
    font-size:12px!important;font-weight:700!important;
    color:#374151!important;letter-spacing:.3px!important;
    text-transform:uppercase!important;
}
</style>""", unsafe_allow_html=True)

    # ─────────────────────────── STATE DEFAULTS ───────────────────────
    st.session_state.setdefault("attachments_text", "")
    st.session_state.setdefault("attachments_meta", [])
    st.session_state.setdefault("use_attachments", True)
    st.session_state.setdefault("tab1_uploader_nonce", 0)
    st.session_state.setdefault("tab1_do_reset", False)
    st.session_state.setdefault("tab1_input_mode", None)
    st.session_state.setdefault("tab1_last_upload_signature", ())
    st.session_state.setdefault("test_types", ["Positivas", "Negativas"])
    st.session_state.setdefault("detail_level", "Detallado")
    st.session_state.setdefault("output_format", "TestRail")
    st.session_state.setdefault("t1_show_testrail", False)

    modo_ingreso   = st.session_state.get("tab1_input_mode")
    usar_adj       = modo_ingreso == "Documento"
    st.session_state["use_attachments"] = usar_adj

    tiene_texto    = bool(st.session_state.get("texto_funcional", "").strip())
    tiene_adjuntos = bool(st.session_state.get("attachments_text", ""))
    input_listo    = (modo_ingreso == "Texto" and tiene_texto) or \
                     (modo_ingreso == "Documento" and tiene_adjuntos)
    ya_generado    = bool(st.session_state.get("generado", False))

    # ─────────────────────────── STEP BAR ─────────────────────────────
    STEP_NAMES = ["Fuente", "Contexto", "Generar", "Preview", "TestRail"]

    subido_ok = st.session_state.get("t1_subido_ok", False)

    def _sstate(n):
        if n == 1: return "done" if modo_ingreso else "active"
        if n == 2:
            if not modo_ingreso: return "pending"
            return "done" if input_listo else "active"
        if n == 3:
            if not input_listo: return "pending"
            return "done" if ya_generado else "active"
        if n == 4: return "done" if subido_ok else ("active" if ya_generado else "pending")
        if n == 5: return "done" if subido_ok else ("active" if ya_generado else "pending")
        return "pending"

    bar_html = '<div class="wz-bar">'
    for i, name in enumerate(STEP_NAMES):
        s     = _sstate(i + 1)
        icon  = "✓" if s == "done" else str(i + 1)
        l_cls = f"done" if s == "done" else ("active" if s == "active" else "")
        bar_html += (
            f'<div class="wz-step">'
            f'<div class="wz-circle {s}">{icon}</div>'
            f'<div class="wz-lbl {l_cls}">{name}</div>'
            f'<div class="wz-line {"done" if s=="done" else ""}"></div>'
            f'</div>'
        )
    bar_html += '</div>'
    st.markdown(bar_html, unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════
    # STEP 1 — FUENTE
    # ══════════════════════════════════════════════════════════════
    st.markdown('<div class="qa-card-hdr">① Selecciona la fuente de información</div>', unsafe_allow_html=True)

    CARDS = [
        ("Texto libre", "📝", "Escribe el requerimiento\no historia de usuario", "Texto"),
        ("Documento",   "📄", "Sube PDF, DOCX, XLSX,\nimágenes y más",           "Documento"),
    ]

    _gap_l, col_a, col_b, _gap_r = st.columns([1, 3, 3, 1], gap="small")
    for col, (title, icon, desc, mode_val) in zip([col_a, col_b], CARDS):
        is_sel  = (modo_ingreso == mode_val)
        wrap    = "sc-sel" if is_sel else "sc-wrap"
        btn_key = f"src_card_{mode_val}"
        with col:
            st.markdown(f'<div class="{wrap}">', unsafe_allow_html=True)
            lbl = f"{icon} **{title}**\n\n{desc}"
            if st.button(lbl, key=btn_key, use_container_width=True):
                st.session_state["tab1_input_mode"] = mode_val
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

    # ─────────────────────────── HELPER: procesar uploads ─────────────
    def _procesar_uploads_tab1(archivos_subidos):
        if not archivos_subidos:
            st.session_state["attachments_text"] = ""
            st.session_state["attachments_meta"] = []
            st.session_state["tab1_last_upload_signature"] = ()
            return False
        try:
            from utils_ingest import consolidate_attachments
        except Exception:
            consolidate_attachments = None
        if consolidate_attachments is None:
            st.error("❌ Falta utils_ingest.consolidate_attachments.")
            return False
        files = [(f.name, f.getvalue()) for f in archivos_subidos]
        txt, metas = consolidate_attachments(files, max_chars=60_000)
        st.session_state["attachments_text"] = txt or ""
        st.session_state["attachments_meta"] = metas or []
        st.session_state["tab1_last_upload_signature"] = tuple(
            (f.name, len(f.getvalue())) for f in archivos_subidos
        )
        return True

    # ══════════════════════════════════════════════════════════════
    # STEP 2 — INPUT
    # ══════════════════════════════════════════════════════════════
    uploads = []
    if modo_ingreso:
        st.markdown('<div class="qa-card-hdr">② Contexto de entrada</div>', unsafe_allow_html=True)

        if modo_ingreso == "Texto":
            st.text_area(
                "Contexto funcional",
                height=220,
                key="texto_funcional",
                placeholder=(
                    "Ejemplo:\n"
                    "Como usuario registrado quiero poder iniciar sesión con correo y contraseña.\n\n"
                    "Reglas de negocio:\n"
                    "• El email es obligatorio y debe tener formato válido\n"
                    "• La contraseña debe tener mínimo 8 caracteres\n"
                    "• Tras 3 intentos fallidos la cuenta se bloquea temporalmente"
                ),
                label_visibility="collapsed",
            )
            chars = len(st.session_state.get("texto_funcional", ""))
            if chars > 0:
                st.caption(f"📊 {chars:,} caracteres · ~{chars // 5} palabras")

        elif modo_ingreso == "Documento":
            uploads = st.file_uploader(
                "Arrastra o selecciona archivos (PDF, DOCX, XLSX, imágenes…)",
                type=["pdf","docx","txt","csv","xlsx","png","jpg","jpeg","webp","tiff"],
                accept_multiple_files=True,
                key=f"tab1_uploader_{st.session_state['tab1_uploader_nonce']}",
                label_visibility="collapsed",
            )
            firmas_act = tuple((f.name, len(f.getvalue())) for f in uploads) if uploads else ()
            if uploads and firmas_act != st.session_state.get("tab1_last_upload_signature", ()):
                with st.spinner("📄 Procesando documentos..."):
                    if _procesar_uploads_tab1(uploads):
                        n = len(st.session_state["attachments_meta"])
                        st.success(f"✅ {n} archivo(s) procesados correctamente.")
            elif not uploads and st.session_state.get("tab1_last_upload_signature"):
                _procesar_uploads_tab1([])

            metas = st.session_state.get("attachments_meta", [])
            if metas:
                c_meta, c_rep = st.columns([4, 1])
                with c_meta:
                    for m in metas:
                        kb = round(m["size_bytes"] / 1024, 1)
                        st.caption(f"📎 **{m['filename']}** — {m['ext'].upper()} · {kb} KB · {m['chars']:,} chars")
                with c_rep:
                    if st.button("🔄 Reprocesar", key="btn_reprocesar"):
                        if uploads:
                            with st.spinner("Reprocesando…"):
                                _procesar_uploads_tab1(uploads)
                        else:
                            st.info("Sin archivos.")

            if uploads:
                with st.expander("📑 Preview de documentos", expanded=False):
                    for i, f in enumerate(uploads, 1):
                        bts = f.getvalue() if hasattr(f, "getvalue") else f.read()
                        preview_document_paginado_inline(
                            file_label=f"Archivo {i}: {f.name}",
                            file_name=f.name, file_bytes=bts,
                            tipo="pdf" if f.name.lower().endswith(".pdf") else "texto",
                            key_ns="t1", collapsible=False, expanded=False,
                        )
            elif st.session_state.get("attachments_text"):
                with st.expander("📑 Preview del texto consolidado", expanded=False):
                    preview_document_paginado_inline(
                        file_label="Texto consolidado",
                        file_name="adjuntos.txt",
                        text_extraido=st.session_state["attachments_text"],
                        tipo="texto", key_ns="t1", collapsible=False,
                    )

        # ─────────────────────────── NORMALIZERS ──────────────────────
        def _normalizar_type(valor):
            t = str(valor).strip().lower()
            if not t: return "Funcional"
            if "valid" in t: return "Validacion"
            if any(x in t for x in ("integr","api","servicio","motor")): return "Integracion"
            if any(x in t for x in ("segur","permis","autoriz","rol")): return "Seguridad"
            if any(x in t for x in ("usab","ux","mensaje")): return "Usabilidad"
            return "Funcional"

        def _normalizar_title(valor):
            tit = str(valor or "").strip()
            if not tit: return ""
            # 1) Eliminar prefijos semánticos al inicio: "Validación:", "Regla:", etc.
            _PREFIJOS = (
                r"manejo\s+de\s+error",
                r"validaci[oó]n",
                r"regla",
                r"error",
                r"escenario",
                r"caso(?:\s+de\s+prueba)?",
                r"caso",
            )
            tit = re.sub(
                r"^(?:" + "|".join(_PREFIJOS) + r")\s*:\s*",
                "", tit, flags=re.IGNORECASE,
            ).strip()
            # 2) Eliminar prefijos estructurales: SCENARIO, TC, numeraciones…
            for pat in [
                r"^(?:SCENARIO|TEST\s*CASE|TC)\s*[_:\-#]*\s*[\d\.]*\s*[:\-]*\s*",
                r"^\s*[\d]+\s*[\)\.\-:]\s*",
            ]:
                tit = re.sub(pat, "", tit, flags=re.IGNORECASE).strip()
            # 3) Limpiar caracteres residuales al inicio y capitalizar primera letra
            tit = limpiar_texto_qa(re.sub(r"^[\s\-\:\._]+", "", tit).strip())
            return tit[:1].upper() + tit[1:] if tit else ""

        def _normalizar_priority(valor):
            p = str(valor).strip().lower()
            if not p: return "Media"
            if any(x in p for x in ("alta","high","critical")): return "Alta"
            if any(x in p for x in ("baja","low")): return "Baja"
            return "Media"

        def _normalizar_df_generado(df_in):
            df_out = df_in.copy()
            for c in ["Title","Preconditions","Steps","Expected Result"]:
                if c in df_out.columns:
                    df_out[c] = df_out[c].apply(lambda x: limpiar_texto_qa(x) if isinstance(x, str) else x)
            if "Title"    in df_out.columns: df_out["Title"]    = df_out["Title"].apply(_normalizar_title)
            if "Type"     in df_out.columns: df_out["Type"]     = df_out["Type"].apply(_normalizar_type)
            if "Priority" in df_out.columns: df_out["Priority"] = df_out["Priority"].apply(_normalizar_priority)
            req = [c for c in ["Title","Steps","Expected Result"] if c in df_out.columns]
            if req:
                mask = pd.Series([True]*len(df_out))
                for c in req:
                    mask = mask & df_out[c].astype(str).str.strip().ne("")
                df_out = df_out.loc[mask].copy()
            if "Title" in df_out.columns:
                df_out = df_out.drop_duplicates(subset=["Title"], keep="first")
            return df_out.reset_index(drop=True)

        def _estimar_rango_casos(texto_base: str):
            txt   = (texto_base or "").strip()
            chars = len(txt)
            if   chars < 800:    obj = 10
            elif chars < 2_000:  obj = 14
            elif chars < 5_000:  obj = 18
            elif chars < 10_000: obj = 24
            else:                obj = 30
            pats = [r"\bvalid",r"\bregla",r"\berror",r"\bpermis",r"\brol",r"\bintegr",
                    r"\bapi",r"\bservicio",r"\bsegur",r"\bl[ií]mite",r"\bmin",r"\bmax",
                    r"\bc[aá]lcul",r"\btasa",r"\bplazo",r"\bgradiente",r"\breestruct",
                    r"\bauditor",r"\bnegativ"]
            hits = sum(1 for p in pats if re.search(p, txt, flags=re.IGNORECASE))
            obj += min(8, hits // 2)
            obj  = max(8, min(36, obj))
            return max(6, obj - 5), obj

        # ══════════════════════════════════════════════════════════════
        # STEP 3 — GENERAR
        # ══════════════════════════════════════════════════════════════
        tiene_texto    = bool(st.session_state.get("texto_funcional", "").strip())
        tiene_adjuntos = bool(st.session_state.get("attachments_text", ""))
        input_listo    = (modo_ingreso == "Texto" and tiene_texto) or \
                         (modo_ingreso == "Documento" and tiene_adjuntos)

        texto_base = (
            st.session_state.get("attachments_text","") if modo_ingreso == "Documento"
            else st.session_state.get("texto_funcional","")
        )
        st.markdown('<div class="qa-card-hdr">③ Generar escenarios</div>', unsafe_allow_html=True)

        gc_left, _gc_right = st.columns([3, 1])
        with gc_left:
            hint = (
                "El modelo generará los escenarios realmente justificables por el contexto."
                if input_listo
                else "Completa el paso 2 para habilitar la generación."
            )
            st.markdown(
                f'<p style="color:#6b7280;font-size:13px;margin-bottom:10px">{hint}</p>',
                unsafe_allow_html=True
            )
            st.markdown('<div class="gen-wrap">', unsafe_allow_html=True)
            generar_clicked = st.button(
                "⚡  Generar escenarios",
                key="btn_generar_tab1",
                disabled=not input_listo,
                use_container_width=True,
                help="Se habilita cuando ingresas texto o cuando se procesa al menos un documento.",
            )
            st.markdown('</div>', unsafe_allow_html=True)

        # ── Lógica de generación ──────────────────────────────────────
        respuesta_modelo_raw = ""
        if generar_clicked:
            if usar_adj and uploads and not st.session_state.get("attachments_text"):
                with st.spinner("📄 Procesando adjuntos…"):
                    _procesar_uploads_tab1(uploads)
            if modo_ingreso == "Texto" and not tiene_texto:
                st.warning("⚠️ Ingresa el contexto funcional.")
            elif modo_ingreso == "Documento" and not tiene_adjuntos:
                st.warning("⚠️ Adjunta al menos un documento válido.")
            else:
                try:
                    texto_entrada = (
                        st.session_state.get("attachments_text","").strip()
                        if modo_ingreso == "Documento"
                        else st.session_state["texto_funcional"].strip()
                    )
                    with st.spinner("🧠 Analizando documento…"):
                        analisis_documento = analyze_document_structure(texto_entrada)
                        descripcion_refinada = summarize_analysis_for_prompt(analisis_documento)
                        min_cases, target_cases = estimate_scenario_volume(texto_entrada, analisis_documento)
                    st.session_state["descripcion_refinada"] = descripcion_refinada
                    st.session_state["analisis_documento"] = analisis_documento

                    with st.spinner("📄 Generando escenarios…"):
                        respuesta_modelo_raw = ""
                        df = pd.DataFrame()
                        MAX_REINTENTOS = 2

                        for intento in range(1, MAX_REINTENTOS + 1):
                            resp = enviar_a_gemini(
                                prompt_generar_escenarios_profesionales(
                                    descripcion_refinada,
                                    contexto_original=texto_entrada,
                                    target_cases=target_cases,
                                    min_cases=min_cases,
                                    titulos_excluir=[],
                                    analisis_documento=analisis_documento,
                                )
                            )
                            respuesta_modelo_raw = extraer_texto_de_respuesta_gemini(resp).strip()

                            if not respuesta_modelo_raw:
                                if intento < MAX_REINTENTOS:
                                    continue
                                break

                            try:
                                payload = parse_gemini_json_response(respuesta_modelo_raw)
                                df_it, metadata_validacion = validate_and_prepare_scenarios(payload, analysis=analisis_documento)
                            except Exception:
                                if intento < MAX_REINTENTOS:
                                    continue
                                break

                            if df_it.empty:
                                if intento < MAX_REINTENTOS:
                                    continue
                                break

                            if "Steps" in df_it.columns:
                                df_it["Steps"] = df_it["Steps"].apply(normalizar_steps).str.replace(r'\\n','\n',regex=True)
                            if "Preconditions" in df_it.columns:
                                df_it["Preconditions"] = df_it["Preconditions"].apply(normalizar_preconditions)
                            if "Expected Result" in df_it.columns:
                                df_it["Expected Result"] = df_it["Expected Result"].apply(limpiar_texto_qa)
                            df_it["Estado"] = "Pendiente"
                            df_it = enforce_expected_results_quality(df_it, analysis=analisis_documento)
                            df = df_it.copy()
                            st.session_state["ultima_validacion_qa"] = metadata_validacion
                            break  # CSV válido y con datos — no reintentar

                    st.session_state.df_editable = df
                    st.session_state.generado    = True
                    st.session_state["historial_generaciones"].append({
                        "fecha":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "fuente":      "QA",
                        "origen":      "Generación inicial (con adjuntos)" if usar_adj else "Generación inicial",
                        "descripcion": descripcion_refinada,
                        "analisis_documento": analisis_documento,
                        "escenarios":  df.copy(),
                    })
                    guardar_historial(st.session_state["historial_generaciones"])
                    st.success(f"✅ Se generaron **{len(df)}** escenarios relevantes según el contexto.")
                    st.caption("ℹ️ Se priorizó calidad y relevancia sobre cantidad.")
                    if st.session_state.get("ultima_validacion_qa", {}).get("dropped"):
                        st.caption(
                            f"ℹ️ Se descartaron {len(st.session_state['ultima_validacion_qa']['dropped'])} escenarios por calidad/duplicidad antes de mostrar el resultado."
                        )

                except Exception as exc:
                    st.error(f"❌ Error durante la generación: {exc}")
                    if respuesta_modelo_raw:
                        st.text_area("⚠️ Respuesta del modelo que causó error", respuesta_modelo_raw, height=220)
                    st.session_state.df_editable = None
                    st.session_state.generado    = False

        # ══════════════════════════════════════════════════════════════
        # STEP 4 — RESULTADOS (tabla única: seleccionar + editar)
        # ══════════════════════════════════════════════════════════════
        if st.session_state.get("generado") and st.session_state.get("df_editable") is not None:
            df_prev = st.session_state.df_editable
            total   = len(df_prev)

            BADGE = {
                "Funcional":"bdg-g","Positiva":"bdg-g","Positivas":"bdg-g",
                "Validacion":"bdg-r","Negativa":"bdg-r","Negativas":"bdg-r",
                "Edge":"bdg-y","Seguridad":"bdg-p",
                "Integracion":"bdg-b","Integración":"bdg-b","Usabilidad":"bdg-gr",
            }

            st.markdown('<div class="qa-card-hdr">④ Resultados — revisa, selecciona y edita</div>', unsafe_allow_html=True)

            # Resumen con pills y badges
            type_cnt = df_prev["Type"].value_counts().to_dict() if "Type" in df_prev.columns else {}
            pills_html = f'<span class="pill">Total: <b>{total}</b></span>'
            for t, c in type_cnt.items():
                pills_html += f'<span class="bdg {BADGE.get(t,"bdg-gr")}">{t}: {c}</span>'
            st.markdown(pills_html, unsafe_allow_html=True)

            # Fila de botones superiores
            ac1, ac2, _ac3 = st.columns([2, 2, 3])
            with ac1:
                if st.button("🔄 Regenerar", key="btn_regen"):
                    st.session_state.generado    = False
                    st.session_state.df_editable = None
                    st.rerun()
            with ac2:
                st.caption(f"**{total}** escenarios generados")

            # ── Preparar df de trabajo ──────────────────────────────
            df_work = df_prev.copy()
            internal_cols = ["source_basis", "assumption", "quality_notes", "score", "flags"]
            if "Estado" not in df_work.columns:
                df_work["Estado"] = "Pendiente"
            if "Steps" in df_work.columns:
                df_work["Steps"] = df_work["Steps"].apply(normalizar_steps)
            if "Preconditions" in df_work.columns:
                df_work["Preconditions"] = df_work["Preconditions"].apply(normalizar_preconditions)
            df_work = enforce_expected_results_quality(df_work, analysis=st.session_state.get("analisis_documento", {}))
            df_work.reset_index(drop=True, inplace=True)
            internal_shadow = df_work[[c for c in internal_cols if c in df_work.columns]].copy()
            df_view = df_work.drop(columns=internal_cols, errors="ignore")
            if "✓" not in df_view.columns:
                df_view.insert(0, "✓", True)

            # ── TABLA ÚNICA: selección + edición inline ─────────────
            edited_unified = st.data_editor(
                df_view,
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                column_config={
                    "✓":        st.column_config.CheckboxColumn("✓", default=True, width="small"),
                    "Priority": st.column_config.SelectboxColumn("Priority", options=["Alta", "Media", "Baja"]),
                    "Type":     st.column_config.SelectboxColumn("Type", options=["Funcional", "Validación", "Usabilidad", "Integración", "Seguridad"]),
                    "Estado":   st.column_config.SelectboxColumn("Estado", options=["Pendiente", "Listo", "Descartado"]),
                },
                key="t1_data_editor_unified",
            )

            # Guardar estado de edición (sin la columna ✓)
            df_sin_check = edited_unified.drop(columns=["✓"], errors="ignore")
            st.session_state.df_editable = df_sin_check
            df_export_tr = build_testrail_export_dataframe(df_sin_check)
            df_for_extended = df_sin_check.copy()
            for col in internal_cols:
                if col in internal_shadow.columns:
                    df_for_extended[col] = internal_shadow[col].reindex(df_for_extended.index).fillna("")
            df_export_ext = prepare_extended_export(df_for_extended)

            # Estadística de selección
            sel_mask = edited_unified["✓"] == True
            n_sel    = int(sel_mask.sum())
            st.caption(f"**{n_sel}** de **{len(edited_unified)}** seleccionados")

            # Botones de acción sobre la tabla
            ca1, ca2, _ca3 = st.columns([2, 2, 3])
            with ca1:
                if st.button(
                    f"✅ Aplicar {n_sel} seleccionados",
                    key="btn_aplicar_sel",
                    disabled=n_sel == 0,
                ):
                    df_aplicado = edited_unified[sel_mask].drop(columns=["✓"]).reset_index(drop=True)
                    st.session_state.df_editable = df_aplicado
                    st.success(f"✅ {len(df_aplicado)} escenarios aplicados.")
            with ca2:
                if st.button("✅ Marcar todos como listos", key="btn_marcar_listos"):
                    df_sin_check["Estado"] = "Listo"
                    st.session_state.df_editable = df_sin_check
                    st.success("Todos los escenarios marcados como listos.")

            dl1, dl2, _dl3 = st.columns([2, 2, 3])
            with dl1:
                st.download_button(
                    "⬇️ Exportar CSV TestRail",
                    data=scenarios_dataframe_to_csv(df_export_tr, extended=False),
                    file_name="escenarios_testrail.csv",
                    mime="text/csv",
                    key="btn_download_testrail_csv",
                    use_container_width=True,
                )
            with dl2:
                st.download_button(
                    "⬇️ Exportar CSV extendido",
                    data=scenarios_dataframe_to_csv(df_export_ext, extended=True),
                    file_name="escenarios_extendido.csv",
                    mime="text/csv",
                    key="btn_download_extended_csv",
                    use_container_width=True,
                )

            # ══════════════════════════════════════════════════════════
            # STEP 5 — TESTRAIL
            # ══════════════════════════════════════════════════════════
            df_subir = st.session_state.get("df_editable")
            _tr_vacio = df_subir is None or df_subir.empty

            # ── Header TestRail ──
            st.markdown(
                '''<div class="tr-header" style="border-radius:12px;margin-bottom:16px">
                  <div class="tr-header-title">⑤ Publicar en TestRail</div>
                  <div class="tr-header-sub">Selecciona dónde publicar los casos generados</div>
                </div>''',
                unsafe_allow_html=True,
            )

            if _tr_vacio:
                st.info("ℹ️ Aplica los escenarios seleccionados (paso ④) para habilitar la subida.")
            else:
                n_subir = len(df_subir)
                st.markdown(
                    f'<div class="tr-summary">'
                    f'<span style="font-size:22px">📋</span>'
                    f'<span><strong>{n_subir}</strong> caso{"s" if n_subir != 1 else ""} listo{"s" if n_subir != 1 else ""} para publicar</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                if not st.session_state.get("t1_show_testrail"):
                    st.markdown('<div class="tr-connect-wrap">', unsafe_allow_html=True)
                    if st.button("🔌 Conectar con TestRail", key="btn_open_tr"):
                        st.session_state["t1_show_testrail"] = True
                        st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)
                else:
                    with st.spinner("Conectando a TestRail…"):
                        proy_raw = obtener_proyectos()

                    if not (isinstance(proy_raw, dict) and "projects" in proy_raw):
                        st.error("❌ Error al conectar con TestRail.")
                    else:
                        proyectos = proy_raw["projects"]
                        tr1, tr2, tr3 = st.columns(3)

                        with tr1:
                            sel_p = st.selectbox("Proyecto", [p["name"] for p in proyectos], key="t1_tr_proy")
                            id_p  = next((p["id"] for p in proyectos if p["name"] == sel_p), None)

                        suites = []
                        if id_p:
                            sr = obtener_suites(id_p)
                            suites = sr["suites"] if isinstance(sr,dict) and "suites" in sr else (sr if isinstance(sr,list) else [])

                        with tr2:
                            if suites:
                                sel_s = st.selectbox("Suite", [s["name"] for s in suites], key="t1_tr_suite")
                                id_s  = next((s["id"] for s in suites if s["name"] == sel_s), None)
                            else:
                                st.info("Sin suites disponibles.")
                                sel_s = ""; id_s = None

                        secs = []
                        if id_p and id_s:
                            secr = obtener_secciones(id_p, id_s)
                            secs = secr["sections"] if isinstance(secr,dict) and "sections" in secr else (secr if isinstance(secr,list) else [])

                        with tr3:
                            if secs:
                                sel_sec = st.selectbox("Sección", [s["name"] for s in secs], key="t1_tr_sec")
                                id_sec  = next((s["id"] for s in secs if s["name"] == sel_sec), None)
                            else:
                                st.info("Sin secciones disponibles.")
                                sel_sec = ""; id_sec = None

                        if id_sec:
                            st.markdown('<hr class="tr-divider">', unsafe_allow_html=True)
                            st.markdown(
                                f'<div class="tr-summary" style="background:#f0fdf4;border-color:#bbf7d0">'
                                f'<span style="font-size:18px">📤</span>'
                                f'<span><strong style="color:#059669">{n_subir}</strong> casos &nbsp;→&nbsp;'
                                f'<span class="tr-badge" style="background:#d1fae5;color:#065f46">{sel_p}</span>'
                                f'<span class="tr-badge" style="background:#d1fae5;color:#065f46">{sel_s}</span>'
                                f'<span class="tr-badge" style="background:#d1fae5;color:#065f46">{sel_sec}</span>'
                                f'</span></div>',
                                unsafe_allow_html=True,
                            )
                            st.markdown('<div class="tr-upload-wrap">', unsafe_allow_html=True)
                            if st.button("✅ Subir casos a TestRail", key="t1_btn_subir", use_container_width=True):
                                st.session_state["t1_confirm"] = {
                                    "proyecto":sel_p, "suite":sel_s, "seccion":sel_sec,
                                    "section_id":id_sec, "total":n_subir,
                                }
                                st.rerun()
                            st.markdown('</div>', unsafe_allow_html=True)

                            ctx = st.session_state.get("t1_confirm")
                            if ctx:
                                st.warning(f"⚠️ ¿Confirmas subir **{ctx['total']}** casos a **{ctx['seccion']}**?")
                                cb1, cb2 = st.columns(2)
                                with cb1:
                                    if st.button("✅ Confirmar subida", key="t1_btn_confirm"):
                                        ctx_data = st.session_state.pop("t1_confirm", None)
                                        if ctx_data:
                                            with st.spinner("📡 Subiendo casos…"):
                                                res = enviar_a_testrail(ctx_data["section_id"], build_testrail_export_dataframe(df_subir))
                                            if res["exito"]:
                                                st.session_state["step_actual"] = 5
                                                st.session_state["t1_subido_ok"] = True
                                                st.session_state["t1_show_testrail"] = False
                                                st.success("✅ Casos subidos correctamente a TestRail")
                                                st.rerun()
                                            else:
                                                st.error(f"❌ {res['subidos']} de {res['total']} subidos.")
                                                if res["detalle"]:
                                                    with st.expander("Ver detalles del error"):
                                                        for e in res["detalle"]: st.write(e)
                                with cb2:
                                    if st.button("❌ Cancelar", key="t1_btn_cancel"):
                                        st.session_state.pop("t1_confirm", None)
                                        st.rerun()


    # ─────────────────────────── LIMPIAR ──────────────────────────────
    st.markdown('<br>', unsafe_allow_html=True)
    if st.button("🧹 Limpiar todo", key="btn_limpiar_tab1"):
        st.session_state["tab1_do_reset"]    = True
        st.session_state["tab1_input_mode"]  = None
        st.session_state["t1_show_testrail"] = False
        st.session_state["t1_subido_ok"]     = False
        st.rerun()



# --------------------------- HISTORIAL ---------------------------
with tab2:
    if "historial_generaciones" not in st.session_state:
        st.session_state["historial_generaciones"] = cargar_historial()

    historial = st.session_state["historial_generaciones"]

    _col_hdr, _col_del = st.columns([7, 2])
    with _col_hdr:
        st.markdown("### 📚 Historial de generaciones")
    with _col_del:
        if st.button("🗑️ Borrar historial", key="btn_borrar_historial"):
            st.session_state["historial_generaciones"] = []
            guardar_historial([])
            st.success("✅ Historial borrado.")
            st.rerun()

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
