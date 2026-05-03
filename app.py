import os

import requests
import streamlit as st
import streamlit.components.v1 as components


API_BASE_URL = os.getenv("TRADEMATIC_API_URL", "http://localhost:8000").rstrip("/")


st.set_page_config(
    page_title="Tradematic Member dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------- SESSION ----------------
if "page" not in st.session_state:
    st.session_state.page = "home"
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "access_token" not in st.session_state:
    st.session_state.access_token = None
if "user_data" not in st.session_state:
    st.session_state.user_data = None


def api_request(method, path, *, json=None, authenticated=True):
    headers = {}
    if authenticated:
        token = st.session_state.get("access_token")
        if not token:
            raise RuntimeError("Please log in again.")
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.request(
            method,
            f"{API_BASE_URL}{path}",
            json=json,
            headers=headers,
            timeout=25,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Backend is not reachable at {API_BASE_URL}: {exc}") from exc

    try:
        data = response.json()
    except ValueError:
        data = {"detail": response.text}

    if response.status_code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else None
        raise RuntimeError(detail or "Backend request failed")
    return data


def load_current_user():
    data = api_request("GET", "/api/dashboard/me")
    user = data["user"]
    st.session_state.user_data = user
    return user


def format_last_authorized(value):
    if not value:
        return "Never"
    try:
        from datetime import datetime

        parsed = datetime.fromisoformat(value)
        return parsed.astimezone().strftime("%d/%m/%Y %I:%M:%S %p")
    except ValueError:
        return value


def open_new_tab(url):
    components.html(
        f"""
        <script>
            window.open({url!r}, "_blank", "noopener,noreferrer");
        </script>
        """,
        height=0,
    )


# ---------------- GLOBAL STYLE ----------------
st.markdown("""
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

.block-container {
    padding-top: 1.2rem;
    padding-left: 2rem;
    padding-right: 2rem;
}

html, body, [class*="css"] {
    background: #000000 !important;
    color: #ffffff !important;
}

/* Inputs */
.stTextInput input,
.stNumberInput input,
.stSelectbox div[data-baseweb="select"] > div {
    background-color: #242424 !important;
    color: white !important;
    border-radius: 10px !important;
    border: 1px solid #333 !important;
}

/* Buttons */
.stButton > button {
    width: 100%;
    border-radius: 10px;
    border: 1px solid #3b3b3b;
    background: transparent;
    color: white;
}

/* Login */
.login-wrap {
    max-width: 680px;
    margin: 2rem auto 0 auto;
}

.login-title {
    font-size: 32px;
    line-height: 1.15;
    font-weight: 800;
    margin: 0 0 18px 0;
    color: #ffffff;
}

div[data-testid="stForm"] {
    border: 1px solid #323232;
    border-radius: 10px;
    padding: 18px 18px 20px 18px;
    background: #000000;
}

div[data-testid="stForm"] label {
    font-size: 16px !important;
    font-weight: 700 !important;
    color: #ffffff !important;
}

div[data-testid="stForm"] .stTextInput input {
    min-height: 50px;
    background-color: #232323 !important;
    border: 1px solid #232323 !important;
    border-radius: 9px !important;
}

div[data-testid="stForm"] .stFormSubmitButton > button {
    min-height: 50px;
    margin-top: 8px;
    border-radius: 9px;
    border: 1px solid #3b3b3b;
    background: #000000;
    color: #ffffff;
    font-size: 16px;
    font-weight: 700;
}

div[data-testid="stForm"] .stFormSubmitButton > button:hover {
    border-color: #00c853;
    color: #00c853;
    background: #050505;
}

.section-heading {
    text-align: center;
    font-size: 24px;
    font-weight: 800;
    margin: 0 0 18px 0;
    color: #ffffff;
}

.center-caption {
    text-align: center;
    color: rgba(255, 255, 255, 0.62);
    font-size: 14px;
    margin-top: 10px;
}
</style>
""", unsafe_allow_html=True)

# ---------------- SIDEBAR ----------------
with st.sidebar:

    st.markdown("## Tradematic")
    st.markdown("---")

    if st.button("Home", use_container_width=True):
        st.session_state.page = "home"

    if st.button("Member Dashboard", use_container_width=True):
        if st.session_state.authenticated:
            st.session_state.page = "dashboard"
        else:
            st.session_state.page = "login"

    if st.button("Integration Tutorial", use_container_width=True):
        st.session_state.page = "tutorial"

    if st.button("Help", use_container_width=True):
        st.session_state.page = "help"

# ---------------- LOGIN ----------------
def render_login():
    left, center, right = st.columns([1, 1.65, 1])

    with center:
        st.markdown('<div class="login-wrap">', unsafe_allow_html=True)
        st.markdown('<h1 class="login-title">Member Login</h1>', unsafe_allow_html=True)

        with st.form("member_login", clear_on_submit=False):
            username = st.text_input("Email", placeholder="")
            password = st.text_input("Password", type="password", placeholder="")
            submitted = st.form_submit_button("Login")

            if submitted:
                try:
                    data = api_request(
                        "POST",
                        "/api/auth/login",
                        json={"email": username, "password": password},
                        authenticated=False,
                    )
                    st.session_state.access_token = data["access_token"]
                    st.session_state.user_data = data["user"]
                    st.session_state.authenticated = True
                    st.session_state.page = "dashboard"
                    st.rerun()
                except RuntimeError as exc:
                    st.error(str(exc))

        st.markdown("</div>", unsafe_allow_html=True)

if st.session_state.page == "login" and not st.session_state.authenticated:
    render_login()
    st.stop()

if st.session_state.page == "dashboard" and st.session_state.authenticated:
    try:
        user_data = load_current_user()
    except RuntimeError as exc:
        st.session_state.authenticated = False
        st.session_state.access_token = None
        st.session_state.user_data = None
        st.error(str(exc))
        render_login()
        st.stop()
else:
    user_data = st.session_state.get("user_data") or {}

# ---------------- TITLE ----------------
if st.session_state.page == "dashboard":
    st.title("Tradematic")
    st.subheader("Member Dashboard")

# ================= HOME =================
if st.session_state.page == "home":
    st.title("Tradematic")
    st.write("Select Member Dashboard from the sidebar to continue.")

# ================= DASHBOARD =================
elif st.session_state.page == "dashboard":

    tab1, tab2 = st.tabs(["Account", "Capital & Integration"])

    # -------- ACCOUNT --------
    with tab1:
        st.markdown('<div class="section-heading">Account</div>', unsafe_allow_html=True)
        _, account_col, _ = st.columns([0.29, 0.42, 0.29])
        with account_col:
            with st.container(border=True):
                st.text_input(
                    "Name",
                    value=user_data.get("full_name", ""),
                    disabled=True
                )
                st.text_input(
                    "Subscription Days",
                    value=str(user_data.get("subscription_days", "")),
                    disabled=True
                )

    # -------- CAPITAL --------
    with tab2:

        st.markdown('<div class="section-heading">Capital Allocation</div>', unsafe_allow_html=True)
        _, capital_col, _ = st.columns([0.21, 0.58, 0.21])
        with capital_col:
            with st.container(border=True):

                capital = st.number_input(
                    "Capital (INR)",
                    value=float(user_data.get("capital") or 60000),
                )

                index_options = ["None", "Nifty", "Sensex"]
                current_index = user_data.get("index_name") or "None"
                index_value = st.selectbox(
                    "Index",
                    index_options,
                    index=index_options.index(current_index) if current_index in index_options else 0,
                )

                risk_options = ["Low", "Medium", "High"]
                current_risk = user_data.get("risk_mode") or "Medium"
                risk_mode = st.selectbox(
                    "Risk mode",
                    risk_options,
                    index=risk_options.index(current_risk) if current_risk in risk_options else 1,
                )

                if st.button("Save & Refresh", key="save_capital"):
                    try:
                        data = api_request(
                            "PUT",
                            "/api/dashboard/capital",
                            json={
                                "capital": capital,
                                "index_name": index_value,
                                "risk_mode": risk_mode,
                            },
                        )
                        st.session_state.user_data = data["data"]["user"]
                        st.success("Saved successfully")
                        st.rerun()
                    except RuntimeError as exc:
                        st.error(str(exc))

        # -------- BROKER --------
        st.markdown('<div class="section-heading">Broker Integration</div>', unsafe_allow_html=True)
        _, broker_col, _ = st.columns([0.21, 0.58, 0.21])
        with broker_col:
            with st.container(border=True):

                broker_app_id = st.text_input(
                    "App ID",
                    value=user_data.get("broker_app_id") or "KN4D1XKL15-200",
                )

                broker_secret_key = st.text_input(
                    "Secret Key",
                    type="password",
                    placeholder="Saved" if user_data.get("broker_secret_saved") else "",
                )

                broker_auth_code = st.text_input(
                    "Auth Code / Redirect URL",
                    placeholder="Paste FYERS auth_code or final redirect URL if it is not captured automatically",
                )

                if st.button("Authorize Broker", key="auth"):
                    try:
                        data = api_request(
                            "POST",
                            "/api/broker/start",
                            json={
                                "broker_app_id": broker_app_id,
                                "broker_client_id": broker_app_id,
                                "broker_secret_key": broker_secret_key or None,
                                "broker_auth_code": broker_auth_code or None,
                            },
                        )
                        st.session_state.user_data = data["data"]["user"]
                        open_new_tab(data["data"]["auth_url"])
                        st.success("Authorization started")
                    except RuntimeError as exc:
                        st.error(str(exc))

        st.divider()

        _, save_col, _ = st.columns([0.31, 0.38, 0.31])
        with save_col:
            if st.button("Save Broker Credentials", key="save", use_container_width=True):
                try:
                    data = api_request(
                        "POST",
                        "/api/broker/confirm",
                        json={
                            "broker_app_id": broker_app_id,
                            "broker_client_id": broker_app_id,
                            "broker_secret_key": broker_secret_key or None,
                        },
                    )
                    st.session_state.user_data = data["data"]["user"]
                    st.info("Credentials saved")
                    st.rerun()
                except RuntimeError as exc:
                    st.error(str(exc))

            st.markdown(
                f'<div class="center-caption">Last Authorized: {format_last_authorized(user_data.get("last_authorized_at"))}</div>',
                unsafe_allow_html=True
            )

# ================= OTHER PAGES =================
elif st.session_state.page == "tutorial":
    st.title("Integration Tutorial")
    st.write("Yaha tutorial aayega")

elif st.session_state.page == "help":
    st.title("Help")
    st.write("Help content yaha aayega")
