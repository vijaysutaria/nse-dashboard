"""NSE Swing Screener — a rule-based technical-analysis dashboard for Indian stocks.

Educational tool only. Signals are mechanical outputs of indicators, not investment advice.
Opened from home.py (run:  streamlit run home.py)
"""
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from common import NIFTY_50, fetch_prices as fetch
from db import holdings_editor

COLORS = {"BUY": "#1a7f37", "WATCH": "#9a6700", "SELL / AVOID": "#cf222e", "NEUTRAL": "#6e7781"}


# ---------------------------------------------------------------- data + indicators
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c, h, l = df["Close"], df["High"], df["Low"]
    df["SMA20"] = c.rolling(20).mean()
    df["SMA50"] = c.rolling(50).mean()
    df["SMA200"] = c.rolling(200).mean()

    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["RSI"] = (100 - 100 / (1 + gain / loss.replace(0, np.nan))).fillna(100)

    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACDsig"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACDhist"] = df["MACD"] - df["MACDsig"]

    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df["VolRatio"] = df["Volume"] / df["Volume"].rolling(20).mean()
    df["High52"] = h.rolling(252, min_periods=200).max()
    return df


def score_row(df: pd.DataFrame, i: int) -> tuple[int, list[str]]:
    """Bullish score 0-7 with human-readable reasons, evaluated at positional index i."""
    r, prev = df.iloc[i], df.iloc[i - 1]
    hist = df["MACDhist"].iloc[i - 5:i + 1]
    pts, why = 0, []
    if r.Close > r.SMA200:
        pts += 1; why.append("Above 200-DMA (long-term uptrend)")
    if r.SMA50 > r.SMA200:
        pts += 1; why.append("50-DMA > 200-DMA (golden-cross regime)")
    if r.Close > r.SMA20 > r.SMA50:
        pts += 1; why.append("Price > 20-DMA > 50-DMA (short-term trend up)")
    if r.MACD > r.MACDsig:
        pts += 1; why.append("MACD above signal line")
    if r.MACDhist > 0 and (hist < 0).any():
        pts += 1; why.append("Fresh MACD bullish crossover (last 5 days)")
    if 45 <= r.RSI <= 68:
        pts += 1; why.append(f"RSI {r.RSI:.0f}: healthy momentum, not overbought")
    if r.VolRatio >= 1.3 and r.Close > prev.Close:
        pts += 1; why.append(f"Up-day on {r.VolRatio:.1f}× average volume")
    return pts, why


def signal(df: pd.DataFrame, i: int) -> str:
    r = df.iloc[i]
    pts, _ = score_row(df, i)
    if r.RSI >= 75 or (r.Close < r.SMA50 and r.MACD < r.MACDsig):
        return "SELL / AVOID"
    if pts >= 5 and r.RSI < 70:
        return "BUY"
    if pts >= 3:
        return "WATCH"
    return "NEUTRAL"


def trade_plan(df: pd.DataFrame, atr_stop: float, rr: float) -> dict:
    r = df.iloc[-1]
    entry = r.Close
    stop = entry - atr_stop * r.ATR
    target = entry + rr * (entry - stop)
    trail = max(r.SMA20, entry - atr_stop * r.ATR)
    return dict(entry=entry, stop=stop, target=target, trail=trail,
                risk_pct=(entry - stop) / entry * 100, reward_pct=(target - entry) / entry * 100)


def backtest(df: pd.DataFrame, atr_stop: float, rr: float) -> tuple[pd.DataFrame, list]:
    """Enter next open on BUY; exit at stop, target, or SELL signal. One position at a time."""
    trades, markers, pos = [], [], None
    for i in range(200, len(df) - 1):
        row, nxt = df.iloc[i], df.iloc[i + 1]
        if pos is None:
            if signal(df, i) == "BUY":
                entry = nxt.Open
                stop = entry - atr_stop * row.ATR
                pos = dict(date=df.index[i + 1], entry=entry, stop=stop,
                           target=entry + rr * (entry - stop))
                markers.append(("buy", df.index[i + 1], entry))
            continue
        exit_px = reason = None
        if nxt.Low <= pos["stop"]:
            exit_px, reason = pos["stop"], "Stop-loss"
        elif nxt.High >= pos["target"]:
            exit_px, reason = pos["target"], "Target"
        elif signal(df, i) == "SELL / AVOID":
            exit_px, reason = nxt.Open, "Sell signal"
        if exit_px is not None:
            trades.append(dict(Entry=pos["date"].date(), Exit=df.index[i + 1].date(),
                               Buy=round(pos["entry"], 2), Sell=round(exit_px, 2),
                               Return_pct=round((exit_px / pos["entry"] - 1) * 100, 2), Reason=reason))
            markers.append(("sell", df.index[i + 1], exit_px))
            pos = None
    return pd.DataFrame(trades), markers


