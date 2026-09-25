import datetime
import os

import pandas as pd
import pytz
import requests
import yfinance as yf


# =========================================================
# TELEGRAM
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

IST = pytz.timezone("Asia/Kolkata")

# Cloud Run-la TEST_MODE=true set pannina
# active-session time bypass aagum.
TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"


# =========================================================
# WATCHLIST
# =========================================================

WATCHLIST = {
    "GC=F": {
        "name": "XAU/USD (GOLD)",
        "emoji": "🥇",
        "buffer": 1.50,
        "dec": 2,
        "sym": "$",
        "min_body_ratio": 0.45,
    },

    "GBPUSD=X": {
        "name": "GBP/USD",
        "emoji": "💷",
        "buffer": 0.0015,
        "dec": 4,
        "sym": "",
        "min_body_ratio": 0.45,
    },

    "EURUSD=X": {
        "name": "EUR/USD",
        "emoji": "💶",
        "buffer": 0.0012,
        "dec": 4,
        "sym": "",
        "min_body_ratio": 0.45,
    },

    "USDJPY=X": {
        "name": "USD/JPY",
        "