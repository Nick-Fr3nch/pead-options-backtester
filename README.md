# PEAD Options Backtester

An asynchronous data ingestion pipeline and quantitative backtesting engine designed for Post-Earnings Announcement Drift (PEAD) trading strategies.

## Overview
This project processes historical price and volume (OHLCV) data to evaluate volatility dynamics around earnings releases. It enforces strict liquidity constraints and derives pre-earnings realized volatility metrics used for positioning strategies.

## Features
- **Async Data Ingestion:** Asynchronous Polygon.io API integration with pagination support for historical pricing.
- **SQLite Storage:** Indexed SQL schema for localized, persistent pricing queries.
- **Quant Math Engine:** Realized volatility annualized calculations ($\sigma_{\text{stock}} = \text{std} \times \sqrt{252}$) and 5-day post-earnings Average Daily Dollar Volume ($\text{ADV}$) liquidity filtering.

## Repository Structure
```text
pead-options-backtester/
├── data_pipeline.py    # Core async API client, DB storage, & quant math functions
├── requirements.txt    # Python dependencies
└── README.md           # Documentation