def color_signal(v):
    return f"color: white; background-color: {COLORS.get(v, '#6e7781')}; font-weight: 600"


# ---------------------------------------------------------------- sidebar
st.sidebar.title("⚙️ Settings")
universe = st.sidebar.multiselect("Stock universe (NSE symbols)", NIFTY_50, default=NIFTY_50)
extra = st.sidebar.text_input("Add more NSE symbols (comma-separated)", placeholder="IRCTC, DMART, PIDILITIND")
if extra:
    universe = list(dict.fromkeys(universe + [s.strip().upper() for s in extra.split(",") if s.strip()]))
atr_stop = st.sidebar.slider("Stop-loss distance (× ATR)", 1.0, 4.0, 2.0, 0.5)
rr = st.sidebar.slider("Reward : Risk ratio for target", 1.0, 4.0, 2.0, 0.5)
capital = st.sidebar.number_input("Capital per trade (₹)", 1000, 10_000_000, 100_000, 5000)
risk_per_trade = st.sidebar.slider("Max risk per trade (% of capital)", 0.5, 5.0, 1.0, 0.5)
if st.sidebar.button("🔄 Refresh data"):
    st.cache_data.clear()

st.title("📈 NSE Swing Screener")
st.caption("Rule-based technical signals on NSE stocks (daily candles, Yahoo Finance data, ~15 min delayed). "
           "**Educational tool, not investment advice.** Past patterns don't guarantee future returns. "
           "Do your own research or consult a SEBI-registered advisor.")

if not universe:
    st.info("Pick at least one stock in the sidebar.")
    st.stop()

with st.spinner(f"Fetching {len(universe)} stocks from NSE…"):
    data = {s: add_indicators(df) for s, df in fetch(tuple(universe)).items()}
if not data:
    st.error("Couldn't fetch any data. Check your internet connection and try Refresh.")
    st.stop()

rows = []
for sym, d in data.items():
    r = d.iloc[-1]
    pts, _ = score_row(d, len(d) - 1)
    plan = trade_plan(d, atr_stop, rr)
    rows.append({"Symbol": sym, "Signal": signal(d, len(d) - 1), "Score": pts, "Price": r.Close,
                 "Chg %": (r.Close / d.Close.iloc[-2] - 1) * 100, "RSI": r.RSI,
                 "From 52W high %": (r.Close / r.High52 - 1) * 100,
                 "Stop-loss": plan["stop"], "Target": plan["target"],
                 "Risk %": plan["risk_pct"], "Reward %": plan["reward_pct"]})
screen = pd.DataFrame(rows).sort_values(["Score", "RSI"], ascending=[False, True])
missing = sorted(set(universe) - set(data))
last_date = max(d.index[-1] for d in data.values()).date()

# ---------------------------------------------------------------- KPIs
k1, k2, k3, k4 = st.columns(4)
k1.metric("Stocks scanned", len(screen), f"data as of {last_date}", delta_color="off")
k2.metric("🟢 BUY signals", int((screen.Signal == "BUY").sum()))
k3.metric("🟡 WATCH", int((screen.Signal == "WATCH").sum()))
k4.metric("🔴 SELL / AVOID", int((screen.Signal == "SELL / AVOID").sum()))
if missing:
    st.caption(f"⚠️ No/insufficient data for: {', '.join(missing)}")

tab_screen, tab_detail, tab_port, tab_rules = st.tabs(
    ["🔎 Screener", "📊 Stock deep-dive", "💼 My holdings: when to sell", "📘 How signals work"])

fmt = {"Price": "₹{:,.2f}", "Chg %": "{:+.2f}", "RSI": "{:.0f}", "From 52W high %": "{:+.1f}",
       "Stop-loss": "₹{:,.2f}", "Target": "₹{:,.2f}", "Risk %": "{:.1f}", "Reward %": "{:.1f}"}

