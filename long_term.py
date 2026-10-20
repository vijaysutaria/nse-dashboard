"""Long-term investor page: business quality, growth and valuation screen plus holding reviews.

Educational tool only. Scores are mechanical outputs of public data, not investment advice.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from common import NIFTY_50, fetch_fundamentals, fetch_prices
from db import holdings_editor

VERDICT_COLORS = {"ACCUMULATE": "#1a7f37", "QUALITY: WAIT FOR DIP": "#0969da",
                  "WATCHLIST": "#9a6700", "AVOID": "#cf222e"}


# ---------------------------------------------------------------- analytics
def cagr(close: pd.Series, years: float) -> float | None:
    n = int(round(52 * years))
    if len(close) <= n:
        return None
    return (close.iloc[-1] / close.iloc[-1 - n]) ** (1 / years) - 1


def sector_pe_medians(funds: dict[str, dict]) -> tuple[dict[str, float], float]:
    df = pd.DataFrame([{"sector": f.get("sector"), "pe": f.get("trailingPE")} for f in funds.values()])
    df = df[(df.pe > 0) & (df.pe < 200)]
    overall = df.pe.median()
    by_sector = df.groupby("sector").pe.agg(["median", "count"])
    return {s: r["median"] for s, r in by_sector.iterrows() if r["count"] >= 2}, overall


def evaluate(f: dict, w: pd.DataFrame, sector_pe: float) -> dict:
    """Score 0-100 on the metrics available, with a checklist explaining every point."""
    close = w.Close
    ma40 = close.rolling(40).mean().iloc[-1]
    price = close.iloc[-1]
    checks = []

    def add(metric, value, earned, mx, bench):
        checks.append(dict(Metric=metric, Value=value, Points=f"{earned}/{mx}", Benchmark=bench,
                           _e=earned, _m=mx))

    roe = f.get("returnOnEquity")
    if roe is not None:
        add("Return on equity", f"{roe * 100:.1f}%",
            20 if roe >= .20 else 14 if roe >= .15 else 7 if roe >= .10 else 0, 20, "≥20% excellent · ≥15% good")
    de = f.get("debtToEquity")
    if de is not None and f.get("sector") != "Financial Services":
        add("Debt / equity", f"{de / 100:.2f}", 15 if de < 50 else 8 if de < 100 else 0, 15,
            "<0.5 strong · <1.0 acceptable")
    pm = f.get("profitMargins")
    if pm is not None:
        add("Net profit margin", f"{pm * 100:.1f}%", 10 if pm >= .15 else 5 if pm >= .08 else 0, 10,
            "≥15% strong · ≥8% fair")
    eg = f.get("earningsGrowth")
    if eg is not None:
        add("Earnings growth (YoY)", f"{eg * 100:+.1f}%", 10 if eg > .10 else 5 if eg > 0 else 0, 10,
            ">10% strong · >0% positive")
    rg = f.get("revenueGrowth")
    if rg is not None:
        add("Revenue growth (YoY)", f"{rg * 100:+.1f}%", 10 if rg > .10 else 5 if rg > 0 else 0, 10,
            ">10% strong · >0% positive")
    c5 = cagr(close, 5)
    if c5 is not None:
        add("5-year price CAGR", f"{c5 * 100:+.1f}%", 10 if c5 > .12 else 5 if c5 > 0 else 0, 10,
            ">12% beats typical index return")

    pe = f.get("trailingPE")
    peg = rel = None
    if f:  # only judge valuation when fundamentals were fetched at all
        if pe is not None and pe > 0:
            if eg is not None and eg > 0:
                peg = pe / (min(eg, 0.5) * 100)
            rel = pe / sector_pe if sector_pe else None
            if peg is not None:
                pts = 15 if peg < 1.5 else 8 if peg < 2.5 else 0
                add("Valuation (PEG)", f"P/E {pe:.1f} · PEG {peg:.2f}", pts, 15, "PEG <1.5 cheap for growth · <2.5 fair")
            else:
                pts = 15 if rel and rel < 0.9 else 8 if rel and rel < 1.3 else 0
                add("Valuation (vs sector P/E)", f"P/E {pe:.1f} vs {sector_pe:.1f}", pts, 15,
                    "<0.9× sector cheap · <1.3× fair")
        else:
            add("Valuation", "Loss-making / no P/E", 0, 15, "Needs positive earnings")
    add("Long-term trend", "Above 40-week avg" if price > ma40 else "Below 40-week avg",
        10 if price > ma40 else 0, 10, "Price above ~200-day / 40-week average")

    earned, mx = sum(c["_e"] for c in checks), sum(c["_m"] for c in checks)
    score = round(earned / mx * 100) if mx else 0
    expensive = (peg is not None and peg >= 2.5) or (rel is not None and rel >= 1.5) or price > ma40 * 1.20
    if score >= 70:
        verdict = "QUALITY: WAIT FOR DIP" if expensive else "ACCUMULATE"
    elif score >= 55:
        verdict = "WATCHLIST"
    else:
        verdict = "AVOID"
    return dict(score=score, verdict=verdict, checks=checks, coverage=mx, price=price, ma40=ma40,
                buy_below=ma40 * 1.05, high52=w.High.iloc[-52:].max(), pe=pe, peg=peg, c5=c5,
                c1=cagr(close, 1), c3=cagr(close, 3), c10=cagr(close, 10))


def color_verdict(v):
    return f"color: white; background-color: {VERDICT_COLORS.get(v, '#6e7781')}; font-weight: 600"


def pct(x):
    return None if x is None or pd.isna(x) else x * 100


# ---------------------------------------------------------------- sidebar + data
st.sidebar.title("⚙️ Settings")
universe = st.sidebar.multiselect("Stock universe (NSE symbols)", NIFTY_50, default=NIFTY_50, key="lt_universe")
extra = st.sidebar.text_input("Add more NSE symbols (comma-separated)", placeholder="PIDILITIND, DMART, HAL",
                              key="lt_extra")
if extra:
    universe = list(dict.fromkeys(universe + [s.strip().upper() for s in extra.split(",") if s.strip()]))
max_weight = st.sidebar.slider("Max weight per stock (%)", 5, 40, 20, 5)
max_sector = st.sidebar.slider("Max weight per sector (%)", 15, 60, 35, 5)
if st.sidebar.button("🔄 Refresh data", key="lt_refresh"):
    st.cache_data.clear()

st.title("🏦 Long-Term Investor Dashboard")
st.caption("Scores NSE stocks on business quality, growth and valuation, and reviews your holdings for "
           "long-term exit triggers. Data: Yahoo Finance (fundamentals can lag or be missing). "
           "**Educational tool, not investment advice.** Do your own research or consult a SEBI-registered advisor.")

if not universe:
    st.info("Pick at least one stock in the sidebar.")
    st.stop()


def load(symbols: tuple[str, ...]):
    prices = fetch_prices(symbols, period="10y", interval="1wk", min_rows=60)
    funds = fetch_fundamentals(symbols)
    return prices, funds


with st.spinner(f"Fetching 10 years of prices and fundamentals for {len(universe)} stocks (first load ≈ 30 s)…"):
    prices, funds = load(tuple(universe))
if not prices:
    st.error("Couldn't fetch any data. Check your internet connection and try Refresh.")
    st.stop()

sector_pe, overall_pe = sector_pe_medians(funds)
results = {}
for sym, w in prices.items():
    f = funds.get(sym) or {}
    results[sym] = evaluate(f, w, sector_pe.get(f.get("sector"), overall_pe))

rows = []
for sym, r in results.items():
    f = funds.get(sym) or {}
    rows.append({"Symbol": sym, "Company": f.get("longName") or sym, "Sector": f.get("sector") or "—",
                 "Verdict": r["verdict"], "Score": r["score"], "Price": r["price"],
                 "Accumulate below": r["buy_below"], "P/E": r["pe"],
                 "Sector P/E": sector_pe.get(f.get("sector"), overall_pe),
                 "ROE %": pct(f.get("returnOnEquity")),
                 "D/E": None if f.get("debtToEquity") is None else f["debtToEquity"] / 100,
                 "Div yield %": f.get("dividendYield"), "5Y CAGR %": pct(r["c5"]),
                 "From 52W high %": (r["price"] / r["high52"] - 1) * 100})
screen = pd.DataFrame(rows).sort_values("Score", ascending=False)
missing = sorted(set(universe) - set(prices))

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Stocks scored", len(screen))
for col, v in zip([k2, k3, k4, k5], VERDICT_COLORS):
    col.metric(v.title(), int((screen.Verdict == v).sum()))
if missing:
    st.caption(f"⚠️ No/insufficient data for: {', '.join(missing)}")

tab_screen, tab_detail, tab_port, tab_rules = st.tabs(
    ["🔎 Quality screener", "📊 Company deep-dive", "💼 My portfolio: hold or sell?", "📘 How scoring works"])

num = "{:,.1f}"
fmt = {"Price": "₹{:,.2f}", "Accumulate below": "₹{:,.2f}", "P/E": num, "Sector P/E": num, "ROE %": num,
       "D/E": "{:.2f}", "Div yield %": "{:.2f}", "5Y CAGR %": "{:+.1f}", "From 52W high %": "{:+.1f}"}

with tab_screen:
    c_a, c_b = st.columns([2, 1])
    filt = c_a.radio("Show", ["All"] + list(VERDICT_COLORS), horizontal=True)
    sectors = c_b.multiselect("Sector", sorted(screen.Sector.unique()))
    view = screen if filt == "All" else screen[screen.Verdict == filt]
    if sectors:
        view = view[view.Sector.isin(sectors)]
    st.dataframe(view.style.format(fmt, na_rep="—").map(color_verdict, subset=["Verdict"]),
                 hide_index=True, width="stretch", height=min(38 * (len(view) + 1), 720))
    st.caption("**Accumulate below** ≈ 5% above the 40-week average price. Long-term investors often buy in "
               "tranches (e.g. monthly) near or under this level instead of chasing highs.")

with tab_detail:
    sym = st.selectbox("Company", screen.Symbol.tolist(),
                       format_func=lambda s: f"{s} · {(funds.get(s) or {}).get('longName') or ''}")
    r, f, w = results[sym], funds.get(sym) or {}, prices[sym]
    st.markdown(f"#### {f.get('longName') or sym}  \n{f.get('sector') or '—'} · {f.get('industry') or '—'}"
                + (f" · Market cap ₹{f['marketCap'] / 1e7:,.0f} Cr" if f.get("marketCap") else ""))
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f"### <span style='color:{VERDICT_COLORS[r['verdict']]}'>{r['verdict']}</span>",
                unsafe_allow_html=True)
    c2.metric("Quality score", f"{r['score']} / 100")
    c3.metric("Price", f"₹{r['price']:,.2f}", f"{(r['price'] / r['high52'] - 1) * 100:+.1f}% vs 52W high",
              delta_color="off")
    c4.metric("Accumulate below", f"₹{r['buy_below']:,.2f}")

    st.dataframe(pd.DataFrame(r["checks"]).drop(columns=["_e", "_m"]), hide_index=True, width="stretch")

    cg = st.columns(4)
    for col, label, key in zip(cg, ["1Y", "3Y", "5Y", "10Y"], ["c1", "c3", "c5", "c10"]):
        col.metric(f"{label} CAGR", "—" if r[key] is None else f"{r[key] * 100:+.1f}%")

    w = w.assign(MA40=w.Close.rolling(40).mean(), MA200=w.Close.rolling(200).mean())
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=w.index, y=w.Close, name="Weekly close", line=dict(color="#24292f", width=1.4)))
    fig.add_trace(go.Scatter(x=w.index, y=w.MA40, name="40-week avg (~200-day)", line=dict(color="#0969da")))
    fig.add_trace(go.Scatter(x=w.index, y=w.MA200, name="200-week avg (~4 yr)", line=dict(color="#8250df")))
    fig.add_hline(y=r["buy_below"], line_dash="dot", line_color="#1a7f37", annotation_text="Accumulate below")
    fig.update_layout(height=480, margin=dict(t=10, b=10), legend=dict(orientation="h", y=1.05),
                      yaxis_title="₹", yaxis_type="log")
    st.plotly_chart(fig, width="stretch")
    st.caption("Log scale, so equal percentage moves look equal. Ten years of weekly prices, where available.")

with tab_port:
    st.markdown("Enter your long-term holdings, including the **buy date** for tax timing. If a stock had a "
                "bonus or split since you bought it, enter the adjusted buy price and quantity.")
    holdings = holdings_editor("long", with_date=True)
    holdings = holdings.dropna(subset=["Symbol", "Buy price", "Qty"])
    holdings = holdings.assign(Symbol=holdings.Symbol.astype(str).str.strip().str.upper())
    need = tuple(s for s in holdings.Symbol.unique() if s not in prices)
    if need:
        p2, f2 = load(need)
        prices.update(p2)
        funds.update(f2)
        for s in p2:
            results[s] = evaluate(f2.get(s) or {}, p2[s],
                                  sector_pe.get((f2.get(s) or {}).get("sector"), overall_pe))

    today = date.today()
    out = []
    for _, h in holdings.iterrows():
        s = h.Symbol
        if s not in results:
            continue
        r, f = results[s], funds.get(s) or {}
        bp, q = float(h["Buy price"]), float(h.Qty)
        bd = h["Buy date"] if not pd.isna(h["Buy date"]) else None
        bd = bd.date() if hasattr(bd, "date") and callable(bd.date) else bd
        held = (today - bd).days if bd else None
        ltcg_on = (pd.Timestamp(bd) + pd.DateOffset(years=1) + timedelta(days=1)).date() if bd else None
        out.append(dict(Symbol=s, Sector=f.get("sector") or "—", Buy=bp, LTP=r["price"], Qty=q,
                        Value=r["price"] * q, PnL=(r["price"] - bp) * q, PnL_pct=(r["price"] / bp - 1) * 100,
                        CAGR=((r["price"] / bp) ** (365 / held) - 1) * 100 if held and held >= 180 else None,
                        Score=r["score"], _r=r, _f=f, _ltcg_on=ltcg_on))

    if out:
        pf = pd.DataFrame(out)
        total = pf.Value.sum()
        pf["Weight %"] = pf.Value / total * 100
        sector_w = pf.groupby("Sector").Value.sum() / total * 100

        actions, taxes = [], []
        for _, p in pf.iterrows():
            r, f = p._r, p._f
            pe, spe = r["pe"], sector_pe.get(f.get("sector"), overall_pe)
            if p.Score < 45:
                a = f"🔴 REVIEW / EXIT: business quality weak (score {p.Score})"
            elif r["price"] < r["ma40"] * 0.85:
                a = "🟠 REVIEW: >15% below 40-week avg, long-term trend broken"
            elif pe and spe and pe > 2 * spe and pe > 40:
                a = f"🟠 Consider trimming: very rich valuation (P/E {pe:.0f} vs sector {spe:.0f})"
            elif p["Weight %"] > max_weight:
                a = f"🟡 REBALANCE: {p['Weight %']:.0f}% of portfolio (limit {max_weight}%)"
            elif sector_w.get(p.Sector, 0) > max_sector:
                a = f"🟡 Sector heavy: {p.Sector} is {sector_w[p.Sector]:.0f}% of portfolio"
            else:
                a = "🟢 HOLD: thesis intact"
            actions.append(a)
            if p._ltcg_on is None:
                taxes.append("Add buy date")
            elif today >= p._ltcg_on:
                taxes.append("Long-term (LTCG 12.5%)")
            else:
                days = (p._ltcg_on - today).days
                note = f"Short-term (STCG 20%): LTCG in {days} days"
                if p.PnL > 0 and not a.startswith("🟢") and days <= 90:
                    note += ". Selling after then may cut tax"
                taxes.append(note)
        pf["Action"], pf["Tax status"] = actions, taxes

        m1, m2, m3, m4 = st.columns(4)
        invested = (pf.Buy * pf.Qty).sum()
        m1.metric("Invested", f"₹{invested:,.0f}")
        m2.metric("Current value", f"₹{total:,.0f}")
        m3.metric("Total P&L", f"₹{pf.PnL.sum():,.0f}", f"{(total / invested - 1) * 100:+.2f}%")
        m4.metric("Weighted quality score", f"{np.average(pf.Score, weights=pf.Value):.0f} / 100")

        show = pf[["Symbol", "Sector", "Buy", "LTP", "Qty", "PnL", "PnL_pct", "CAGR", "Weight %", "Score",
                   "Action", "Tax status"]].rename(columns={"PnL": "P&L ₹", "PnL_pct": "P&L %", "CAGR": "CAGR %"})
        st.dataframe(show.style.format({"Buy": "₹{:,.2f}", "LTP": "₹{:,.2f}", "Qty": "{:.0f}", "P&L ₹": "₹{:+,.0f}",
                                        "P&L %": "{:+.1f}", "CAGR %": "{:+.1f}", "Weight %": "{:.1f}"}, na_rep="—"),
                     hide_index=True, width="stretch")
        st.caption("CAGR is shown for positions held 6 months or more. Tax rates are listed equity rules from "
                   "23 Jul 2024: LTCG 12.5% on gains above ₹1.25 lakh per year, STCG 20%. Confirm with your CA.")

        fig = px.pie(sector_w.reset_index(), names="Sector", values="Value", hole=0.5,
                     title="Sector allocation (%)")
        fig.update_layout(height=380, margin=dict(t=40, b=10))
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No holdings yet. Add your stocks above and click Save to get hold / sell reviews.")

with tab_rules:
    st.markdown(f"""
