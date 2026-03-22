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
        self._logout_if_requested()

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
            self._render_logout_link()
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
[data-testid="stAppViewContainer"] {{ background: #f8fafc !important; }}
[data-testid="stHeader"]           {{ background: transparent !important; }}

.block-container {{
    max-width: {self.login_page_width}px;
    margin: 10vh auto 0 auto;
    padding: 3rem 3rem 2.5rem 3rem !important;
    background: #ffffff;
    border-radius: 16px;
    box-shadow: 0 4px 24px rgba(0,0,0,.08), 0 1px 4px rgba(0,0,0,.04);
    border: 1px solid #e5e7eb;
}}

[data-testid="stTextInput"] [data-baseweb="input"] {{
    background: #ffffff !important; border: 1.5px solid #e5e7eb !important;
    border-radius: 8px !important; box-shadow: 0 1px 3px rgba(0,0,0,.04) !important;
    transition: border-color .18s, box-shadow .18s !important;
}}
[data-testid="stTextInput"] [data-baseweb="input"]:focus-within {{
    border-color: #ef4444 !important; box-shadow: 0 0 0 3px rgba(239,68,68,.1) !important;
}}
[data-testid="stTextInput"] input {{
    font-size: 14px !important; color: #1e293b !important;
    background: transparent !important;
}}
[data-testid="stTextInput"] label {{
    font-weight: 600 !important; font-size: 13px !important; color: #374151 !important;
}}
[data-testid="InputInstructions"] {{ display: none !important; }}

[data-testid="stFormSubmitButton"] button {{
    width: 100% !important; background: #ef4444 !important;
    color: #ffffff !important; border: none !important;
    border-radius: 10px !important; padding: 14px 24px !important;
    font-size: 15px !important; font-weight: 700 !important;
    letter-spacing: .2px !important;
    box-shadow: 0 4px 14px rgba(239,68,68,.35) !important;
    margin-top: 8px !important; transition: all .2s !important; cursor: pointer !important;
}}
[data-testid="stFormSubmitButton"] button:hover {{
    background: #dc2626 !important;
    box-shadow: 0 6px 20px rgba(239,68,68,.45) !important;
    transform: translateY(-1px) !important;
}}

[data-testid="stSidebar"] {{ display: none !important; }}
[data-testid="stToolbar"]  {{ right: .5rem; }}
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

  .logout-fixed {{
    position: fixed; top: {self.logout_top}px; right: {self.logout_right}px;
    z-index: 9999; background: #fff; color: #0f1116; text-decoration: none;
    border: 1px solid #e5e7eb; border-radius: .5rem; padding: .35rem .7rem;
    font-size: .92rem; box-shadow: 0 2px 8px rgba(0,0,0,.05);
  }}
  .logout-fixed:hover {{ background: #f8f9fb; border-color: #d1d5db; }}
</style>""",
            unsafe_allow_html=True,
        )

    def _render_login_ui(self) -> None:
        st.markdown(
            """
            <div style="text-align:center;margin-bottom:28px">
                <div style="font-size:36px;margin-bottom:10px">🔒</div>
                <div style="font-size:22px;font-weight:800;color:#0f172a;letter-spacing:-.3px">
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

    def _logout_if_requested(self) -> None:
        qp = st.query_params
        v  = qp.get("logout")
        if v in (["1"], "1", 1, True):
            self._delete_session()
            for k in ("logged_in", "user", "display_name"):
                st.session_state.pop(k, None)
            qp.clear()
            st.rerun()

    def _render_logout_link(self) -> None:
        # Incluir el SID en la URL de logout para que _delete_session() lo encuentre
        sid         = st.query_params.get(_QP_KEY, "")
        logout_href = f"?logout=1&{_QP_KEY}={sid}" if sid else "?logout=1"
        st.markdown(
            f'<a class="logout-fixed" href="{logout_href}">Cerrar sesión</a>',
            unsafe_allow_html=True,
        )
