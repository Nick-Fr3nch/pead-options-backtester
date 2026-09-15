#!/usr/bin/env python3
"""
Historical Price & Volume (OHLCV) Ingestion and PEAD Strategy Pipeline
"""

import asyncio
import logging
import os
import sqlite3
import ssl
from datetime import date, datetime, timedelta
from typing import Optional

import aiohttp
import certifi
import numpy as np
import pandas as pd


class AsyncPolygonOHLCV:
    """Asynchronous client for fetching Polygon.io daily OHLCV bars."""

    def __init__(self, api_key: str, timeout: float = 20.0):
        self.api_key = api_key
        self.timeout = timeout
        self.session: Optional[aiohttp.ClientSession] = None
        self.active = False
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            "https://api.polygon.io", connector=aiohttp.TCPConnector(verify_ssl=False)
        )
        self.active = True
        return self

    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
        self.active = False

    async def get_daily_ohlcv(
        self, ticker: str, start_date: date, end_date: date
    ) -> pd.DataFrame:
        """Fetches daily adjusted OHLCV bars from Polygon.io."""
        if not self.session or not self.active:
            raise RuntimeError("Must use async context manager")

        url = (
            f"/v2/aggs/ticker/{ticker}/range/1/day/"
            f"{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
            f"?adjusted=true&sort=asc&apiKey={self.api_key}"
        )

        records = []

        async with self.session.get(url, timeout=self.timeout) as resp:
            data = await resp.json()

        if data.get("status") == "ERROR":
            logging.error(f"Error fetching {ticker}: {data.get('error')}")
            return pd.DataFrame()

        def parse_results(res_list):
            for bar in res_list:
                dt = datetime.fromtimestamp(bar["t"] / 1000).strftime("%Y-%m-%d")
                records.append({
                    "ticker": ticker,
                    "date": dt,
                    "open": float(bar["o"]),
                    "high": float(bar["h"]),
                    "low": float(bar["l"]),
                    "close": float(bar["c"]),
                    "volume": float(bar["v"]),
                })

        if "results" in data:
            parse_results(data["results"])

        while "next_urlstring" in data:
            async with self.session.get(
                data["next_urlstring"], timeout=self.timeout
            ) as resp:
                data = await resp.json()
            if "results" in data:
                parse_results(data["results"])

        return pd.DataFrame(records)


def init_db(db_path: str = "data/ohlcv.db") -> sqlite3.Connection:
    """Initializes SQLite database schema for pricing data."""
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            PRIMARY KEY (ticker, date)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ticker_date ON ohlcv(ticker, date);")
    conn.commit()
    return conn


def save_ohlcv_to_db(df: pd.DataFrame, conn: sqlite3.Connection):
    """Saves DataFrame of OHLCV data into SQLite database."""
    if df.empty:
        return

    cursor = conn.cursor()
    records = df.to_dict("records")
    cursor.executemany(
        """
        INSERT OR IGNORE INTO ohlcv (ticker, date, open, high, low, close, volume)
        VALUES (:ticker, :date, :open, :high, :low, :close, :volume)
        """,
        records,
    )
    conn.commit()


def calculate_pre_earnings_vol(
    conn: sqlite3.Connection,
    ticker: str,
    earnings_date: str,
    lookback_days: int = 30,
) -> Optional[float]:
    """Calculates 30-day pre-earnings realized volatility."""
    query = """
        SELECT date, close FROM ohlcv 
        WHERE ticker = ? AND date < ? 
        ORDER BY date DESC LIMIT ?
    """
    df = pd.read_sql_query(query, conn, params=(ticker, earnings_date, lookback_days + 1))
    if len(df) < lookback_days:
        return None

    df = df.sort_values("date")
    df["log_ret"] = np.log(df["close"] / df["close"].shift(1))
    log_rets = df["log_ret"].dropna()

    if len(log_rets) < 5:
        return None

    return float(log_rets.std() * np.sqrt(252))


def calculate_post_earnings_adv(
    conn: sqlite3.Connection,
    ticker: str,
    earnings_date: str,
    window_days: int = 5,
) -> Optional[float]:
    """Calculates Average Daily Dollar Volume over 5 trading days post-earnings."""
    query = """
        SELECT date, close, volume FROM ohlcv 
        WHERE ticker = ? AND date >= ? 
        ORDER BY date ASC LIMIT ?
    """
    df = pd.read_sql_query(query, conn, params=(ticker, earnings_date, window_days))
    if len(df) < window_days:
        return None

    df["dollar_volume"] = df["close"] * df["volume"]
    return float(df["dollar_volume"].mean())


if __name__ == "__main__":
    import sys

    async def main():
        ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL"
        api_key = os.getenv("POLYGON_API_KEY", "YOUR_API_KEY")

        if api_key == "YOUR_API_KEY":
            print("Please set your POLYGON_API_KEY environment variable.")
            return

        end_date = date.today()
        start_date = end_date - timedelta(days=180)

        async with AsyncPolygonOHLCV(api_key) as client:
            df = await client.get_daily_ohlcv(ticker, start_date, end_date)
            if df.empty:
                return

            conn = init_db("data/ohlcv.db")
            save_ohlcv_to_db(df, conn)

            latest_date = df["date"].iloc[-10]
            vol = calculate_pre_earnings_vol(conn, ticker, latest_date)
            adv = calculate_post_earnings_adv(conn, ticker, latest_date)

            print(f"=== PEAD Metrics ({ticker}) ===")
            if vol:
                print(f"30-Day Pre-Earnings Volatility: {vol:.2%}")
            if adv:
                print(f"5-Day Post-Earnings ADV: ${adv:,.2f}")

            conn.close()

    asyncio.run(main())