### Quality score (0–100)
Points are earned on each metric that has data, then scaled to 100.

| Metric | Points | Full marks when |
|---|---|---|
| Return on equity | 20 | ≥ 20% (14 pts ≥ 15%, 7 pts ≥ 10%) |
| Debt / equity *(not used for banks / NBFCs)* | 15 | < 0.5 (8 pts < 1.0) |
| Net profit margin | 10 | ≥ 15% (5 pts ≥ 8%) |
| Earnings growth (YoY) | 10 | > 10% (5 pts > 0) |
| Revenue growth (YoY) | 10 | > 10% (5 pts > 0) |
| 5-year price CAGR | 10 | > 12% (5 pts > 0) |
| Valuation | 15 | PEG < 1.5, or P/E < 0.9× sector median |
| Long-term trend | 10 | Price above its 40-week average |

### Verdicts
- **ACCUMULATE**: score ≥ 70 and not expensive. Consider buying in tranches.
- **QUALITY: WAIT FOR DIP**: score ≥ 70 but expensive (PEG ≥ 2.5, P/E ≥ 1.5× sector, or price > 20% above its 40-week average).
- **WATCHLIST**: score 55–69.
- **AVOID**: score below 55.

### When a long-term investor should consider selling
Long-term selling is about the business and your portfolio, not daily price swings:
1. **Business quality deteriorates**: score falls below 45 (falling ROE, shrinking earnings, rising debt).
2. **Long-term trend breaks**: price more than 15% below its 40-week average. Review why before acting.
3. **Extreme valuation**: P/E above 2× sector median and above 40. Consider trimming, not exiting fully.
4. **Overweight position**: more than {max_weight}% of the portfolio in one stock, or more than {max_sector}% in one sector. Rebalance.
5. **Tax timing**: holdings under 12 months pay STCG at 20%. If a sell isn't urgent and LTCG is close, waiting can save tax.

### Limits
Yahoo Finance fundamentals are trailing figures, can lag quarterly results and are sometimes missing.
The score ignores management quality, governance, competitive moat, promoter pledging and news.
Read annual reports and concall notes before investing.
""")
