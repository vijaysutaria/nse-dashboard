"""User accounts and saved holdings.

Uses DATABASE_URL from .streamlit/secrets.toml or the environment (hosted Postgres in the cloud),
falling back to a local SQLite file in ./data for running on this Mac.
"""
import os
import re
from datetime import datetime

import bcrypt
import pandas as pd
import sqlalchemy as sa
import streamlit as st

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,30}$")

meta = sa.MetaData()
users = sa.Table(
    "users", meta,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("username", sa.String(30), unique=True, nullable=False),
    sa.Column("pw_hash", sa.String(100), nullable=False),
    sa.Column("created_at", sa.DateTime, nullable=False),
)
holdings = sa.Table(
    "holdings", meta,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False),
    sa.Column("kind", sa.String(10), nullable=False),  # "long" or "swing"
    sa.Column("symbol", sa.String(30), nullable=False),
    sa.Column("buy_price", sa.Float, nullable=False),
    sa.Column("qty", sa.Float, nullable=False),
    sa.Column("buy_date", sa.Date),
)


def secret(name: str) -> str | None:
    try:
        value = st.secrets.get(name)
    except Exception:  # no secrets.toml
        value = None
    return value or os.environ.get(name)


def _url() -> str:
    url = secret("DATABASE_URL")
    if not url:
        os.makedirs(DATA_DIR, exist_ok=True)
        return f"sqlite:///{DATA_DIR}/app.db"
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@st.cache_resource
def engine() -> sa.Engine:
    eng = sa.create_engine(_url(), pool_pre_ping=True)
    meta.create_all(eng)
    return eng


# ---------------------------------------------------------------- accounts
def create_user(username: str, password: str) -> str | None:
    """Returns an error message, or None on success."""
    username = username.strip().lower()
    if not USERNAME_RE.match(username):
        return "Username must be 3–30 characters: letters, numbers, dot, dash or underscore."
    if not 8 <= len(password.encode()) <= 72:
        return "Password must be 8–72 characters."
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    try:
        with engine().begin() as c:
            c.execute(users.insert().values(username=username, pw_hash=pw_hash, created_at=datetime.utcnow()))
    except sa.exc.IntegrityError:
        return "That username is taken."
    return None


def verify_user(username: str, password: str) -> dict | None:
    with engine().connect() as c:
        row = c.execute(sa.select(users).where(users.c.username == username.strip().lower())).first()
    if row and bcrypt.checkpw(password.encode()[:72], row.pw_hash.encode()):
        return {"id": row.id, "username": row.username}
    return None


# ---------------------------------------------------------------- holdings
def load_holdings(user_id: int, kind: str) -> pd.DataFrame:
    with engine().connect() as c:
        rows = c.execute(sa.select(holdings).where(holdings.c.user_id == user_id, holdings.c.kind == kind)
                         .order_by(holdings.c.id)).all()
    return pd.DataFrame({
        "Symbol": pd.Series([r.symbol for r in rows], dtype="object"),
        "Buy price": pd.Series([r.buy_price for r in rows], dtype="float"),
        "Qty": pd.Series([r.qty for r in rows], dtype="float"),
        "Buy date": pd.to_datetime(pd.Series([r.buy_date for r in rows], dtype="object")),
    })


def save_holdings(user_id: int, kind: str, df: pd.DataFrame) -> None:
    records = []
    for _, r in df.iterrows():
        bd = r.get("Buy date")
        records.append(dict(user_id=user_id, kind=kind, symbol=str(r.Symbol).strip().upper(),
                            buy_price=float(r["Buy price"]), qty=float(r.Qty),
                            buy_date=None if bd is None or pd.isna(bd) else pd.Timestamp(bd).date()))
    with engine().begin() as c:
        c.execute(holdings.delete().where(holdings.c.user_id == user_id, holdings.c.kind == kind))
        if records:
            c.execute(holdings.insert(), records)


def holdings_editor(kind: str, with_date: bool) -> pd.DataFrame:
    """Editable holdings table for the signed-in user, saved to the database with a Save button."""
    user = st.session_state["user"]
    base_key, ver_key = f"_base_{kind}", f"_ver_{kind}"
    if base_key not in st.session_state:
        st.session_state[base_key] = load_holdings(user["id"], kind)
        st.session_state[ver_key] = 0
    base = st.session_state[base_key]
    if not with_date:
        base = base.drop(columns=["Buy date"])
    cfg = {"Symbol": st.column_config.TextColumn(help="NSE symbol, e.g. TCS"),
           "Buy price": st.column_config.NumberColumn(format="₹%.2f", min_value=0),
           "Qty": st.column_config.NumberColumn(format="%d", min_value=0, step=1)}
    if with_date:
        cfg["Buy date"] = st.column_config.DateColumn(format="DD MMM YYYY")
    edited = st.data_editor(base, num_rows="dynamic", width="stretch", column_config=cfg,
                            key=f"_editor_{kind}_{st.session_state[ver_key]}")
    c1, c2 = st.columns([1, 5])
    if c1.button("💾 Save", key=f"_save_{kind}", type="primary"):
        clean = edited.dropna(subset=["Symbol", "Buy price", "Qty"])
        clean = clean[clean.Symbol.astype(str).str.strip() != ""]
        save_holdings(user["id"], kind, clean)
        del st.session_state[base_key]
        st.toast("Portfolio saved")
        st.rerun()
    c2.caption("Add rows with ➕ at the bottom of the table, then click **Save** to keep them for next time.")
    return edited
