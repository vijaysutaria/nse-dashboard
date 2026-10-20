"""Intraday (day-trading) page: opening-range breakouts, VWAP, pivot levels and top movers.

Educational tool only. Yahoo intraday data is ~15 min delayed, which is too late to time real trades.
"""
from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from common import NIFTY_50

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN, MARKET_CLOSE, SQUARE_OFF = time(9, 15), time(15, 30), time(15, 15)
SETUP_COLORS = {"LONG": "#1a7f37", "SHORT": "#cf222e", "WAIT": "#6e7781", "EXTENDED": "#9a6700",
                "DONE": "#0969da"}


@st.cache_data(ttl=120, show_spinner=False)
def fetch_intraday(symbols: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    tickers = [f"{s}.NS" for s in symbols]
    raw = yf.download(tickers, period="5d", interval="5m", group_by="ticker",
                      auto_adjust=False, progress=False, threads=True)
    out = {}
    for s, t in zip(symbols, tickers):
        try:
            df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
        except KeyError:
            continue
        df = df.dropna(subset=["Close"])
        if df.empty:
            continue
        df.index = (df.index.tz_localize("UTC") if df.index.tz is None else df.index).tz_convert(IST)
        out[s] = df
    return out


def analyze(df: pd.DataFrame, or_minutes: int, rr: float) -> dict | None:
    days = sorted(set(df.index.date))
    if len(days) < 2:
        return None
    t = df[df.index.date == days[-1]]
    p = df[df.index.date == days[-2]]
    ph, pl, pc = p.High.max(), p.Low.min(), p.Close.iloc[-1]
    pivot = (ph + pl + pc) / 3
    levels = {"R2": pivot + (ph - pl), "R1": 2 * pivot - pl, "Pivot": pivot,
              "S1": 2 * pivot - ph, "S2": pivot - (ph - pl)}

    n = max(1, or_minutes // 5)
    orh, orl = t.High.iloc[:n].max(), t.Low.iloc[:n].min()
    typical = (t.High + t.Low + t.Close) / 3
    vwap = (typical * t.Volume).cumsum() / t.Volume.cumsum().replace(0, np.nan)
    last, v = t.Close.iloc[-1], vwap.iloc[-1]

    prior = [df[df.index.date == d].Volume.iloc[:len(t)].sum() for d in days[:-1]]
    rvol = t.Volume.sum() / np.mean(prior) if prior and np.mean(prior) > 0 else np.nan

    entry = stop = target = None
    mid = (orh + orl) / 2
    if len(t) <= n:
        setup = "WAIT: opening range still forming"
    elif last > orh and last > v:
        entry, stop = orh, mid
        target = entry + rr * (entry - stop)
        setup = "LONG: broke above opening range, above VWAP"
    elif last < orl and last < v:
        entry, stop = orl, mid
        target = entry - rr * (stop - entry)
        setup = "SHORT: broke below opening range, below VWAP"
    else:
        setup = "WAIT: inside range or mixed signals"
    if entry is not None:
        risk = abs(entry - stop)
        if (target - last) * np.sign(target - entry) <= 0:
            setup = "DONE: target already reached, don't chase"
        elif abs(last - entry) > risk:
            setup = "EXTENDED: moved >1R past entry, wait for pullback"

    return dict(today=t, vwap=vwap, levels=levels, orh=orh, orl=orl, last=last, vwap_last=v,
                prev_close=pc, gap=(t.Open.iloc[0] / pc - 1) * 100, chg=(last / pc - 1) * 100,
                rvol=rvol, setup=setup, entry=entry, stop=stop, target=target,
                day=days[-1], last_time=t.index[-1])


def market_status(now: datetime) -> str:
    if now.weekday() >= 5:
        return "🔴 Closed (weekend)"
    if now.time() < MARKET_OPEN:
        return "🟡 Pre-open: opens 9:15 AM IST"
    if now.time() > MARKET_CLOSE:
        return "🔴 Closed for the day"
    if now.time() >= SQUARE_OFF:
        return "🟠 Square-off time: close intraday (MIS) positions"
    return "🟢 Market open"


def color_setup(v: str):
    return f"color: white; background-color: {SETUP_COLORS.get(v.split(':')[0], '#6e7781')}; font-weight: 600"


# ---------------------------------------------------------------- sidebar
st.sidebar.title("⚙️ Settings")
universe = st.sidebar.multiselect("Stock universe (NSE symbols)", NIFTY_50, default=NIFTY_50, key="id_universe")
extra = st.sidebar.text_input("Add more NSE symbols (comma-separated)", key="id_extra")
if extra:
    universe = list(dict.fromkeys(universe + [s.strip().upper() for s in extra.split(",") if s.strip()]))
or_minutes = st.sidebar.select_slider("Opening range", [5, 15, 30, 60], value=15, key="id_or",
                                      format_func=lambda m: f"First {m} min")
rr = st.sidebar.slider("Reward : Risk for target", 1.0, 3.0, 2.0, 0.5, key="id_rr")
capital = st.sidebar.number_input("Trading capital (₹)", 1000, 10_000_000, 50_000, 5000, key="id_cap")
risk_pct = st.sidebar.slider("Max risk per trade (% of capital)", 0.25, 2.0, 0.5, 0.25, key="id_risk")
auto = st.sidebar.toggle("Auto-refresh every 2 min", value=True, key="id_auto")

st.title("⚡ Intraday Trading")
st.warning("**Prices are ~15 minutes delayed** (free Yahoo data), so use this to plan and learn rather than to time "
           "live entries. SEBI's 2024 study found about 7 in 10 individual intraday traders lost money. "
           "Educational tool, not investment advice.", icon="⚠️")

if not universe:
    st.info("Pick at least one stock in the sidebar.")
    st.stop()


@st.fragment(run_every="120s" if auto else None)
def body():
    now = datetime.now(IST)
    with st.spinner("Fetching 5-minute candles…"):
        data = fetch_intraday(tuple(universe))
    res = {s: r for s, df in data.items() if (r := analyze(df, or_minutes, rr))}
    if not res:
        st.error("Couldn't fetch intraday data. Check your internet connection.")
        return
    last_candle = max(r["last_time"] for r in res.values())
    st.markdown(f"**{market_status(now)}** · Now {now:%d %b %Y, %I:%M %p} IST · "
                f"Latest candle {last_candle:%d %b, %I:%M %p}")

    rows = []
    for s, r in res.items():
        risk = abs(r["entry"] - r["stop"]) if r["entry"] is not None else None
        qty = int(min(capital * risk_pct / 100 / risk, capital / r["entry"])) if risk else None
        rows.append({"Symbol": s, "Setup": r["setup"], "LTP": r["last"], "Chg %": r["chg"], "Gap %": r["gap"],
                     "vs VWAP %": (r["last"] / r["vwap_last"] - 1) * 100, "Rel. volume": r["rvol"],
                     "OR high": r["orh"], "OR low": r["orl"], "Entry": r["entry"], "Stop": r["stop"],
                     "Target": r["target"], "Qty": qty})
    table = pd.DataFrame(rows)
    order = {"LONG": 0, "SHORT": 1, "EXTENDED": 2, "DONE": 3, "WAIT": 4}
    table = table.assign(_o=table.Setup.str.split(":").str[0].map(order)) \
        .sort_values(["_o", "Rel. volume"], ascending=[True, False]).drop(columns="_o")

    k = st.columns(5)
    k[0].metric("🟢 Long setups", int(table.Setup.str.startswith("LONG").sum()))
    k[1].metric("🔴 Short setups", int(table.Setup.str.startswith("SHORT").sum()))
    k[2].metric("Waiting", int(table.Setup.str.startswith("WAIT").sum()))
    k[3].metric("Advancing", int((table["Chg %"] > 0).sum()))
    k[4].metric("Declining", int((table["Chg %"] < 0).sum()))

    tab_setups, tab_chart, tab_movers, tab_rules = st.tabs(
        ["🎯 Setups", "📊 Intraday chart", "🚀 Top movers", "📘 How it works"])
    money = "₹{:,.2f}"
    fmt = {"LTP": money, "Chg %": "{:+.2f}", "Gap %": "{:+.2f}", "vs VWAP %": "{:+.2f}", "Rel. volume": "{:.2f}×",
           "OR high": money, "OR low": money, "Entry": money, "Stop": money, "Target": money, "Qty": "{:,.0f}"}

    with tab_setups:
        only = st.toggle("Only LONG / SHORT setups", key="id_only")
        view = table[table.Setup.str.match("LONG|SHORT")] if only else table
        st.dataframe(view.style.format(fmt, na_rep="—").map(color_setup, subset=["Setup"]),
                     hide_index=True, width="stretch", height=min(38 * (len(view) + 1), 720))
        st.caption(f"Qty risks about {risk_pct}% of ₹{capital:,} if the stop is hit, without leverage. "
                   "Brokerage, STT and slippage are not included. Square off intraday positions by 3:15 PM.")

    with tab_chart:
        sym = st.selectbox("Stock", table.Symbol.tolist(), key="id_sym")
        r = res[sym]
        t = r["today"]
        c = st.columns(4)
        c[0].metric("LTP", f"₹{r['last']:,.2f}", f"{r['chg']:+.2f}%")
        c[1].metric("VWAP", f"₹{r['vwap_last']:,.2f}")
        c[2].metric("Opening range", f"₹{r['orl']:,.0f} – {r['orh']:,.0f}")
        c[3].metric("Relative volume", f"{r['rvol']:.2f}×")
        st.markdown(f"**Setup:** {r['setup']}")
        fig = go.Figure(go.Candlestick(x=t.index, open=t.Open, high=t.High, low=t.Low, close=t.Close, name=sym))
        fig.add_trace(go.Scatter(x=t.index, y=r["vwap"], name="VWAP", line=dict(color="#8250df", width=2)))
        fig.add_hrect(y0=r["orl"], y1=r["orh"], fillcolor="#0969da", opacity=0.08, line_width=0,
                      annotation_text=f"Opening range ({or_minutes} min)", annotation_position="top left")
        for name, y in r["levels"].items():
            fig.add_hline(y=y, line_dash="dot", line_width=1, line_color="#6e7781",
                          annotation_text=name, annotation_position="right")
        if r["entry"] is not None:
            fig.add_hline(y=r["stop"], line_color="#cf222e", annotation_text="Stop")
            fig.add_hline(y=r["target"], line_color="#1a7f37", annotation_text="Target")
        fig.update_layout(height=560, xaxis_rangeslider_visible=False, margin=dict(t=10, b=10),
                          legend=dict(orientation="h", y=1.04), yaxis_title="₹")
        st.plotly_chart(fig, width="stretch")
        st.caption(f"5-minute candles for {r['day']:%d %b %Y}. Dotted lines are classic pivots from the "
                   "previous session's high, low and close.")

    with tab_movers:
        cols = ["Symbol", "LTP", "Chg %", "Gap %", "Rel. volume"]
        m1, m2, m3 = st.columns(3)
        m1.markdown("**Top gainers**")
        m1.dataframe(table.nlargest(8, "Chg %")[cols].style.format(fmt), hide_index=True)
        m2.markdown("**Top losers**")
        m2.dataframe(table.nsmallest(8, "Chg %")[cols].style.format(fmt), hide_index=True)
        m3.markdown("**Unusual volume**")
        m3.dataframe(table.nlargest(8, "Rel. volume")[cols].style.format(fmt, na_rep="—"), hide_index=True)

    with tab_rules:
        st.markdown(f"""
### Opening-range breakout (ORB) with VWAP filter
1. **Opening range**: high and low of the first {or_minutes} minutes after 9:15 AM.
2. **LONG** when price breaks **above** the range high *and* trades above **VWAP** (volume-weighted average price).
   **SHORT** when it breaks **below** the range low *and* is below VWAP.
3. **Entry** = the range edge · **Stop** = middle of the range · **Target** = {rr}× the risk.
4. **EXTENDED**: price already moved more than one risk-unit past entry, so chasing it gives a poor reward/risk.
5. **DONE**: target already hit today.

### Other columns
- **Gap %**: today's open vs yesterday's close. Big gaps often mean news; trade them with care.
- **Rel. volume**: today's volume so far vs the same time on previous days. Above 1.5× means unusual interest.
- **Pivots (R2/R1/Pivot/S1/S2)**: support and resistance levels many traders watch, from yesterday's high, low and close.

### Discipline
- Risk a small fixed % per trade ({risk_pct}% here) and always place the stop-loss order.
- Square off all intraday (MIS) positions by 3:15 PM; brokers auto-square around 3:20 PM and charge for it.
- Data is about 15 minutes delayed. For live trading, use your broker's real-time chart to confirm every level.
""")


body()
