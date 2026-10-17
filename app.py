import io
import os
import time
from datetime import date, datetime

import altair as alt
import pandas as pd
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Stock Tracker", page_icon="📈", layout="wide")
st.title("📈 Stock Tracker")

FILE = "portfolio.csv"
HIST = "history.csv"
RANGES = ["1mo", "3mo", "6mo", "1y", "2y", "5y"]
DEFAULT = pd.DataFrame({
    "Ticker": ["VOO"],
    "Shares": [0.307],
    "Cost": [646.55],
    "Alert above": [0.0],
    "Alert below": [0.0],
})


def secret_holdings():
    """When hosted online, holdings come from the app's private Secrets, not from the repo."""
    try:
        return st.secrets["holdings_csv"]
    except Exception:
        return None


HOSTED_CSV = secret_holdings()


def load():
    if HOSTED_CSV:
        return pd.read_csv(io.StringIO(HOSTED_CSV))
    if os.path.exists(FILE):
        return pd.read_csv(FILE)
    return DEFAULT.copy()


@st.cache_data(ttl=10)
def quote(ticker):
    fi = yf.Ticker(ticker).fast_info
    return float(fi["last_price"]), float(fi["previous_close"])


@st.cache_data(ttl=300)
def history(ticker, period):
    return yf.Ticker(ticker).history(period=period)["Close"]


@st.cache_data(ttl=300)
def stats(ticker):
    t = yf.Ticker(ticker)
    fi = t.fast_info

    def g(key):
        try:
            return float(fi[key])
        except Exception:
            return None

    out = {
        "low": g("year_low"),
        "high": g("year_high"),
        "d50": g("fifty_day_average"),
        "d200": g("two_hundred_day_average"),
        "pe": None,
    }
    try:
        pe = t.info.get("trailingPE")
        out["pe"] = float(pe) if pe else None
    except Exception:
        pass
    return out


def num(x):
    try:
        v = float(x)
        return 0.0 if v != v else v
    except Exception:
        return 0.0


def usd(v):
    return f"-${abs(v):,.2f}" if v < 0 else f"${v:,.2f}"


def usd_signed(v):
    return f"-${abs(v):,.2f}" if v < 0 else f"+${v:,.2f}"


def money(v):
    return "n/a" if v is None else usd(v)


def pct(v):
    return "n/a" if v is None else f"{v:+.1f}%"


def log_value(total_value, total_invested):
    """Save one row per weekday. The last refresh of the day wins."""
    if date.today().weekday() >= 5 or total_value <= 0:
        return
    today = str(date.today())
    new = pd.DataFrame([{
        "Date": today,
        "Value": round(total_value, 2),
        "Invested": round(total_invested, 2),
    }])
    if os.path.exists(HIST):
        old = pd.read_csv(HIST)
        old = old[old["Date"] != today]
        new = pd.concat([old, new], ignore_index=True)
    new.to_csv(HIST, index=False)


def draw(plot, ycol, title, points=False):
    lo, hi = float(plot[ycol].min()), float(plot[ycol].max())
    pad = (hi - lo) * 0.08 or max(abs(hi) * 0.02, 1.0)
    chart = alt.Chart(plot).mark_line(point=points).encode(
        x=alt.X("Date:T", title=None),
        y=alt.Y(f"{ycol}:Q", title=title, scale=alt.Scale(domain=[lo - pad, hi + pad])),
        color=alt.Color("Series:N", title=None, legend=alt.Legend(orient="bottom")),
    )
    st.altair_chart(chart, width="stretch")


def clean_index(s):
    s = s.copy()
    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
    return s


