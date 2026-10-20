"""Login / sign-up page and session helpers."""
import hmac
import time

import streamlit as st

from db import create_user, secret, verify_user

MAX_FAILURES, LOCKOUT_SECONDS = 5, 15 * 60


@st.cache_resource
def _failures() -> dict[str, list[float]]:
    """Recent failed login timestamps per username, shared across sessions."""
    return {}


def _locked(username: str) -> bool:
    recent = [t for t in _failures().get(username, []) if time.time() - t < LOCKOUT_SECONDS]
    _failures()[username] = recent
    return len(recent) >= MAX_FAILURES


def current_user() -> dict | None:
    return st.session_state.get("user")


def logout() -> None:
    for k in list(st.session_state):
        del st.session_state[k]
    st.rerun()


def login_page() -> None:
    st.title("📈 NSE Investor Dashboard")
    st.caption("Sign in to see your saved portfolios. Educational tool, not investment advice.")
    tab_in, tab_up = st.tabs(["Log in", "Create account"])

    with tab_in, st.form("login"):
        username = st.text_input("Username").strip().lower()
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Log in", type="primary"):
            if _locked(username):
                st.error("Too many failed attempts. Try again in 15 minutes.")
            elif user := verify_user(username, password):
                _failures().pop(username, None)
                st.session_state["user"] = user
                st.rerun()
            else:
                _failures().setdefault(username, []).append(time.time())
                st.error("Wrong username or password.")

    invite = secret("SIGNUP_CODE")
    with tab_up, st.form("signup"):
        new_user = st.text_input("Choose a username", help="3–30 characters: letters, numbers, . - _")
        pw1 = st.text_input("Password (8+ characters)", type="password")
        pw2 = st.text_input("Confirm password", type="password")
        code = st.text_input("Invite code", type="password", help="Ask the dashboard owner") if invite else None
        if st.form_submit_button("Create account", type="primary"):
            if invite and not hmac.compare_digest(code or "", invite):
                st.error("Invalid invite code.")
            elif pw1 != pw2:
                st.error("Passwords don't match.")
            elif err := create_user(new_user, pw1):
                st.error(err)
            else:
                st.session_state["user"] = verify_user(new_user, pw1)
                st.rerun()
