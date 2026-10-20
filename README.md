# NSE Investor Dashboard

Streamlit app with three pages, each behind a login with per-user saved portfolios:

- **Long-term investing**: quality / growth / valuation score, accumulate-below price, hold-or-sell review with LTCG/STCG timing
- **Swing trading screener**: daily technical signals, ATR stop-loss and targets, backtest
- **Intraday trading**: opening-range breakout with VWAP, pivots, top movers (Yahoo data, ~15 min delayed)

Educational tool, not investment advice.

## Run on this Mac

It runs as a login service at http://localhost:8501 (see `dashboard.sh start | stop | restart | status`).
Accounts and portfolios are stored in `data/app.db`. The sign-up invite code is in `.streamlit/secrets.toml`.

## Put it on the internet (free)

1. **Database**: create a free Postgres database at [neon.tech](https://neon.tech) and copy its connection string.
2. **Code**: push this folder to a **private** GitHub repository. `.gitignore` keeps out secrets, the local database and the venv.
3. **Hosting**: at [share.streamlit.io](https://share.streamlit.io), create an app from that repo with main file `home.py`
   (under Advanced settings, choose Python 3.12).
4. **Secrets**: in the app's settings → Secrets, paste the following (format as in `.streamlit/secrets.toml.example`):
   ```toml
   DATABASE_URL = "postgresql://...your Neon string..."
   SIGNUP_CODE = "a-code-you-share-with-people-you-invite"
   ```
5. Share the app URL and invite code. Each person creates an account and their portfolio is private to them.

To make this Mac use the same online accounts, add the same `DATABASE_URL` line to `.streamlit/secrets.toml`
and run `./dashboard.sh restart`.

Notes: free Streamlit apps sleep after a few days without visitors and wake on the next visit (about 30 seconds).
Yahoo sometimes rate-limits cloud servers; if prices fail to load there, wait a few minutes and use Refresh.
Signing in again is needed after a page reload.
