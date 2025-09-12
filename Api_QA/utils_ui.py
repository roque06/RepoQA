import streamlit as st
from contextlib import contextmanager

import streamlit as st
from utils_ingest import consolidate_attachments
from utils_gemini import generar_escenarios_desde_contexto  # lo usaremos luego

# Estado base
if "attachments_text" not in st.session_state: st.session_state["attachments_text"] = ""
if "attachments_meta" not in st.session_state: st.session_state["attachments_meta"] = []
if "use_attachments" not in st.session_state: st.session_state["use_attachments"] = True
if "contexto_base" not in st.session_state: st.session_state["contexto_base"] = ""  # si ya tienes uno, omite esto


# --- utils_ui.py ---
import io, re
import streamlit as st

# PDF -> imágenes por página (requiere PyMuPDF: pip install pymupdf)
def _render_pdf_pages(file_bytes, dpi=140):
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
    # une líneas cortas, respeta párrafos y arma páginas de ~max_chars
    if not text:
        return [""]
    # normaliza saltos
    text = re.sub(r'\r\n?', '\n', text).strip()
    paras = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]
    pages, buf = [], ""
    for p in paras:
        # agrega párrafo + salto doble para lectura
        chunk = (("\n\n" if buf else "") + p)
        if len(buf) + len(chunk) <= max_chars:
            buf += chunk
        else:
            if buf:
                pages.append(buf)
            # si el párrafo es gigante, córtalo en trozos
            if len(chunk) > max_chars:
                for i in range(0, len(chunk), max_chars):
                    pages.append(chunk[i:i+max_chars])
                buf = ""
            else:
                buf = chunk
    if buf:
        pages.append(buf)
    return pages or [""]

def preview_document_paginado(
    file_name: str,
    file_bytes: bytes = None,
    text_extraido: str = None,
    tipo: str = None,  # "pdf" | "texto". Si no viene, se infiere por extensión
    key_ns: str = "preview"
):
    """
    Muestra un preview paginado del documento.
    - Si es PDF: renderiza páginas como imágenes.
    - Si es texto: pagina por caracteres.
    Usa st.session_state[f"{key_ns}:{file_name}:page"] para recordar la página.
    """
    # Inferencia de tipo
    if not tipo and file_name:
        lower = file_name.lower()
        if lower.endswith(".pdf"):
            tipo = "pdf"
        else:
            tipo = "texto"

    state_key = f"{key_ns}:{file_name}:page"

    # Construye páginas
    if tipo == "pdf":
        if not file_bytes:
            st.warning("No se recibieron bytes del PDF.")
            return
        pages = _render_pdf_pages(file_bytes)
        total = len(pages)
        if total == 0:
            st.warning("No se pudo renderizar el PDF.")
            return

        # Estado inicial
        if state_key not in st.session_state:
            st.session_state[state_key] = 1

        # Controles
        col_a, col_b, col_c, col_d, col_e = st.columns([1, 1.2, 2, 1.2, 1])
        with col_a:
            if st.button("⏮️", use_container_width=True, key=f"{state_key}-first"):
                st.session_state[state_key] = 1
        with col_b:
            if st.button("◀️", use_container_width=True, key=f"{state_key}-prev"):
                st.session_state[state_key] = max(1, st.session_state[state_key] - 1)
        with col_c:
            page = st.number_input(
                "Ir a página", min_value=1, max_value=total,
                value=st.session_state[state_key], step=1, label_visibility="collapsed",
                key=f"{state_key}-num"
            )
            st.session_state[state_key] = int(page)
        with col_d:
            if st.button("▶️", use_container_width=True, key=f"{state_key}-next"):
                st.session_state[state_key] = min(total, st.session_state[state_key] + 1)
        with col_e:
            if st.button("⏭️", use_container_width=True, key=f"{state_key}-last"):
                st.session_state[state_key] = total

        st.caption(f"Página {st.session_state[state_key]} de {total}")

        # Vista
        idx = st.session_state[state_key] - 1
        st.image(pages[idx], use_column_width=True)

    else:
        # TEXTO
        if not text_extraido:
            if file_bytes:
                # intenta decodificar como utf-8
                try:
                    text_extraido = file_bytes.decode("utf-8", errors="ignore")
                except Exception:
                    text_extraido = ""
            else:
                text_extraido = ""

        pages = _paginate_text(text_extraido, max_chars=3000)
        total = len(pages)
        if state_key not in st.session_state:
            st.session_state[state_key] = 1

        col_a, col_b, col_c, col_d, col_e = st.columns([1, 1.2, 2, 1.2, 1])
        with col_a:
            if st.button("⏮️", use_container_width=True, key=f"{state_key}-t-first"):
                st.session_state[state_key] = 1
        with col_b:
            if st.button("◀️", use_container_width=True, key=f"{state_key}-t-prev"):
                st.session_state[state_key] = max(1, st.session_state[state_key] - 1)
        with col_c:
            page = st.number_input(
                "Ir a página", min_value=1, max_value=total,
                value=st.session_state[state_key], step=1, label_visibility="collapsed",
                key=f"{state_key}-t-num"
            )
            st.session_state[state_key] = int(page)
        with col_d:
            if st.button("▶️", use_container_width=True, key=f"{state_key}-t-next"):
                st.session_state[state_key] = min(total, st.session_state[state_key] + 1)
        with col_e:
            if st.button("⏭️", use_container_width=True, key=f"{state_key}-t-last"):
                st.session_state[state_key] = total

        st.caption(f"Página {st.session_state[state_key]} de {total}")

        # Contenedor con bordes y scroll si la página es muy larga
        with st.container(border=True):
            st.markdown(pages[st.session_state[state_key] - 1])

        st.caption("Tip: ajusta 'max_chars' en _paginate_text si quieres páginas más largas o más cortas.")



# 🎛️ Título de sección
def titulo_seccion(texto, emoji="🔧"):
    st.markdown(f"### {emoji} {texto}")

# 📦 Botón con ícono
def boton_con_icono(label, emoji="🚀"):
    return st.button(f"{emoji} {label}")

# 📋 Tabs personalizados con emojis
def crear_tabs(titulos_emojis):
    return st.tabs([f"{emoji} {titulo}" for titulo, emoji in titulos_emojis])

# 📝 TextArea estilizado
def textarea_estilizada(titulo, contenido="", altura=250):
    st.text_area(titulo, value=contenido, height=altura)

# ⚠️ Alerta visual de advertencia
def alerta_advertencia(texto):
    st.warning(f"⚠️ {texto}")

# 🧠 Spinner con mensaje visual
class SpinnerAccion:
    def __init__(self, mensaje):
        self.mensaje = mensaje

    def __enter__(self):
        self.spinner = st.spinner(self.mensaje)
        self.spinner.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.spinner.__exit__(exc_type, exc_val, exc_tb)

def spinner_accion(mensaje):
    return SpinnerAccion(mensaje)
