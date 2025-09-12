# auth_ui.py
import streamlit as st
import yaml
from yaml.loader import SafeLoader
import bcrypt
from typing import Optional, Dict, Any

class SecureShell:
    """
    Maneja login con dos anchos independientes:
      - login_page_width: ancho (px) de .block-container en la pantalla de login
      - app_page_width  : ancho (px) de .block-container cuando ya hay sesión
    El botón "Cerrar sesión" queda fijo arriba a la derecha.
    """
    def __init__(
        self,
        auth_yaml: str = ".streamlit/auth.yaml",
        *,
        login_page_width: int = 560,  # <-- ancho solo para la pantalla de login
        app_page_width: int = 1600,   # <-- ancho del contenido de la app
        logout_top: int = 12,
        logout_right: int = 96,
    ):
        self.auth_yaml = auth_yaml
        self.login_page_width = login_page_width
        self.app_page_width = app_page_width
        self.logout_top = logout_top
        self.logout_right = logout_right

        self._users = self._load_users()
        self.user: Optional[str] = None
        self.display_name: Optional[str] = None

    # ----------------- público -----------------
    def login(self) -> bool:
        """Aplica estilos según estado y renderiza login si hace falta."""
        self._logout_if_requested()

        st.session_state.setdefault("logged_in", False)
        st.session_state.setdefault("user", None)
        st.session_state.setdefault("display_name", None)

        if st.session_state["logged_in"]:
            # ====== Usuario AUTENTICADO → estilos de APP ======
            self._apply_styles_app()
            self.user = st.session_state["user"]
            self.display_name = st.session_state["display_name"]
            self._render_logout_link()
            return True

        # ====== Usuario NO autenticado → estilos de LOGIN ======
        self._apply_styles_login()
        self._render_login_ui()
        return False

    # ----------------- helpers internos -----------------
    def _load_users(self) -> Dict[str, Any]:
        with open(self.auth_yaml, "r", encoding="utf-8") as f:
            cfg = yaml.load(f, Loader=SafeLoader)
        return cfg["credentials"]["usernames"]

    def _apply_styles_login(self) -> None:
        """Limita el ancho de la página solo en la pantalla de login."""
        st.markdown(
            f"""
<style>
  .block-container {{
    max-width: {self.login_page_width}px;   /* ancho de PAGINA en LOGIN */
    margin: 6vh auto 0 auto;                /* centrado y bajito */
    padding: 1.2rem 1.6rem 2rem 1.6rem;
  }}
  [data-testid="stSidebar"]{{display:none !important;}}
  [data-testid="stToolbar"]{{right:.5rem;}}
</style>
            """,
            unsafe_allow_html=True,
        )

    def _apply_styles_app(self) -> None:
        """Ancho para el contenido de la app cuando hay sesión."""
        st.markdown(
            f"""
<style>
  .block-container {{
    max-width: {self.app_page_width}px;     /* ancho de PAGINA en APP */
    margin: 0 auto;
    padding: .6rem 2rem 2rem 2rem;
  }}
  [data-testid="stSidebar"]{{display:none !important;}}
  [data-testid="stToolbar"]{{right:.5rem;}}

  .logout-fixed {{
    position: fixed;
    top: {self.logout_top}px;
    right: {self.logout_right}px;
    z-index: 9999;
    background:#fff; color:#0f1116; text-decoration:none;
    border:1px solid #e5e7eb; border-radius:.5rem; padding:.35rem .7rem;
    font-size:.92rem; box-shadow:0 2px 8px rgba(0,0,0,.05);
  }}
  .logout-fixed:hover{{ background:#f8f9fb; border-color:#d1d5db; }}
</style>
            """,
            unsafe_allow_html=True,
        )

    def _render_login_ui(self) -> None:
        """Form con ENTER para enviar."""
        st.subheader("🔒 Acceso restringido")

        with st.form("login_form", clear_on_submit=False):
            u = st.text_input("Usuario", key="u")
            p = st.text_input("Contraseña", type="password", key="p")
            submitted = st.form_submit_button("Entrar")

        if submitted:
            ok = False
            if u in self._users:
                stored_hash = self._users[u]["password"]
                try:
                    ok = bcrypt.checkpw(p.encode("utf-8"), stored_hash.encode("utf-8"))
                except Exception:
                    ok = False
            if ok:
                st.session_state["logged_in"] = True
                st.session_state["user"] = u
                st.session_state["display_name"] = self._users[u].get("name", u)
                st.rerun()
            else:
                st.error("❌ Usuario o contraseña incorrectos")

    def _logout_if_requested(self) -> None:
        qp = st.query_params
        v = qp.get("logout")
        if v in (["1"], "1", 1, True):
            for k in ("logged_in", "user", "display_name"):
                st.session_state.pop(k, None)
            qp.clear()
            st.rerun()

    def _render_logout_link(self) -> None:
        st.markdown('<a class="logout-fixed" href="?logout=1">Cerrar sesión</a>',
                    unsafe_allow_html=True)