with tab_screen:
    filt = st.radio("Show", ["All", "BUY", "WATCH", "SELL / AVOID"], horizontal=True)
    view = screen if filt == "All" else screen[screen.Signal == filt]
    st.dataframe(view.style.format(fmt).map(color_signal, subset=["Signal"]),
                 hide_index=True, width="stretch", height=min(38 * (len(view) + 1), 700))
    buys = screen[screen.Signal == "BUY"]
    if len(buys):
        st.subheader("🟢 Today's BUY candidates: position sizing")
        sz = buys[["Symbol", "Price", "Stop-loss", "Target"]].copy()
        risk_amt = capital * risk_per_trade / 100
        sz["Qty"] = np.minimum(np.floor(risk_amt / (sz.Price - sz["Stop-loss"])),
                               np.floor(capital / sz.Price)).astype(int)
        sz["Invest ₹"] = sz.Qty * sz.Price
        sz["Max loss ₹"] = sz.Qty * (sz.Price - sz["Stop-loss"])
        sz["Potential gain ₹"] = sz.Qty * (sz.Target - sz.Price)
        st.dataframe(sz.style.format({"Price": "₹{:,.2f}", "Stop-loss": "₹{:,.2f}", "Target": "₹{:,.2f}",
                                      "Invest ₹": "₹{:,.0f}", "Max loss ₹": "₹{:,.0f}",
                                      "Potential gain ₹": "₹{:,.0f}"}),
                     hide_index=True, width="stretch")
        st.caption(f"Qty sized so hitting the stop loses ≈ {risk_per_trade}% of ₹{capital:,} "
                   "(capped at full capital). Brokerage, STT and taxes are not included.")

with tab_detail:
    sym = st.selectbox("Stock", screen.Symbol.tolist())
    full = data[sym]
    d = full.iloc[-260:]
    pts, why = score_row(full, len(full) - 1)
    plan = trade_plan(full, atr_stop, rr)
    sig = signal(full, len(full) - 1)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.markdown(f"### <span style='color:{COLORS[sig]}'>{sig}</span>", unsafe_allow_html=True)
    c2.metric("Score", f"{pts} / 7")
    c3.metric("Entry (last close)", f"₹{plan['entry']:,.2f}")
    c4.metric("Stop-loss", f"₹{plan['stop']:,.2f}", f"-{plan['risk_pct']:.1f}%", delta_color="off")
    c5.metric("Target", f"₹{plan['target']:,.2f}", f"+{plan['reward_pct']:.1f}%")
    st.markdown("**Why:** " + (" · ".join(why) if why else "No bullish conditions met."))
    st.markdown(f"**Trailing stop if already holding:** ₹{plan['trail']:,.2f} "
                f"(higher of 20-DMA or close − {atr_stop}×ATR). Exit if a daily close falls below it.")

    trades, markers = backtest(full, atr_stop, rr)
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=d.index, open=d.Open, high=d.High, low=d.Low, close=d.Close, name=sym), 1, 1)
    for col, c in [("SMA20", "#0969da"), ("SMA50", "#bf8700"), ("SMA200", "#8250df")]:
        fig.add_trace(go.Scatter(x=d.index, y=d[col], name=col, line=dict(width=1.3, color=c)), 1, 1)
    for kind, color, shape in [("buy", "#1a7f37", "triangle-up"), ("sell", "#cf222e", "triangle-down")]:
        pts_ = [(t, p) for k, t, p in markers if k == kind and t >= d.index[0]]
        if pts_:
            fig.add_trace(go.Scatter(x=[t for t, _ in pts_], y=[p for _, p in pts_], mode="markers",
                                     name=f"Past {kind}", marker=dict(symbol=shape, size=12, color=color)), 1, 1)
    fig.add_hline(y=plan["stop"], line_dash="dot", line_color="#cf222e", annotation_text="Stop", row=1, col=1)
    fig.add_hline(y=plan["target"], line_dash="dot", line_color="#1a7f37", annotation_text="Target", row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d.RSI, name="RSI", line=dict(color="#6639ba")), 2, 1)
    for lvl in (30, 70):
        fig.add_hline(y=lvl, line_dash="dash", line_color="gray", row=2, col=1)
    fig.add_trace(go.Bar(x=d.index, y=d.MACDhist, name="MACD hist",
                         marker_color=np.where(d.MACDhist >= 0, "#1a7f37", "#cf222e")), 3, 1)
    fig.add_trace(go.Scatter(x=d.index, y=d.MACD, name="MACD", line=dict(color="#0969da", width=1)), 3, 1)
    fig.add_trace(go.Scatter(x=d.index, y=d.MACDsig, name="Signal", line=dict(color="#bf8700", width=1)), 3, 1)
    fig.update_layout(height=720, xaxis_rangeslider_visible=False, margin=dict(t=10, b=10),
                      legend=dict(orientation="h", y=1.02))
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    st.plotly_chart(fig, width="stretch")

    st.subheader("How these rules would have done on this stock (backtest)")
    if trades.empty:
        st.info("No completed trades in the backtest window.")
    else:
        wins = (trades.Return_pct > 0).mean() * 100
        comp = (np.prod(1 + trades.Return_pct / 100) - 1) * 100
        bh = (full.Close.iloc[-1] / full.Close.iloc[200] - 1) * 100
        b1, b2, b3, b4 = st.columns(4)
        b1.metric("Trades", len(trades))
        b2.metric("Win rate", f"{wins:.0f}%")
        b3.metric("Strategy return", f"{comp:+.1f}%")
        b4.metric("Buy & hold return", f"{bh:+.1f}%")
        st.dataframe(trades, hide_index=True, width="stretch")
        st.caption("Simplified: no costs or slippage. Past results don't predict future returns.")