try:
    # ---------- Sidebar ----------
    st.sidebar.header("Your holdings")
    st.sidebar.caption("Shares = 0 means watch only. Leave alerts at 0 to turn them off.")
    edited = st.sidebar.data_editor(load(), num_rows="dynamic", hide_index=True, width="stretch")
    if HOSTED_CSV:
        st.sidebar.caption("Holdings come from this app's Secrets. Edits here last only until you refresh.")
    elif st.sidebar.button("Save holdings"):
        edited.to_csv(FILE, index=False)
        st.sidebar.success("Saved to portfolio.csv")
    refresh = st.sidebar.slider("Refresh every (seconds)", 15, 300, 30)

    holdings = edited.dropna(subset=["Ticker"]).copy()
    holdings["Ticker"] = holdings["Ticker"].astype(str).str.upper().str.strip()
    holdings = holdings[holdings["Ticker"] != ""]

    # ---------- Live numbers ----------
    rows, alerts = [], []
    total_invested = 0.0
    for _, r in holdings.iterrows():
        t = r["Ticker"]
        try:
            price, prev = quote(t)
        except Exception:
            st.warning(f"Could not get a price for {t}. Check the ticker symbol.")
            continue
        shares, cost = num(r["Shares"]), num(r["Cost"])
        above, below = num(r["Alert above"]), num(r["Alert below"])
        value, invested = price * shares, cost * shares
        total_invested += invested
        flag = ""
        if above and price >= above:
            flag = f"above {above:,.2f}"
        elif below and price <= below:
            flag = f"below {below:,.2f}"
        if flag:
            alerts.append(f"{t} is {flag} (now {price:,.2f})")
        rows.append({
            "Ticker": t,
            "Price": price,
            "Day %": (price - prev) / prev * 100,
            "Shares": shares,
            "Value": value,
            "Day $": (price - prev) * shares,
            "Gain/Loss $": value - invested if invested else 0.0,
            "Gain/Loss %": (value - invested) / invested * 100 if invested else 0.0,
            "Alert": flag,
        })

    if not rows:
        st.info("Add a ticker in the sidebar to get started.")
    else:
        df = pd.DataFrame(rows)
        log_value(df["Value"].sum(), total_invested)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Portfolio value", usd(df["Value"].sum()))
        c2.metric("Today", usd(df["Day $"].sum()))
        c3.metric("Total gain / loss", usd(df["Gain/Loss $"].sum()))
        c4.metric("Active alerts", len(alerts))
        for a in alerts:
            st.warning(a)

        def color(v):
            if isinstance(v, (int, float)) and v != 0:
                return "color: #1faa59" if v > 0 else "color: #e5484d"
            return ""

        styled = df.style.map(
            color, subset=["Day %", "Day $", "Gain/Loss $", "Gain/Loss %"]
        ).format({
            "Price": usd, "Day %": "{:+.2f}%", "Shares": "{:g}",
            "Value": usd, "Day $": usd_signed,
            "Gain/Loss $": usd_signed, "Gain/Loss %": "{:+.2f}%",
        })
        st.dataframe(styled, hide_index=True, width="stretch")
        st.caption(f"Last updated {datetime.now().strftime('%I:%M:%S %p')}. Free data can be delayed a few minutes.")

        # ---------- Allocation ----------
        st.subheader("Allocation")
        alloc = df[df["Value"] > 0][["Ticker", "Value"]].copy()
        if alloc.empty:
            st.info("Allocation shows up once you enter shares for at least one holding.")
        else:
            alloc["Weight"] = alloc["Value"] / alloc["Value"].sum() * 100
            left, right = st.columns(2)
            donut = alt.Chart(alloc).mark_arc(innerRadius=60).encode(
                theta=alt.Theta("Value:Q"),
                color=alt.Color("Ticker:N", title=None, legend=alt.Legend(orient="bottom")),
                tooltip=[
                    "Ticker",
                    alt.Tooltip("Value:Q", format="$,.2f"),
                    alt.Tooltip("Weight:Q", format=".1f", title="Weight (%)"),
                ],
            )
            left.altair_chart(donut, width="stretch")
            right.dataframe(
                pd.DataFrame({
                    "Ticker": alloc["Ticker"],
                    "Value": alloc["Value"].map(usd),
                    "Weight": alloc["Weight"].map(lambda w: f"{w:.1f}%"),
                }),
                hide_index=True,
                width="stretch",
            )
            if len(alloc) == 1:
                st.caption("With one holding it is 100%. This gets more interesting as you add more.")

        # ---------- Key stats ----------
        st.subheader("Key stats")
        stat_rows = []
        for _, r in df.iterrows():
            s = stats(r["Ticker"])
            p = r["Price"]
            stat_rows.append({
                "Ticker": r["Ticker"],
                "52w low": money(s["low"]),
                "52w high": money(s["high"]),
                "From 52w high": pct((p / s["high"] - 1) * 100 if s["high"] else None),
                "vs 50-day avg": pct((p / s["d50"] - 1) * 100 if s["d50"] else None),
                "vs 200-day avg": pct((p / s["d200"] - 1) * 100 if s["d200"] else None),
                "P/E": f"{s['pe']:.1f}" if s["pe"] else "n/a",
            })
        st.dataframe(pd.DataFrame(stat_rows), hide_index=True, width="stretch")
        st.caption("The 50-day and 200-day columns show how far the price sits above (+) or below (-) its average. P/E is often n/a for ETFs.")

    # ---------- Portfolio history ----------
    st.subheader("Portfolio history")
    if os.path.exists(HIST):
        hist = pd.read_csv(HIST)
    else:
        hist = pd.DataFrame(columns=["Date", "Value", "Invested"])
    if len(hist) >= 2:
        hist["Date"] = pd.to_datetime(hist["Date"])
        hist = hist.rename(columns={"Value": "Portfolio value", "Invested": "Amount invested"})
        long = hist.melt(
            id_vars="Date",
            value_vars=["Portfolio value", "Amount invested"],
            var_name="Series",
            value_name="Dollars",
        ).dropna()
        draw(long, "Dollars", "Dollars ($)", points=True)
        st.caption("The gap between the lines is your gain or loss.")
    else:
        st.info(
            f"History builds up on its own: one point per weekday while this app is running. "
            f"{len(hist)} day(s) saved so far, and the chart appears at 2."
        )

    # ---------- Price chart ----------
    st.subheader("Price chart")
    if len(holdings):
        left, right = st.columns([2, 1])
        pick = left.selectbox("Ticker", list(holdings["Ticker"]), key="pc_ticker")
        period = right.selectbox("Range", RANGES, index=2, key="pc_range")
        custom = st.text_input("Or type any ticker", "", key="pc_custom").upper().strip()
        sym = custom or pick
        try:
            h = clean_index(history(sym, period))
            plot = pd.DataFrame({
                f"{sym} price": h,
                "20-day average": h.rolling(20).mean(),
            })
            plot.index.name = "Date"
            plot = plot.reset_index().melt(id_vars="Date", var_name="Series", value_name="Price").dropna()
            draw(plot, "Price", "Price ($)")
        except Exception:
            st.error(f"Could not load history for {sym}.")

    # ---------- Benchmark comparison ----------
    st.subheader("Benchmark comparison")
    if len(holdings):
        b1, b2, b3 = st.columns(3)
        sym_a = b1.selectbox("Holding", list(holdings["Ticker"]), key="bm_hold")
        bench = b2.selectbox("Benchmark", ["SPY", "QQQ", "VTI", "DIA", "IWM"], key="bm_bench")
        per = b3.selectbox("Range", RANGES, index=3, key="bm_range")
        custom_b = st.text_input("Or type a different benchmark ticker", "", key="bm_custom").upper().strip()
        bench = custom_b or bench

        if sym_a == bench:
            st.info("Pick a benchmark that is different from the holding.")
        else:
            try:
                a = clean_index(history(sym_a, per)).rename(sym_a)
                b = clean_index(history(bench, per)).rename(bench)
                both = pd.concat([a, b], axis=1).dropna()
                if len(both) < 2:
                    st.error("Not enough overlapping data for that range.")
                else:
                    ret = (both / both.iloc[0] - 1) * 100
                    end = ret.iloc[-1]
                    m1, m2, m3 = st.columns(3)
                    m1.metric(f"{sym_a} return", pct(end[sym_a]))
                    m2.metric(f"{bench} return", pct(end[bench]))
                    m3.metric("Difference", f"{end[sym_a] - end[bench]:+.1f} pts")
                    ret.index.name = "Date"
                    plot = ret.reset_index().melt(id_vars="Date", var_name="Series", value_name="Return")
                    draw(plot, "Return", "Return since start (%)")
                    st.caption("Both lines start at 0% on the first day of the range. Prices from this data source are usually adjusted for splits and dividends, so returns roughly include dividends.")
            except Exception:
                st.error(f"Could not compare {sym_a} with {bench}. Check the ticker symbols.")

except Exception as e:
    st.exception(e)
    st.stop()

# ---------- Auto refresh ----------
time.sleep(refresh)
st.rerun()
