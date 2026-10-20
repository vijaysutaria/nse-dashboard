"""Shared stock universe and data fetching for both dashboard pages."""
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import streamlit as st
import yfinance as yf

NIFTY_50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO",
    "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL", "CIPLA", "COALINDIA", "DRREDDY",
    "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY", "ITC", "JIOFIN",
    "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM",
    "TATASTEEL", "TCS", "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
]

INFO_KEYS = ["longName", "sector", "industry", "marketCap", "trailingPE", "forwardPE", "priceToBook",
             "returnOnEquity", "debtToEquity", "profitMargins", "revenueGrowth", "earningsGrowth",
             "dividendYield"]


@st.cache_data(ttl=900, show_spinner=False)
def fetch_prices(symbols: tuple[str, ...], period: str = "2y", interval: str = "1d",
                 min_rows: int = 210) -> dict[str, pd.DataFrame]:
    tickers = [f"{s}.NS" for s in symbols]
    raw = yf.download(tickers, period=period, interval=interval, group_by="ticker",
                      auto_adjust=True, progress=False, threads=True)
    out = {}
    for s, t in zip(symbols, tickers):
        try:
            df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
            df = df.dropna(subset=["Close"])
            if len(df) >= min_rows:
                out[s] = df.copy()
        except KeyError:
            continue
    return out


def _info(symbol: str) -> dict:
    try:
        info = yf.Ticker(f"{symbol}.NS").info
    except Exception:
        return {}
    return {k: info.get(k) for k in INFO_KEYS}


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_fundamentals(symbols: tuple[str, ...]) -> dict[str, dict]:
    with ThreadPoolExecutor(max_workers=8) as ex:
        return dict(zip(symbols, ex.map(_info, symbols)))
