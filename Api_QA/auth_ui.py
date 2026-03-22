# auth_ui.py
import streamlit as st
import yaml
from yaml.loader import SafeLoader
import bcrypt
import uuid
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

# ──────────────────────────────────────────────────────────────────────────────
# Persistencia de sesión: archivo local + session ID en query param
#
#  • sessions.json  guarda  { sid: { user, name, expires } }
#  • La URL queda   ?sid=<uuid>  → sobrevive a F5 porque el navegador la mantiene
#  • Sin dependencias externas de cookies
# ──────────────────────────────────────────────────────────────────────────────

_SESSIONS_FILE = "sessions.json"
_SESSION_DAYS  = 7
_QP_KEY        = "sid"


def _load_sessions() -> dict:
    if not os.path.exists(_SESSIONS_FILE):
        return {}
    try:
        with open(_SESSIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_sessions(sessions: dict) -> None:
    try:
        with open(_SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _purge_expired(sessions: dict) -> dict:
    now = datetime.now().isoformat()
    return {k: v for k, v in sessions.items() if v.get("expires", "") > now}


# ──────────────────────────────────────────────────────────────────────────────

class SecureShell:
    """
    Maneja login con dos anchos independientes:
      - login_page_width: ancho (px) de .block-container en la pantalla de login
      - app_page_width  : ancho (px) de .block-container cuando ya hay sesión
    El botón "Cerrar sesión" queda fijo arriba a la derecha.

    Persistencia de sesión: session ID (UUID) en query param ?sid=...
    Los datos de sesión viven en sessions.json (servidor). La URL sobrevive a F5.
    """

    def __init__(
        self,
        auth_yaml: str = ".streamlit/auth.yaml",
        *,
        login_page_width: int = 560,
        app_page_width:   int = 1600,
        logout_top:       int = 12,
        logout_right:     int = 96,
    ):
        self.auth_yaml        = auth_yaml
        self.login_page_width = login_page_width
        self.app_page_width   = app_page_width
        self.logout_top       = logout_top
        self.logout_right     = logout_right

        self._users: Dict[str, Any]  = self._load_users()
        self.user:         Optional[str] = None
        self.display_name: Optional[str] = None

    # ─────────────────────────── público ─────────────────────────────────────

    def login(self) -> bool:
        """Aplica estilos según estado y renderiza login si hace falta."""
        st.session_state.setdefault("logged_in",    False)
        st.session_state.setdefault("user",         None)
        st.session_state.setdefault("display_name", None)

        # Si session_state no tiene sesión activa, intentar restaurar desde URL
        if not st.session_state["logged_in"]:
            self._restore_from_qp()

        if st.session_state["logged_in"]:
            self._apply_styles_app()
            self.user         = st.session_state["user"]
            self.display_name = st.session_state["display_name"]
            return True

        self._apply_styles_login()
        self._render_login_ui()
        return False

    # ─────────────────────────── session helpers ──────────────────────────────

    def _restore_from_qp(self) -> None:
        """Lee el SID de la URL, lo valida en sessions.json y restaura session_state."""
        sid = st.query_params.get(_QP_KEY)
        if not sid:
            return

        sessions = _purge_expired(_load_sessions())
        session  = sessions.get(sid)

        if not session:
            # SID inexistente o expirado → limpiar URL
            st.query_params.pop(_QP_KEY, None)
            return

        username = session.get("user", "")
        if username and username in self._users:
            st.session_state["logged_in"]    = True
            st.session_state["user"]         = username
            st.session_state["display_name"] = session.get("name", username)
            # Guardar sessions sin las expiradas (limpieza pasiva)
            _save_sessions(sessions)
        else:
            # Usuario eliminado del sistema → borrar sesión huérfana
            sessions.pop(sid, None)
            _save_sessions(sessions)
            st.query_params.pop(_QP_KEY, None)

    def _create_session(self, username: str, display_name: str) -> None:
        """Crea una sesión nueva, la persiste en sessions.json y pone el SID en la URL."""
        sid      = str(uuid.uuid4())
        sessions = _purge_expired(_load_sessions())
        sessions[sid] = {
            "user":    username,
            "name":    display_name,
            "expires": (datetime.now() + timedelta(days=_SESSION_DAYS)).isoformat(),
        }
        _save_sessions(sessions)
        st.query_params[_QP_KEY] = sid

    def _delete_session(self) -> None:
        """Elimina la sesión de sessions.json y la borra de la URL."""
        sid = st.query_params.get(_QP_KEY)
        if sid:
            sessions = _load_sessions()
            sessions.pop(sid, None)
            _save_sessions(sessions)
        # No limpiamos query_params aquí; lo hace _logout_if_requested con qp.clear()

    # ─────────────────────────── helpers internos ────────────────────────────

    def _load_users(self) -> Dict[str, Any]:
        with open(self.auth_yaml, "r", encoding="utf-8") as f:
            cfg = yaml.load(f, Loader=SafeLoader)
        return cfg["credentials"]["usernames"]

    def _apply_styles_login(self) -> None:
        st.markdown(
            f"""
<style>
/* ── Fondo y header Streamlit ──────────────────────── */
[data-testid="stAppViewContainer"] {{ background: #f8fafc !important; }}
[data-testid="stHeader"]           {{ background: transparent !important; }}
[data-testid="stSidebar"]          {{ display: none !important; }}
[data-testid="stToolbar"]          {{ right: .5rem; }}

/* ── Card central ──────────────────────────────────── */
.block-container {{
    max-width: {self.login_page_width}px;
    margin: 10vh auto 0 auto;
    padding: 3rem 3rem 2.5rem 3rem !important;
    background: #ffffff;
    border-radius: 16px;
    box-shadow: 0 4px 24px rgba(0,0,0,.08), 0 1px 4px rgba(0,0,0,.04);
    border: 1px solid #e5e7eb;
}}

/* ── Inputs ────────────────────────────────────────── */
[data-testid="stTextInput"] input {{
    background:    #ffffff !important;
    border:        1.5px solid #e5e7eb !important;
    border-radius: 8px !important;
    font-size:     14px !important;
    color:         #1e293b !important;
    padding:       10px 12px !important;
    box-shadow:    0 1px 3px rgba(0,0,0,.04) !important;
    transition:    border-color .18s, box-shadow .18s !important;
}}
[data-testid="stTextInput"] input:focus {{
    border-color: #ef4444 !important;
    box-shadow:   0 0 0 3px rgba(239,68,68,.1) !important;
    outline:      none !important;
}}
[data-testid="stTextInput"] label {{
    font-weight: 600 !important;
    font-size:   13px !important;
    color:       #374151 !important;
}}
[data-testid="InputInstructions"] {{ display: none !important; }}

/* ── Botón Ingresar — via clase ancla, sin data-testid ─ */
.login-btn-anchor ~ div button {{
    width:          100% !important;
    background:     #ef4444 !important;
    color:          #ffffff !important;
    border:         none !important;
    border-radius:  10px !important;
    padding:        14px 24px !important;
    font-size:      15px !important;
    font-weight:    700 !important;
    letter-spacing: .2px !important;
    box-shadow:     0 4px 14px rgba(239,68,68,.35) !important;
    margin-top:     8px !important;
    transition:     all .2s !important;
    cursor:         pointer !important;
}}
.login-btn-anchor ~ div button:hover {{
    background:  #dc2626 !important;
    box-shadow:  0 6px 20px rgba(239,68,68,.45) !important;
    transform:   translateY(-1px) !important;
}}
</style>""",
            unsafe_allow_html=True,
        )

    def _apply_styles_app(self) -> None:
        st.markdown(
            f"""
<style>
  .block-container {{
    max-width: {self.app_page_width}px; margin: 0 auto;
    padding: .6rem 2rem 2rem 2rem;
  }}
  [data-testid="stSidebar"] {{ display: none !important; }}
  [data-testid="stToolbar"]  {{ right: .5rem; }}

  /* ── App header ─────────────────────────────────── */
  .app-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: .5rem 0 .75rem 0;
    margin-bottom: .25rem;
    border-bottom: 1px solid #f1f5f9;
  }}
  .app-header-title {{
    font-size: 1.55rem;
    font-weight: 800;
    color: #0f172a;
    letter-spacing: -.3px;
    margin: 0;
    line-height: 1.2;
  }}

  /* ── Botón Cerrar sesión ─────────────────────────── */
  .logout-btn-anchor ~ [data-testid="stButton"] button {{
    background:    #ffffff !important;
    color:         #374151 !important;
    border:        1px solid #e5e7eb !important;
    border-radius: 8px !important;
    padding:       6px 14px !important;
    font-size:     14px !important;
    font-weight:   500 !important;
    cursor:        pointer !important;
    box-shadow:    none !important;
    line-height:   1.5 !important;
    min-height:    unset !important;
    width:         auto !important;
    transition:    background .15s, border-color .15s !important;
  }}
  .logout-btn-anchor ~ [data-testid="stButton"] button:hover {{
    background:   #f3f4f6 !important;
    border-color: #d1d5db !important;
  }}

  /* Alinear verticalmente la columna del botón con el título */
  [data-testid="stHorizontalBlock"]:has(.app-header-title) [data-testid="stColumn"]:last-child {{
    display: flex;
    align-items: center;
    justify-content: flex-end;
  }}
</style>""",
            unsafe_allow_html=True,
        )

    def _render_login_ui(self) -> None:
        st.markdown(
            """
            <div style="text-align:center;margin-bottom:28px">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="#f59e0b"
                   xmlns="http://www.w3.org/2000/svg" style="margin-bottom:10px">
                <path d="M12 2a5 5 0 00-5 5v3H6a2 2 0 00-2 2v8a2 2 0 002 2h12
                         a2 2 0 002-2v-8a2 2 0 00-2-2h-1V7a5 5 0 00-5-5zm-3
                         8V7a3 3 0 016 0v3H9z"/>
              </svg>
              <div style="font-size:22px;font-weight:800;color:#0f172a;
                          letter-spacing:-.3px;margin-top:4px">
                Acceso al sistema
              </div>
              <div style="font-size:13.5px;color:#6b7280;margin-top:6px">
                Ingresa tus credenciales para continuar
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form("login_form", clear_on_submit=False):
            u = st.text_input("Usuario",    key="u")
            p = st.text_input("Contraseña", type="password", key="p")
            st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)
            # Ancla para apuntar el CSS al botón submit sin usar data-testid
            st.markdown('<span class="login-btn-anchor"></span>', unsafe_allow_html=True)
            submitted = st.form_submit_button("Ingresar")

        if submitted:
            ok = False
            if u in self._users:
                stored_hash = self._users[u]["password"]
                try:
                    ok = bcrypt.checkpw(p.encode("utf-8"), stored_hash.encode("utf-8"))
                except Exception:
                    ok = False
            if ok:
                st.session_state["logged_in"]    = True
                st.session_state["user"]         = u
                st.session_state["display_name"] = self._users[u].get("name", u)
                self._create_session(u, self._users[u].get("name", u))
                st.rerun()
            else:
                st.error("❌ Usuario o contraseña incorrectos")

    def render_header(self, title: str) -> None:
        """Header principal: título a la izquierda, botón Cerrar sesión a la derecha."""
        _col_t, _col_btn = st.columns([8, 2])
        with _col_t:
            st.markdown(
                f'<p class="app-header-title">{title}</p>',
                unsafe_allow_html=True,
            )
        with _col_btn:
            st.markdown('<span class="logout-btn-anchor"></span>', unsafe_allow_html=True)
            if st.button("Cerrar sesión", key="_logout_btn"):
                self._delete_session()
                for k in ("logged_in", "user", "display_name"):
                    st.session_state.pop(k, None)
                try:
                    st.query_params.clear()
                except Exception:
                    pass
                st.rerun()
