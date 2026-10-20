"""Entry point.  Run:  streamlit run home.py"""
import streamlit as st

from auth import current_user, login_page, logout

st.set_page_config(page_title="NSE Investor Dashboard", page_icon="📈", layout="wide")

user = current_user()
if not user:
    st.navigation([st.Page(login_page, title="Log in", icon="🔐")]).run()
else:
    with st.sidebar:
        st.markdown(f"👤 Signed in as **{user['username']}**")
        if st.button("Log out"):
            logout()
    st.navigation([
        st.Page("long_term.py", title="Long-term investing", icon="🏦", default=True),
        st.Page("app.py", title="Swing trading screener", icon="📈"),
        st.Page("intraday.py", title="Intraday trading", icon="⚡"),
    ]).run()