with tab_port:
    st.markdown("Enter what you hold. Each position is checked against its stop, target and the sell rules.")
    holdings = holdings_editor("swing", with_date=False)
    holdings = holdings.dropna(subset=["Symbol"])
    need = tuple(str(s).strip().upper() for s in holdings.Symbol if str(s).strip().upper() not in data)
    if need:
        data.update({s: add_indicators(df) for s, df in fetch(need).items()})
    out = []
    for _, h in holdings.iterrows():
        s = str(h.Symbol).strip().upper()
        if s not in data or pd.isna(h["Buy price"]) or pd.isna(h.Qty):
            continue
        d = data[s]
        r = d.iloc[-1]
        bp, q = float(h["Buy price"]), float(h.Qty)
        stop = bp - atr_stop * r.ATR
        tgt = bp + rr * (bp - stop)
        trail = max(r.SMA20, r.Close - atr_stop * r.ATR, stop)
        sig = signal(d, len(d) - 1)
        if r.Close <= stop:
            action = "🔴 SELL: stop-loss hit"
        elif r.Close >= tgt:
            action = "🟢 BOOK PROFIT: target reached (or trail the stop)"
        elif sig == "SELL / AVOID":
            action = ("🔴 SELL: trend/momentum turned down" if r.Close < r.SMA50
                      else "🟠 Overbought: consider partial profit")
        elif r.Close < trail:
            action = "🟠 Below trailing stop: consider exit"
        else:
            action = f"⚪ HOLD: trail stop at ₹{trail:,.2f}"
        out.append({"Symbol": s, "Buy": bp, "LTP": r.Close, "Qty": q, "P&L ₹": (r.Close - bp) * q,
                    "P&L %": (r.Close / bp - 1) * 100, "Stop": stop, "Target": tgt,
                    "Trail stop": trail, "Action": action})
    if out:
        pf = pd.DataFrame(out)
        tot, inv = pf["P&L ₹"].sum(), (pf.Buy * pf.Qty).sum()
        st.metric("Total P&L", f"₹{tot:,.0f}", f"{tot / inv * 100:+.2f}%")
        st.dataframe(pf.style.format({"Buy": "₹{:,.2f}", "LTP": "₹{:,.2f}", "Qty": "{:.0f}",
                                      "P&L ₹": "₹{:+,.0f}", "P&L %": "{:+.2f}", "Stop": "₹{:,.2f}",
                                      "Target": "₹{:,.2f}", "Trail stop": "₹{:,.2f}"}),
                     hide_index=True, width="stretch")

with tab_rules:
    st.markdown(f"""
### Bullish score (0–7): one point each
1. Close above the **200-day moving average**: long-term uptrend
2. **50-DMA above 200-DMA**: "golden cross" regime
3. **Close > 20-DMA > 50-DMA**: short-term trend aligned
4. **MACD above its signal line**: positive momentum
5. **Fresh MACD crossover** within the last 5 sessions: momentum just turned
6. **RSI 45–68**: strong but not overbought
7. **Up-day on ≥1.3× average volume**: buying interest

### Signals
- **BUY**: score ≥ 5 and RSI < 70
- **WATCH**: score 3–4
- **SELL / AVOID**: RSI ≥ 75 (overbought) **or** close below 50-DMA with MACD below signal (trend breaking)
- **NEUTRAL**: everything else

### When to sell (exit plan)
- **Stop-loss** = entry − {atr_stop} × ATR(14). ATR adapts to each stock's volatility.
- **Target** = entry + {rr} × (entry − stop), a {rr}:1 reward-to-risk ratio.
- **Trailing stop** = higher of the 20-DMA or close − {atr_stop}×ATR. Ratchet it up as the price rises and exit on a close below it.
- Exit early if a **SELL / AVOID** signal appears.

### Limits
Daily data only, from Yahoo Finance and roughly 15 minutes delayed. The dashboard ignores news, earnings, fundamentals and taxes (STCG). Use it as a filter for your own research, not as a decision.
""")

st.caption(f"Last refreshed {datetime.now():%d %b %Y, %H:%M}")
